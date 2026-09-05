"""Shared feedback processing logic for events and worker.

This module contains the core business logic for processing feedback events,
extracted from events.py and worker.py to eliminate duplication.
"""

import logging
from typing import Optional

import structlog

from . import bandit, feedback_store, track_features
from . import preference_profile
from .models import UserProfile

logger = structlog.get_logger(__name__)


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

        updated = preference_profile.update_preferences_from_feedback(
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


__all__ = [
    "_bump_calibration",
    "_featurize",
    "_apply_posterior",
    "_revert_posterior",
    "_update_preferences",
    "_invalidate_user_cache",
]