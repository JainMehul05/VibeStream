"""Candidate generation for the recommendation pipeline.

This module separates "which tracks are eligible" from "which tracks rank highest".
It wraps the existing Modal recommendation service output as the primary candidate
source, and provides extension points for additional candidate sources.

Phase 2: Reuses Modal's existing candidate generation (Deezer search + history blend)
rather than duplicating it. The Modal service already does:
  - Emotion → Deezer keyword search
  - History → EWMA + Markov → recurring mood blend
  - Quality ranking + interleaving
  - Curated fallback on failure

This module provides a clean interface for the pipeline to consume Modal's output
and add additional candidate sources in the future.
"""

from __future__ import annotations

import logging
from typing import Optional

from integrations.clients import InferenceServiceError, music_recommendation as modal_music

logger = logging.getLogger(__name__)

# Default candidate pool size from Modal
_DEFAULT_CANDIDATE_LIMIT = 60


class CandidateGenerationError(Exception):
    """Raised when candidate generation fails completely."""


def generate_candidates(
    emotion: str,
    history: Optional[list[str]] = None,
    genre: Optional[str] = None,
    limit: int = _DEFAULT_CANDIDATE_LIMIT,
) -> list[dict]:
    """Generate candidate tracks for the given emotion and context.

    This is the primary candidate source — it calls the Modal inference service
    which performs Deezer search, history blending, quality ranking, and
    interleaving. The returned list is already ranked by Modal's base algorithm.

    Args:
        emotion: The detected/current emotion (e.g., "joy", "sadness")
        history: Optional list of recent moods for recurring-mood blending
        genre: Optional genre keyword to bias the search
        limit: Maximum number of candidates to return

    Returns:
        List of track dicts with keys: name, artist, album, preview_url,
        external_url, image_url, popularity, duration_ms, release_date

    Raises:
        CandidateGenerationError: If Modal service is unavailable
    """
    if not emotion:
        raise ValueError("emotion is required")

    # Normalize history
    history = [str(m).strip().lower() for m in (history or []) if m][-50:]
    genre = (genre or "").strip().lower() or None

    try:
        # Modal returns {emotion, recommendations[], degraded, market}
        result = modal_music(emotion, market=None, history=history, genre=genre)
    except InferenceServiceError as exc:
        logger.exception("Modal candidate generation failed for emotion=%s", emotion)
        raise CandidateGenerationError("Inference service unavailable") from exc

    if not isinstance(result, dict):
        raise CandidateGenerationError("Invalid response from inference service")

    candidates = result.get("recommendations") or []
    if not candidates:
        logger.warning("Modal returned empty candidate list for emotion=%s", emotion)
        return []

    # Deduplicate by stable track identifier (Deezer ID from external_url)
    seen = set()
    deduped = []
    for track in candidates:
        track_id = _extract_track_id(track)
        if track_id and track_id not in seen:
            seen.add(track_id)
            deduped.append(track)
        elif not track_id:
            # No stable ID — include but log
            deduped.append(track)

    return deduped[:limit]


def _extract_track_id(track: dict) -> Optional[str]:
    """Extract stable Deezer track ID from track dict."""
    url = track.get("external_url") or track.get("url") or ""
    if not url:
        return None
    # Deezer URLs contain /track/{id}
    import re
    match = re.search(r"/track/(\d+)", str(url))
    if match:
        return f"deezer:{match.group(1)}"
    # Fallback: name::artist
    name = (track.get("name") or "").strip()
    artist = (track.get("artist") or "").strip()
    if name:
        return f"name:{name}::{artist}"
    return None


def generate_exploration_candidates(
    emotion: str,
    limit: int = 10,
) -> list[dict]:
    """Generate exploration candidates for diversity/injection.

    Currently returns an empty list — placeholder for future exploration
    strategies (popular tracks, trending, cross-genre, etc.).

    Args:
        emotion: Current emotion context
        limit: Maximum exploration candidates

    Returns:
        List of track dicts (empty for now)
    """
    # TODO: Implement exploration strategies:
    # - Popular tracks across all moods
    # - Trending tracks from Deezer charts
    # - Cross-genre "discovery" picks
    # - Serendipity injection
    return []


def generate_fallback_candidates(limit: int = 20) -> list[dict]:
    """Generate curated fallback candidates when all else fails.

    Mirrors Modal's _FALLBACK_TRACKS for consistency.
    """
    import random
    import urllib.parse

    _FALLBACK_TRACKS = [
        {"name": "Blinding Lights", "artist": "The Weeknd"},
        {"name": "Levitating", "artist": "Dua Lipa"},
        {"name": "As It Was", "artist": "Harry Styles"},
        {"name": "good 4 u", "artist": "Olivia Rodrigo"},
        {"name": "Sunflower", "artist": "Post Malone, Swae Lee"},
        {"name": "Uptown Funk", "artist": "Mark Ronson, Bruno Mars"},
        {"name": "Someone Like You", "artist": "Adele"},
        {"name": "Counting Stars", "artist": "OneRepublic"},
        {"name": "Stay", "artist": "The Kid LAROI, Justin Bieber"},
        {"name": "Shape of You", "artist": "Ed Sheeran"},
        {"name": "Believer", "artist": "Imagine Dragons"},
        {"name": "Riptide", "artist": "Vance Joy"},
        {"name": "Heat Waves", "artist": "Glass Animals"},
        {"name": "Don't Start Now", "artist": "Dua Lipa"},
    ]

    tracks = list(_FALLBACK_TRACKS)
    random.shuffle(tracks)
    return [
        {
            "name": track["name"],
            "artist": track["artist"],
            "album": None,
            "preview_url": None,
            "external_url": "https://www.deezer.com/search/"
            + urllib.parse.quote(f"{track['name']} {track['artist']}"),
            "image_url": None,
            "popularity": 0,
            "duration_ms": 0,
            "release_date": None,
        }
        for track in tracks[:limit]
    ]


__all__ = [
    "generate_candidates",
    "generate_exploration_candidates",
    "generate_fallback_candidates",
    "CandidateGenerationError",
]