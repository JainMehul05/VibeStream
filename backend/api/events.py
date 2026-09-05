"""Event definitions and queue operations for async feedback processing.

Events are enqueued by the API and processed by the background worker.
Each event has a type, payload, and metadata for tracing and idempotency.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

from .feedback_processing import (
    _apply_posterior,
    _bump_calibration,
    _featurize,
    _invalidate_user_cache,
    _revert_posterior,
    _update_preferences,
)
from . import feedback_store
from .models import UserProfile

logger = structlog.get_logger(__name__)

# Redis key for the event queue
EVENT_QUEUE_KEY = "vibestream:events:queue"
EVENT_PROCESSING_KEY = "vibestream:events:processing"
EVENT_DEAD_LETTER_KEY = "vibestream:events:dead_letter"


class EventType(str, Enum):
    """Types of events that can be processed asynchronously."""

    FEEDBACK_TRACK = "feedback_track"      # like, unlike, open_deezer, clear
    FEEDBACK_MOOD = "feedback_mood"        # mood correction
    CACHE_INVALIDATE = "cache_invalidate"  # invalidate recommendation cache
    PROFILE_UPDATE = "profile_update"      # user profile/preference update


@dataclass
class Event:
    """Base event structure."""

    type: EventType
    payload: dict
    user_id: str
    idempotency_key: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retry_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str) -> "Event":
        d = json.loads(data)
        d["type"] = EventType(d["type"])
        return cls(**d)


# Event payload schemas (for documentation/validation)
FEEDBACK_TRACK_PAYLOAD = {
    "track_id": "str",
    "signal": "str",  # like, unlike, open_deezer, clear
    "context_emotion": "str|None",
    "track": "dict|None",  # full track dict for feature extraction
    "features": "list|None",  # pre-computed feature vector
}

FEEDBACK_MOOD_PAYLOAD = {
    "predicted": "str",
    "actual": "str",
    "input_type": "str",
    "confidence": "float|None",
    "session_id": "str|None",
}

CACHE_INVALIDATE_PAYLOAD = {
    "user_id": "str",
    "pattern": "str",  # e.g., "rec:{user_id}:*"
}

PROFILE_UPDATE_PAYLOAD = {
    "update_type": "str",  # preferences, calibration, taste_profile
    "data": "dict",
}


def create_feedback_track_event(
    user_id: str,
    track_id: str,
    signal: str,
    context_emotion: Optional[str] = None,
    track: Optional[dict] = None,
    features: Optional[list] = None,
    idempotency_key: Optional[str] = None,
) -> Event:
    """Create a track feedback event."""
    return Event(
        type=EventType.FEEDBACK_TRACK,
        payload={
            "track_id": track_id,
            "signal": signal,
            "context_emotion": context_emotion,
            "track": track,
            "features": features,
        },
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


def create_feedback_mood_event(
    user_id: str,
    predicted: str,
    actual: str,
    input_type: str,
    confidence: Optional[float] = None,
    session_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Event:
    """Create a mood correction event."""
    return Event(
        type=EventType.FEEDBACK_MOOD,
        payload={
            "predicted": predicted,
            "actual": actual,
            "input_type": input_type,
            "confidence": confidence,
            "session_id": session_id,
        },
        user_id=user_id,
        idempotency_key=idempotency_key,
    )


def create_cache_invalidate_event(
    user_id: str,
    pattern: str,
) -> Event:
    """Create a cache invalidation event."""
    return Event(
        type=EventType.CACHE_INVALIDATE,
        payload={"user_id": user_id, "pattern": pattern},
        user_id=user_id,
    )


def create_profile_update_event(
    user_id: str,
    update_type: str,
    data: dict,
) -> Event:
    """Create a profile update event."""
    return Event(
        type=EventType.PROFILE_UPDATE,
        payload={"update_type": update_type, "data": data},
        user_id=user_id,
    )


# Queue operations
def enqueue_event(redis_client, event: Event) -> bool:
    """Add event to the processing queue.

    Uses Redis LPUSH for FIFO queue semantics.
    Returns True if enqueued successfully.
    """
    try:
        redis_client.lpush(EVENT_QUEUE_KEY, event.to_json())
        logger.info(
            "event_enqueued event_id=%s type=%s user_id=%s",
            event.event_id, event.type.value, event.user_id
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("event_enqueue_failed event_id=%s error=%s", event.event_id, str(e))
        return False


def dequeue_event(redis_client, timeout: int = 5) -> Optional[Event]:
    """Block and wait for an event from the queue.

    Uses Redis BRPOP for blocking pop.
    Returns Event or None on timeout.
    """
    try:
        result = redis_client.brpop(EVENT_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        _, data = result
        return Event.from_json(data)
    except Exception as e:  # noqa: BLE001
        logger.error("event_dequeue_failed error=%s", str(e))
        return None


def requeue_event(redis_client, event: Event) -> bool:
    """Re-queue an event for retry (increments retry_count)."""
    event.retry_count += 1
    return enqueue_event(redis_client, event)


def move_to_dead_letter(redis_client, event: Event, error: str) -> bool:
    """Move failed event to dead letter queue."""
    try:
        event.metadata["failure_reason"] = error
        event.metadata["failed_at"] = datetime.now(timezone.utc).isoformat()
        redis_client.lpush(EVENT_DEAD_LETTER_KEY, event.to_json())
        logger.warning("event_dead_lettered event_id=%s error=%s", event.event_id, error)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("dead_letter_failed event_id=%s error=%s", event.event_id, str(e))
        return False


def get_queue_length(redis_client) -> int:
    """Get current queue length."""
    try:
        return redis_client.llen(EVENT_QUEUE_KEY)
    except Exception:  # noqa: BLE001
        return -1


def get_dead_letter_length(redis_client) -> int:
    """Get dead letter queue length."""
    try:
        return redis_client.llen(EVENT_DEAD_LETTER_KEY)
    except Exception:  # noqa: BLE001
        return -1


def process_feedback_track(event: Event, redis_client) -> None:
    """Process a track feedback event."""
    payload = event.payload
    username = event.user_id
    track_id = payload["track_id"]
    signal = payload["signal"]
    context_emotion = payload.get("context_emotion")
    track = payload.get("track")
    features = payload.get("features")

    logger.info("processing_feedback_track", username=username, track_id=track_id, signal=signal)

    # Process based on signal type
    if signal == "open_deezer":
        # Implicit positive signal - purely additive
        _apply_posterior(username, _featurize(track, context_emotion), "open_deezer")
        _update_preferences(username, track, context_emotion, "open_deezer")
        
        # Persist to time-series store
        try:
            feedback_store.insert_track_feedback(
                username=username,
                track_id=track_id,
                signal=signal,
                context_emotion=context_emotion,
                features=features,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("feedback_store_insert_failed", username=username, error=str(e))
    else:
        # Set-vote semantics for like/unlike/clear
        prior = feedback_store.get_active_vote(username, track_id)
        prior_signal = prior["signal"] if prior else None

        new_features = _featurize(track, context_emotion) if signal in ("like", "unlike") else None

        # Reconcile prior vote
        if prior_signal in ("like", "unlike") and prior_signal != signal:
            _revert_posterior(username, prior.get("features"), prior_signal)

        if signal in ("like", "unlike") and signal != prior_signal:
            _apply_posterior(username, new_features, signal)

        # Update explicit preferences
        if signal in ("like", "unlike", "clear"):
            _update_preferences(username, track, context_emotion, signal)

        # Persist the event with features (single insert)
        try:
            feedback_store.insert_track_feedback(
                username=username,
                track_id=track_id,
                signal=signal,
                context_emotion=context_emotion,
                features=new_features,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("feedback_store_insert_failed", username=username, error=str(e))

    # Invalidate recommendation cache for this user
    _invalidate_user_cache(redis_client, username)
    logger.info("feedback_track_processed", username=username, track_id=track_id, signal=signal)


def process_feedback_mood(event: Event, redis_client) -> None:
    """Process a mood correction event."""
    payload = event.payload
    username = event.user_id
    predicted = payload["predicted"]
    actual = payload["actual"]
    input_type = payload["input_type"]
    confidence = payload.get("confidence")
    session_id = payload.get("session_id")

    logger.info("processing_feedback_mood", username=username, predicted=predicted, actual=actual)

    # Persist to time-series store
    try:
        feedback_store.insert_mood_feedback(
            username=username,
            predicted=predicted,
            actual=actual,
            input_type=input_type,
            confidence=confidence,
            session_id=session_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("mood_feedback_store_failed", username=username, error=str(e))

    # Update calibration map
    _bump_calibration(username, predicted, actual)

    # Invalidate cache since calibration affects recommendations
    _invalidate_user_cache(redis_client, username)
    logger.info("feedback_mood_processed", username=username, predicted=predicted, actual=actual)