"""User preference profile management for Phase 2 personalization.

This module handles the explicit preference profile (genre, artist, era, mood)
that complements the implicit Thompson Sampling bandit. Preferences are
updated from user feedback (like/unlike) and listening behavior.

Design principles:
- Simple, interpretable weights in [-1, 1]
- Incremental updates from feedback signals
- Decay/forgetting for old preferences
- Cold-start safe: neutral (0) until sufficient evidence
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from . import track_features as tf
from . import genre_inference

logger = logging.getLogger(__name__)

# Preference update parameters
LIKE_BOOST = 0.15       # Weight increase for liked track features
UNLIKE_PENALTY = 0.15   # Weight decrease for disliked track features
LISTEN_BOOST = 0.05     # Weight increase for opened/played tracks
MAX_WEIGHT = 1.0        # Cap for preference weights
MIN_WEIGHT = -1.0       # Floor for preference weights
DECAY_FACTOR = 0.995    # Per-update decay toward neutral (slow)
MIN_INTERACTIONS_FOR_CONFIDENCE = 5  # Minimum signals before trusting preference

# Decade bucket mapping (must match track_features.DECADES)
DECADE_BUCKETS = ("pre1960", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s")

# Emotion labels (must match track_features.EMOTIONS)
EMOTION_LABELS = ("sadness", "joy", "love", "anger", "fear", "neutral")


def _clamp_weight(w: float) -> float:
    """Clamp weight to [-1, 1]."""
    return max(MIN_WEIGHT, min(MAX_WEIGHT, w))


def _decay_preferences(prefs: dict) -> dict:
    """Apply decay toward neutral (0) for all preferences."""
    return {k: v * DECAY_FACTOR for k, v in prefs.items()}


def _extract_genre_from_track(track: dict) -> Optional[str]:
    """Extract genre from track using genre inference.

    Uses artist mapping and title/album keywords to infer genre
    since Deezer doesn't provide genre directly in search results.
    """
    return genre_inference.infer_genre(track)


def _extract_artist_from_track(track: dict) -> Optional[str]:
    """Extract artist name from track."""
    artist = track.get("artist")
    if artist and isinstance(artist, str):
        return artist.strip()
    return None


def _extract_era_from_track(track: dict) -> Optional[str]:
    """Extract decade bucket from track release_date."""
    release = track.get("release_date")
    if not release:
        return None
    import re
    match = re.search(r"(\d{4})", str(release))
    if not match:
        return None
    try:
        year = int(match.group(1))
    except ValueError:
        return None
    if year < 1960:
        return "pre1960"
    if year < 1970:
        return "1960s"
    if year < 1980:
        return "1970s"
    if year < 1990:
        return "1980s"
    if year < 2000:
        return "1990s"
    if year < 2010:
        return "2000s"
    return "2010s"


def _extract_mood_from_context(context_emotion: Optional[str]) -> Optional[str]:
    """Normalize context emotion to canonical label."""
    if not context_emotion:
        return None
    e = context_emotion.strip().lower()
    return e if e in EMOTION_LABELS else None


def update_preferences_from_feedback(
    profile: dict,
    track: dict,
    signal: str,
    context_emotion: Optional[str] = None,
) -> dict:
    """Update user preference profile from a track feedback signal.

    Args:
        profile: UserProfile dict (or None for new user)
        track: Full track dict from recommendation
        signal: One of "like", "unlike", "open_deezer", "clear"
        context_emotion: Emotion that produced this recommendation

    Returns:
        Updated profile dict with modified preferences
    """
    # Initialize profile structure if needed
    prefs = {
        "genre_preferences": dict(profile.get("genre_preferences", {})),
        "artist_preferences": dict(profile.get("artist_preferences", {})),
        "era_preferences": dict(profile.get("era_preferences", {})),
        "mood_preferences": dict(profile.get("mood_preferences", {})),
        "interaction_counts": dict(profile.get("interaction_counts", {})),
        "exploration_preference": profile.get("exploration_preference", 0.3),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "profile_version": 2,
    }

    # Extract track attributes
    artist = _extract_artist_from_track(track)
    era = _extract_era_from_track(track)
    mood = _extract_mood_from_context(context_emotion)
    # genre = _extract_genre_from_track(track)  # Not available from Deezer

    # Determine weight delta based on signal
    if signal == "like":
        delta = LIKE_BOOST
    elif signal == "unlike":
        delta = -UNLIKE_PENALTY
    elif signal == "open_deezer":
        delta = LISTEN_BOOST
    elif signal == "clear":
        # Clear reverts the previous vote - handled at feedback endpoint
        # by calling with opposite signal. Here we just count the interaction.
        delta = 0
    else:
        delta = 0

    if delta == 0:
        return prefs

    # Apply decay to all existing preferences (slow forgetting)
    for key in ("genre_preferences", "artist_preferences", "era_preferences", "mood_preferences"):
        prefs[key] = _decay_preferences(prefs[key])

    # Update artist preference
    if artist:
        current = prefs["artist_preferences"].get(artist, 0.0)
        prefs["artist_preferences"][artist] = _clamp_weight(current + delta)

    # Update era preference
    if era:
        current = prefs["era_preferences"].get(era, 0.0)
        prefs["era_preferences"][era] = _clamp_weight(current + delta)

    # Update mood preference
    if mood:
        current = prefs["mood_preferences"].get(mood, 0.0)
        prefs["mood_preferences"][mood] = _clamp_weight(current + delta)

    # Increment interaction count
    prefs["interaction_counts"][signal] = prefs["interaction_counts"].get(signal, 0) + 1

    # Adjust exploration preference based on interaction history
    total_interactions = sum(prefs["interaction_counts"].values())
    if total_interactions > 20:
        prefs["exploration_preference"] = max(0.1, 0.3 * (20 / total_interactions))

    return prefs


def update_preferences_from_listening(
    profile: dict,
    track: dict,
) -> dict:
    """Update preferences from passive listening (track opened/played).

    Weaker signal than explicit like/unlike.
    """
    prefs = {
        "genre_preferences": dict(profile.get("genre_preferences", {})),
        "artist_preferences": dict(profile.get("artist_preferences", {})),
        "era_preferences": dict(profile.get("era_preferences", {})),
        "mood_preferences": dict(profile.get("mood_preferences", {})),
        "interaction_counts": dict(profile.get("interaction_counts", {})),
        "exploration_preference": profile.get("exploration_preference", 0.3),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "profile_version": 2,
    }

    artist = _extract_artist_from_track(track)
    era = _extract_era_from_track(track)

    if artist:
        current = prefs["artist_preferences"].get(artist, 0.0)
        prefs["artist_preferences"][artist] = _clamp_weight(current + LISTEN_BOOST)

    if era:
        current = prefs["era_preferences"].get(era, 0.0)
        prefs["era_preferences"][era] = _clamp_weight(current + LISTEN_BOOST)

    prefs["interaction_counts"]["listen"] = prefs["interaction_counts"].get("listen", 0) + 1

    return prefs


def compute_personalization_score(
    track: dict,
    prefs: dict,
    context_emotion: Optional[str] = None,
) -> float:
    """Compute personalization score boost for a track based on user preferences.

    Returns a score in [-1, 1] that can be added to base ranking score.
    """
    score = 0.0
    factors = 0

    artist = _extract_artist_from_track(track)
    era = _extract_era_from_track(track)
    mood = _extract_mood_from_context(context_emotion)

    if artist and artist in prefs.get("artist_preferences", {}):
        score += prefs["artist_preferences"][artist]
        factors += 1

    if era and era in prefs.get("era_preferences", {}):
        score += prefs["era_preferences"][era]
        factors += 1

    if mood and mood in prefs.get("mood_preferences", {}):
        score += prefs["mood_preferences"][mood]
        factors += 1

    # Average across available factors
    if factors > 0:
        return score / factors
    return 0.0


def get_preference_summary(profile: dict) -> dict:
    """Get human-readable summary of user preferences for dashboard."""
    def top_prefs(prefs: dict, n: int = 3) -> list[dict]:
        items = [(k, v) for k, v in prefs.items() if v > 0.1]
        items.sort(key=lambda x: x[1], reverse=True)
        return [{"name": k, "weight": round(v, 2)} for k, v in items[:n]]

    def bottom_prefs(prefs: dict, n: int = 3) -> list[dict]:
        items = [(k, v) for k, v in prefs.items() if v < -0.1]
        items.sort(key=lambda x: x[1])
        return [{"name": k, "weight": round(v, 2)} for k, v in items[:n]]

    return {
        "favorite_genres": top_prefs(profile.get("genre_preferences", {})),
        "disliked_genres": bottom_prefs(profile.get("genre_preferences", {})),
        "favorite_artists": top_prefs(profile.get("artist_preferences", {})),
        "disliked_artists": bottom_prefs(profile.get("artist_preferences", {})),
        "favorite_eras": top_prefs(profile.get("era_preferences", {})),
        "disliked_eras": bottom_prefs(profile.get("era_preferences", {})),
        "favorite_moods": top_prefs(profile.get("mood_preferences", {})),
        "exploration_level": round(profile.get("exploration_preference", 0.3), 2),
        "total_interactions": sum(profile.get("interaction_counts", {}).values()),
    }


def has_sufficient_interactions(profile: dict, min_interactions: int = MIN_INTERACTIONS_FOR_CONFIDENCE) -> bool:
    """Check if user has enough interactions for reliable personalization."""
    total = sum(profile.get("interaction_counts", {}).values())
    return total >= min_interactions


__all__ = [
    "update_preferences_from_feedback",
    "update_preferences_from_listening",
    "compute_personalization_score",
    "get_preference_summary",
    "has_sufficient_interactions",
    "LIKE_BOOST",
    "UNLIKE_PENALTY",
    "LISTEN_BOOST",
    "MAX_WEIGHT",
    "MIN_WEIGHT",
    "DECAY_FACTOR",
]