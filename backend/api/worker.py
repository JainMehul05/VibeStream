"""Background worker for processing async events.

The worker runs as a separate process and consumes events from the Redis queue.
It handles feedback processing, cache invalidation, and profile updates
with retry logic and failure handling.
"""

import os
import signal
import sys
import time
from typing import Optional

import django
import redis

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from django.conf import settings
from django.core.cache import cache

from api.feedback_processing import (
    _apply_posterior,
    _bump_calibration,
    _featurize,
    _invalidate_user_cache,
    _revert_posterior,
    _update_preferences,
)
from api.events import (
    Event,
    EventType,
    dequeue_event,
    enqueue_event,
    get_dead_letter_length,
    get_queue_length,
    move_to_dead_letter,
    requeue_event,
)
from api import feedback_store
from api.models import UserProfile
from api.retry import MODAL_RETRY_POLICY, MONGODB_RETRY_POLICY, REDIS_RETRY_POLICY, RetryExhausted

import structlog

logger = structlog.get_logger(__name__)

# Worker configuration
WORKER_ID = f"worker-{os.getpid()}"
MAX_RETRIES = 3
SHUTDOWN_TIMEOUT = 30  # seconds

# Global shutdown flag
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.info("shutdown_signal_received", signal=signum, worker_id=WORKER_ID)
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def get_redis_client():
    """Get Redis client from Django cache backend."""
    # Try to get Redis connection from cache backend
    try:
        backend = cache._cache.get_client(write=True)
        return backend
    except Exception:
        # Fallback: create direct connection
        redis_url = getattr(settings, "CACHE_REDIS_URL", "redis://localhost:6379/0")
        return redis.from_url(redis_url, decode_responses=True)


def _bump_calibration(username: str, predicted: str, actual: str) -> None:
    """Increment mood_calibration[predicted][actual] on the profile."""
    if predicted == actual:
        return
    try:
        profile = UserProfile.objects(username=username).first()
        if profile is None:
            logger.warning("calibration_profile_missing", username=username)
            return
        calibration = dict(profile.mood_calibration or {})
        bucket = dict(calibration.get(predicted, {}) or {})
        bucket[actual] = int(bucket.get(actual, 0)) + 1
        calibration[predicted] = bucket
        profile.mood_calibration = calibration
        profile.save()
        logger.info("calibration_updated", username=username, predicted=predicted, actual=actual)
    except Exception as e:  # noqa: BLE001
        logger.error("calibration_update_failed", username=username, error=str(e))
        raise


def _featurize(track: dict | None, context_emotion: str | None):
    """Feature vector for a track, or None if missing/unfeaturizable."""
    if track is None:
        return None
    try:
        return track_features.featurize(track, context_emotion=context_emotion)
    except Exception as e:  # noqa: BLE001
        logger.warning("feature_extraction_failed", error=str(e))
        return None


def _apply_posterior(username: str, features, signal: str) -> None:
    """Add signal's contribution to the user's posterior."""
    if not features:
        return
    try:
        profile = UserProfile.objects(username=username).first()
        if profile is None:
            return
        profile.taste_profile = bandit.update_posterior(
            profile.taste_profile or {}, features, signal
        )
        profile.save()
        logger.info("taste_profile_updated", username=username, signal=signal, events=profile.taste_profile.get("events"))
    except Exception as e:  # noqa: BLE001
        logger.error("taste_profile_update_failed", username=username, error=str(e))
        raise


def _revert_posterior(username: str, features, signal: str) -> None:
    """Subtract a previously-applied vote."""
    if not features:
        return
    try:
        profile = UserProfile.objects(username=username).first()
        if profile is None:
            return
        profile.taste_profile = bandit.revert_posterior(
            profile.taste_profile or {}, features, signal
        )
        profile.save()
        logger.info("taste_profile_reverted", username=username, signal=signal, events=profile.taste_profile.get("events"))
    except Exception as e:  # noqa: BLE001
        logger.error("taste_profile_revert_failed", username=username, error=str(e))
        raise


def _update_preferences(
    username: str,
    track: dict | None,
    context_emotion: str | None,
    signal: str,
) -> None:
    """Update user's explicit preference profile from track feedback."""
    if not track:
        return
    try:
        profile = UserProfile.objects(username=username).first()
        if profile is None:
            return

        profile_dict = {
            "genre_preferences": dict(getattr(profile, "genre_preferences", {})),
            "artist_preferences": dict(getattr(profile, "artist_preferences", {})),
            "era_preferences": dict(getattr(profile, "era_preferences", {})),
            "mood_preferences": dict(getattr(profile, "mood_preferences", {})),
            "interaction_counts": dict(getattr(profile, "interaction_counts", {})),
            "exploration_preference": getattr(profile, "exploration_preference", 0.3),
        }

        updated = update_preferences_from_feedback(
            profile_dict, track, signal, context_emotion
        )

        profile.genre_preferences = updated["genre_preferences"]
        profile.artist_preferences = updated["artist_preferences"]
        profile.era_preferences = updated["era_preferences"]
        profile.mood_preferences = updated["mood_preferences"]
        profile.interaction_counts = updated["interaction_counts"]
        profile.exploration_preference = updated["exploration_preference"]
        profile.save()
        logger.info("preferences_updated", username=username, signal=signal)
    except Exception as e:  # noqa: BLE001
        logger.error("preferences_update_failed", username=username, error=str(e))
        raise


def _invalidate_user_cache(redis_client, user_id: str, pattern: str = None) -> None:
    """Invalidate recommendation cache for a user.

    Uses SCAN-based iteration to avoid blocking Redis.
    """
    try:
        if pattern is None:
            pattern = f"rec:{user_id}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                redis_client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info("cache_invalidated", user_id=user_id, pattern=pattern, keys_deleted=deleted)
        else:
            logger.debug("cache_invalidate_no_keys", user_id=user_id, pattern=pattern)
    except Exception as e:  # noqa: BLE001
        logger.error("cache_invalidate_failed", user_id=user_id, error=str(e))
        raise


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

    # Persist to time-series store (synchronous, fire-and-forget)
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

    # Process based on signal type
    if signal == "open_deezer":
        # Implicit positive signal - purely additive
        _apply_posterior(username, _featurize(track, context_emotion), "open_deezer")
        _update_preferences(username, track, context_emotion, "open_deezer")
    else:
        # Set-vote semantics for like/unlike/clear
        prior = feedback_store.get_active_vote(username, track_id)
        prior_signal = prior["signal"] if prior else None

        new_features = _featurize(track, context_emotion) if signal in ("like", "unlike") else None

        # Persist the event with features
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

        # Reconcile prior vote
        if prior_signal in ("like", "unlike") and prior_signal != signal:
            _revert_posterior(username, prior.get("features"), prior_signal)

        if signal in ("like", "unlike") and signal != prior_signal:
            _apply_posterior(username, new_features, signal)

        # Update explicit preferences
        if signal in ("like", "unlike", "clear"):
            _update_preferences(username, track, context_emotion, signal)

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


def process_cache_invalidate(event: Event, redis_client) -> None:
    """Process a cache invalidation event."""
    payload = event.payload
    user_id = payload["user_id"]
    pattern = payload.get("pattern")

    logger.info("processing_cache_invalidate", user_id=user_id, pattern=pattern)
    _invalidate_user_cache(redis_client, user_id, pattern)
    logger.info("cache_invalidate_processed", user_id=user_id)


def process_profile_update(event: Event, redis_client) -> None:
    """Process a profile update event."""
    payload = event.payload
    user_id = event.user_id
    update_type = payload["update_type"]
    data = payload["data"]

    logger.info("processing_profile_update", user_id=user_id, update_type=update_type)

    try:
        profile = UserProfile.objects(username=user_id).first()
        if profile is None:
            logger.warning("profile_update_profile_missing", user_id=user_id)
            return

        if update_type == "preferences":
            profile.genre_preferences = data.get("genre_preferences", profile.genre_preferences)
            profile.artist_preferences = data.get("artist_preferences", profile.artist_preferences)
            profile.era_preferences = data.get("era_preferences", profile.era_preferences)
            profile.mood_preferences = data.get("mood_preferences", profile.mood_preferences)
            profile.interaction_counts = data.get("interaction_counts", profile.interaction_counts)
            profile.exploration_preference = data.get("exploration_preference", profile.exploration_preference)
        elif update_type == "calibration":
            profile.mood_calibration = data.get("mood_calibration", profile.mood_calibration)
        elif update_type == "taste_profile":
            profile.taste_profile = data.get("taste_profile", profile.taste_profile)

        profile.save()
        logger.info("profile_update_processed", user_id=user_id, update_type=update_type)

        # Invalidate cache since profile changed
        _invalidate_user_cache(redis_client, user_id)

    except Exception as e:  # noqa: BLE001
        logger.error("profile_update_failed", user_id=user_id, error=str(e))
        raise


# Event processor mapping
PROCESSORS = {
    EventType.FEEDBACK_TRACK: process_feedback_track,
    EventType.FEEDBACK_MOOD: process_feedback_mood,
    EventType.CACHE_INVALIDATE: process_cache_invalidate,
    EventType.PROFILE_UPDATE: process_profile_update,
}


def process_event(event: Event, redis_client) -> bool:
    """Process a single event with retry logic.

    Returns True if processed successfully, False if should be requeued.
    """
    processor = PROCESSORS.get(event.type)
    if not processor:
        logger.error("unknown_event_type", event_id=event.event_id, type=event.type)
        return False  # Don't retry unknown types

    try:
        processor(event, redis_client)
        return True
    except RetryExhausted:
        logger.error("event_retry_exhausted", event_id=event.event_id, type=event.type.value)
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("event_processing_failed", event_id=event.event_id, type=event.type.value, error=str(e))
        return False


def run_worker() -> None:
    """Main worker loop."""
    logger.info("worker_starting", worker_id=WORKER_ID)

    redis_client = get_redis_client()
    logger.info("redis_connected", worker_id=WORKER_ID)

    processed_count = 0
    failed_count = 0

    while not _shutdown:
        try:
            event = dequeue_event(redis_client, timeout=5)
            if event is None:
                # Queue empty, log stats periodically
                if processed_count > 0 or failed_count > 0:
                    logger.info("worker_stats", processed=processed_count, failed=failed_count,
                               queue_length=get_queue_length(redis_client),
                               dead_letter_length=get_dead_letter_length(redis_client))
                continue

            logger.debug("event_dequeued", event_id=event.event_id, type=event.type.value)

            success = process_event(event, redis_client)

            if success:
                processed_count += 1
            else:
                failed_count += 1
                if event.retry_count < MAX_RETRIES:
                    logger.info("event_requeueing", event_id=event.event_id, retry_count=event.retry_count)
                    requeue_event(redis_client, event)
                else:
                    logger.error("event_max_retries_reached", event_id=event.event_id)
                    move_to_dead_letter(redis_client, event, "max retries exceeded")

        except Exception as e:  # noqa: BLE001
            logger.error("worker_loop_error", error=str(e))
            time.sleep(1)  # Brief pause on unexpected error

    logger.info("worker_shutting_down", worker_id=WORKER_ID, processed=processed_count, failed=failed_count)


if __name__ == "__main__":
    run_worker()