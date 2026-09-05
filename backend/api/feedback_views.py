"""``POST /api/feedback/`` -- unified user-feedback endpoint.

Phase 3: Async event-driven feedback processing.
- Validates request and creates event
- Enqueues event for background worker processing
- Returns 202 Accepted immediately
- Worker processes: calibration, bandit, preferences, cache invalidation

Idempotency supported via Idempotency-Key header.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.api_docs import RESP_401, Tags, _obj, error_response, ok_message

from . import bandit, feedback_store, track_features
from . import preference_profile
from .models import UserProfile
from .events import (
    EventType,
    create_feedback_track_event,
    create_feedback_mood_event,
    enqueue_event,
)

logger = logging.getLogger(__name__)

# Canonical labels = BERT classifier outputs + the "neutral" fallback.
# Kept here (not imported from modal_inference) because the Django app
# must not depend on the inference image; the value is small and frozen.
_CANONICAL_EMOTIONS = frozenset({
    "sadness", "joy", "love", "anger", "fear", "neutral",
})

_KIND_MOOD = "mood"
_KIND_TRACK = "track"

# Loose upper bounds -- enough to fit any real payload, tight enough to
# bound the cost of a malicious caller spamming the endpoint.
_MAX_TRACK_ID_LEN = 128
_MAX_SESSION_ID_LEN = 128


# ---------------------------------------------------------------------------
# Swagger schemas
# ---------------------------------------------------------------------------
_MOOD_FEEDBACK_BODY = _obj(
    properties={
        "kind": openapi.Schema(type=openapi.TYPE_STRING, enum=[_KIND_MOOD],
                               example=_KIND_MOOD),
        "predicted": openapi.Schema(type=openapi.TYPE_STRING,
                                    enum=sorted(_CANONICAL_EMOTIONS),
                                    example="joy",
                                    description="The label the model produced."),
        "actual": openapi.Schema(type=openapi.TYPE_STRING,
                                 enum=sorted(_CANONICAL_EMOTIONS),
                                 example="love",
                                 description="The label the user says is correct."),
        "input_type": openapi.Schema(type=openapi.TYPE_STRING,
                                     enum=sorted(feedback_store.INPUT_TYPES),
                                     example="text"),
        "confidence": openapi.Schema(type=openapi.TYPE_NUMBER, format="float",
                                     minimum=0.0, maximum=1.0, nullable=True,
                                     example=0.82,
                                     description="Optional softmax probability for the predicted label."),
        "session_id": openapi.Schema(type=openapi.TYPE_STRING, nullable=True,
                                     example="b1c8...-uuid",
                                     description="Optional client-side session id used to correlate corrections."),
    },
    required=["kind", "predicted", "actual", "input_type"],
)

_TRACK_FEEDBACK_BODY = _obj(
    properties={
        "kind": openapi.Schema(type=openapi.TYPE_STRING, enum=[_KIND_TRACK],
                               example=_KIND_TRACK),
        "track_id": openapi.Schema(type=openapi.TYPE_STRING,
                                   example="deezer:12345",
                                   description="Stable identifier for the rated track."),
        "signal": openapi.Schema(type=openapi.TYPE_STRING,
                                 enum=sorted(feedback_store.TRACK_SIGNALS),
                                 example="like"),
        "context_emotion": openapi.Schema(type=openapi.TYPE_STRING, nullable=True,
                                          example="joy",
                                          description="The emotion that produced the recommendation list this rating belongs to."),
        "track": openapi.Schema(
            type=openapi.TYPE_OBJECT, nullable=True,
            description=(
                "Optional full track dict (same shape the recommender "
                "returns). When supplied, the bandit posterior and "
                "preferences are updated for the signed-in user."
            ),
        ),
    },
    required=["kind", "track_id", "signal"],
)

# drf-yasg doesn't model `oneOf` cleanly across drf versions; the body
# schema renders as the mood variant with the track variant called out
# in the description. Validation enforces the real contract.
_FEEDBACK_BODY = _MOOD_FEEDBACK_BODY


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate(payload: dict) -> tuple[dict | None, str | None]:
    """Return (cleaned_payload, None) on success; (None, error) otherwise."""
    if not isinstance(payload, dict):
        return None, "Body must be a JSON object."

    kind = payload.get("kind")
    if kind == _KIND_MOOD:
        return _validate_mood(payload)
    if kind == _KIND_TRACK:
        return _validate_track(payload)
    return None, "Field 'kind' must be either 'mood' or 'track'."


def _validate_mood(payload: dict) -> tuple[dict | None, str | None]:
    predicted = (payload.get("predicted") or "").strip().lower()
    actual = (payload.get("actual") or "").strip().lower()
    input_type = (payload.get("input_type") or "").strip().lower()

    if predicted not in _CANONICAL_EMOTIONS:
        return None, f"Field 'predicted' must be one of {sorted(_CANONICAL_EMOTIONS)}."
    if actual not in _CANONICAL_EMOTIONS:
        return None, f"Field 'actual' must be one of {sorted(_CANONICAL_EMOTIONS)}."
    if input_type not in feedback_store.INPUT_TYPES:
        return None, f"Field 'input_type' must be one of {sorted(feedback_store.INPUT_TYPES)}."

    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return None, "Field 'confidence' must be a number between 0 and 1."
        if not 0.0 <= confidence <= 1.0:
            return None, "Field 'confidence' must be between 0 and 1."

    session_id = payload.get("session_id")
    if session_id is not None:
        if not isinstance(session_id, str) or len(session_id) > _MAX_SESSION_ID_LEN:
            return None, f"Field 'session_id' must be a string of <= {_MAX_SESSION_ID_LEN} chars."

    return {
        "kind": _KIND_MOOD,
        "predicted": predicted,
        "actual": actual,
        "input_type": input_type,
        "confidence": confidence,
        "session_id": session_id,
    }, None


def _validate_track(payload: dict) -> tuple[dict | None, str | None]:
    track_id = payload.get("track_id")
    signal = (payload.get("signal") or "").strip().lower()
    context_emotion = payload.get("context_emotion")
    track = payload.get("track")

    if not isinstance(track_id, str) or not track_id.strip():
        return None, "Field 'track_id' is required."
    track_id = track_id.strip()
    if len(track_id) > _MAX_TRACK_ID_LEN:
        return None, f"Field 'track_id' must be <= {_MAX_TRACK_ID_LEN} chars."

    if signal not in feedback_store.TRACK_SIGNALS:
        return None, f"Field 'signal' must be one of {sorted(feedback_store.TRACK_SIGNALS)}."

    if context_emotion is not None:
        if not isinstance(context_emotion, str):
            return None, "Field 'context_emotion' must be a string."
        context_emotion = context_emotion.strip().lower() or None
        if context_emotion is not None and context_emotion not in _CANONICAL_EMOTIONS:
            return None, f"Field 'context_emotion' must be one of {sorted(_CANONICAL_EMOTIONS)}."

    if track is not None and not isinstance(track, dict):
        return None, "Field 'track' must be a JSON object when supplied."

    return {
        "kind": _KIND_TRACK,
        "track_id": track_id,
        "signal": signal,
        "context_emotion": context_emotion,
        "track": track,
    }, None


def _extract_idempotency_key(request) -> str | None:
    """Extract Idempotency-Key from request headers."""
    return request.META.get("HTTP_IDEMPOTENCY_KEY")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@swagger_auto_schema(
    method="post",
    tags=[Tags.INFERENCE],
    operation_summary="Submit mood / track feedback (async)",
    operation_description=(
        "Single endpoint for both RL surfaces.\n\n"
        "**Mood correction (`kind=\"mood\"`)** -- record that the user "
        "disagreed (or agreed) with a detected emotion. Per-user calibration "
        "is updated asynchronously by the background worker.\n\n"
        "**Track signal (`kind=\"track\"`)** -- record a 👍 / 👎 / Open-in-"
        "Deezer event for a track. Feeds the Thompson Sampling bandit re-ranker "
        "and updates explicit preferences asynchronously.\n\n"
        "Requires a user JWT (`Authorization: Bearer <access>`).\n\n"
        "Returns **202 Accepted** immediately. The feedback is queued for "
        "asynchronous processing. Idempotency supported via "
        "`Idempotency-Key` header (recommended for track signals)."
    ),
    request_body=_FEEDBACK_BODY,
    manual_parameters=[
        openapi.Parameter(
            name="Idempotency-Key",
            in_=openapi.IN_HEADER,
            type=openapi.TYPE_STRING,
            required=False,
            description="Optional idempotency key for safe retries. Same key returns cached response.",
        ),
    ],
    responses={
        202: ok_message("Feedback accepted for processing.", "Feedback queued."),
        400: error_response("Schema validation failed.",
                            "Field 'kind' must be either 'mood' or 'track'."),
        401: RESP_401,
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def feedback(request):
    """Accept feedback and queue for async processing."""
    cleaned, error = _validate(request.data or {})
    if error is not None:
        return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

    username = request.user.username
    assert cleaned is not None  # narrowing for type-checkers

    # Extract idempotency key from header
    idem_key = _extract_idempotency_key(request)

    if cleaned["kind"] == _KIND_MOOD:
        event = create_feedback_mood_event(
            user_id=username,
            predicted=cleaned["predicted"],
            actual=cleaned["actual"],
            input_type=cleaned["input_type"],
            confidence=cleaned["confidence"],
            session_id=cleaned["session_id"],
            idempotency_key=idem_key,
        )
    else:  # track feedback
        event = create_feedback_track_event(
            user_id=username,
            track_id=cleaned["track_id"],
            signal=cleaned["signal"],
            context_emotion=cleaned["context_emotion"],
            track=cleaned["track"],
            idempotency_key=idem_key,
        )

    # Enqueue event for asynchronous processing by background worker
    # Synchronous mode for testing (controlled by FEEDBACK_SYNC_MODE setting)
    from django.conf import settings
    if getattr(settings, "FEEDBACK_SYNC_MODE", False):
        from .events import process_feedback_track, process_feedback_mood
        from django.core.cache import cache
        redis_client = cache._cache.get_client(write=True)
        if event.type == EventType.FEEDBACK_MOOD:
            process_feedback_mood(event, redis_client)
        else:
            process_feedback_track(event, redis_client)
        logger.info("feedback_processed_sync username=%s event_id=%s type=%s", username, event.event_id, event.type.value)
    else:
        from .events import enqueue_event
        from django.core.cache import cache
        redis_client = cache._cache.get_client(write=True)
        enqueue_event(redis_client, event)
        logger.info("feedback_enqueued username=%s event_id=%s type=%s", username, event.event_id, event.type.value)
    return Response(
        {"message": "Feedback accepted for processing.", "event_id": event.event_id},
        status=status.HTTP_202_ACCEPTED,
    )


@swagger_auto_schema(
    method="get",
    tags=[Tags.INFERENCE],
    operation_summary="Read the user's like/dislike state for tracks",
    operation_description=(
        "Returns the signed-in user's latest explicit vote for each track id "
        "in the comma-separated `ids` query param, so the UI can restore the "
        "like/dislike button state after a reload. Implicit `open_deezer` "
        "signals are excluded."
    ),
    responses={
        200: ok_message("Map of track_id -> 'like' | 'unlike'.", "{}"),
        401: RESP_401,
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def track_feedback_state(request):
    """Return ``{feedback: {track_id: 'like'|'unlike'}}`` for the caller."""
    raw = request.query_params.get("ids", "") or ""
    # Cap the batch so a crafted query can't issue an unbounded $in.
    track_ids = [t for t in (s.strip() for s in raw.split(",")) if t][:200]
    username = getattr(request.user, "username", None)
    if not username or not track_ids:
        return Response({"feedback": {}})
    fb = feedback_store.query_track_feedback(username, track_ids)
    return Response({"feedback": fb})
