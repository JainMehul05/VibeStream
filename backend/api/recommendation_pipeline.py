"""Recommendation pipeline orchestrator.

Coordinates the multi-stage recommendation pipeline:
  Candidate Generation → Base Ranking → Mood/Context → Personalization
  → Thompson Sampling → Diversity → Explanation → Final Recommendations

Each stage is a pure function with clear input/output for testability.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

from . import bandit, calibration, candidate_generation, base_ranking, preference_profile
from .models import UserProfile

logger = logging.getLogger(__name__)

# Pipeline configuration (can be overridden via Django settings)
DEFAULT_CANDIDATE_LIMIT = 60
DEFAULT_FINAL_LIMIT = 20
DEFAULT_DIVERSITY_WEIGHT = 0.3
DEFAULT_DIVERSITY_DIMENSIONS = ("artist", "genre", "era")


class PipelineError(Exception):
    """Raised when pipeline fails unrecoverably."""


def run_pipeline(
    emotion: str,
    user_profile: Optional[UserProfile] = None,
    history: Optional[list[str]] = None,
    genre: Optional[str] = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    final_limit: int = DEFAULT_FINAL_LIMIT,
    diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
    diversity_dimensions: tuple[str, ...] = DEFAULT_DIVERSITY_DIMENSIONS,
    rng: Optional[random.Random] = None,
) -> dict:
    """Run the full recommendation pipeline.

    Args:
        emotion: Current emotion (from detection or user selection)
        user_profile: Authenticated user's UserProfile (None for anonymous)
        history: Recent mood history for recurring-mood blending
        genre: Optional genre filter/bias
        candidate_limit: Max candidates to generate
        final_limit: Max tracks in final response
        diversity_weight: Diversity strength (0.0 = no diversity, 1.0 = max)
        diversity_dimensions: Dimensions to diversify across
        rng: Random number generator for deterministic testing

    Returns:
        Dict with keys:
          - emotion: Final emotion (post-calibration)
          - calibrated_from: Original emotion if calibrated, else None
          - recommendations: List of track dicts with explanations
          - degraded: Whether fallback was used
    """
    rng = rng or random.Random()

    # Stage 1: Candidate Generation
    try:
        candidates = candidate_generation.generate_candidates(
            emotion=emotion,
            history=history,
            genre=genre,
            limit=candidate_limit,
        )
    except candidate_generation.CandidateGenerationError:
        logger.warning("Primary candidate generation failed, using fallback")
        candidates = candidate_generation.generate_fallback_candidates(limit=candidate_limit)
        degraded = True
    else:
        degraded = False

    if not candidates:
        candidates = candidate_generation.generate_fallback_candidates(limit=candidate_limit)
        degraded = True

    # Stage 2: Base Ranking
    context = {"genre": genre} if genre else None
    ranked = base_ranking.rank_candidates(candidates, emotion, context)

    # Stage 3: Mood/Context Scoring
    # (Modal already handles mood match + history blend; we preserve order)
    # This stage is a placeholder for future context signals
    mood_scored = _apply_mood_context(ranked, emotion, history)

    # Stage 4: Personalization (explicit preferences)
    if user_profile:
        personalized = _apply_personalization(mood_scored, user_profile, emotion)
    else:
        personalized = mood_scored

    # Stage 5: Thompson Sampling (existing bandit)
    taste_profile = user_profile.taste_profile if user_profile else {}
    context_emotion = emotion  # Will be updated after calibration
    try:
        bandit_reranked = bandit.rerank(
            personalized,
            taste_profile=taste_profile or {},
            context_emotion=context_emotion,
            rng=rng,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "bandit rerank failed for user=%s -- returning base order",
            user_profile.username if user_profile else "anonymous",
        )
        bandit_reranked = personalized

    # Stage 6: Diversity Re-ranking
    diversified = _apply_diversity(
        bandit_reranked,
        k=final_limit,
        diversity_weight=diversity_weight,
        dimensions=diversity_dimensions,
    )

    # Stage 7: Explanation Generation
    explained = _generate_explanations(diversified, emotion, user_profile)

    # Stage 8: Final truncation
    final_tracks = explained[:final_limit]

    # Determine final emotion (after calibration)
    final_emotion = emotion
    calibrated_from = None
    if user_profile and user_profile.mood_calibration:
        calibrated = calibration.apply_calibration(emotion, user_profile.mood_calibration)
        if calibrated != emotion:
            final_emotion = calibrated
            calibrated_from = emotion

    return {
        "emotion": final_emotion,
        "calibrated_from": calibrated_from,
        "recommendations": final_tracks,
        "degraded": degraded,
    }


def _apply_mood_context(
    tracks: list[dict],
    emotion: str,
    history: Optional[list[str]],
) -> list[dict]:
    """Apply mood/context scoring.

    Currently a pass-through since Modal already handles:
    - Primary emotion match (via search query)
    - Recurring mood blend (via EWMA + Markov + interleave)

    This stage exists for future extension (e.g., time-of-day, weather).
    """
    # Add mood_context signal for explanations
    for track in tracks:
        signals = track.get("ranking_signals", {})
        signals["mood_context"] = {
            "primary_emotion": emotion,
            "has_history": bool(history),
        }
        track["ranking_signals"] = signals
    return tracks


def _apply_personalization(
    tracks: list[dict],
    user_profile: UserProfile,
    emotion: str,
) -> list[dict]:
    """Apply explicit user preferences (Phase 2B).

    Reads from UserProfile's preference fields:
      - genre_preferences
      - artist_preferences
      - era_preferences
      - mood_preferences

    Boosts tracks matching preferences, penalizes mismatches.
    Cold-start safe: no boost if insufficient interactions.
    """
    # Extract preference dict from user profile
    prefs = {
        "genre_preferences": dict(getattr(user_profile, "genre_preferences", {})),
        "artist_preferences": dict(getattr(user_profile, "artist_preferences", {})),
        "era_preferences": dict(getattr(user_profile, "era_preferences", {})),
        "mood_preferences": dict(getattr(user_profile, "mood_preferences", {})),
        "interaction_counts": dict(getattr(user_profile, "interaction_counts", {})),
    }

    # Cold-start check: if insufficient interactions, skip personalization
    if not preference_profile.has_sufficient_interactions(prefs):
        for track in tracks:
            signals = track.get("ranking_signals", {})
            signals["personalization"] = {
                "applied": False,
                "reason": "Insufficient interactions for personalization",
            }
            track["ranking_signals"] = signals
        return tracks

    # Apply personalization score to each track
    for track in tracks:
        signals = track.get("ranking_signals", {})
        pers_score = preference_profile.compute_personalization_score(track, prefs, emotion)
        
        # Add personalization signal for explanation
        signals["personalization"] = {
            "applied": True,
            "score": round(pers_score, 3),
            "artist_match": _extract_artist_from_track(track) in prefs.get("artist_preferences", {}),
            "era_match": _extract_era_from_track(track) in prefs.get("era_preferences", {}),
            "mood_match": _extract_mood_from_context(emotion) in prefs.get("mood_preferences", {}),
        }
        track["ranking_signals"] = signals
        
        # Boost base_score with personalization (weight: 0.3)
        base_score = track.get("base_score", 0.5)
        track["base_score"] = min(1.0, max(0.0, base_score + 0.3 * pers_score))

    # Re-sort by updated base_score
    tracks.sort(key=lambda t: t.get("base_score", 0.5), reverse=True)
    return tracks


def _extract_artist_from_track(track: dict) -> Optional[str]:
    artist = track.get("artist")
    if artist and isinstance(artist, str):
        return artist.strip()
    return None


def _extract_era_from_track(track: dict) -> Optional[str]:
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
    if not context_emotion:
        return None
    e = context_emotion.strip().lower()
    return e if e in ("sadness", "joy", "love", "anger", "fear", "neutral") else None


def _apply_diversity(
    tracks: list[dict],
    k: int,
    diversity_weight: float,
    dimensions: tuple[str, ...],
) -> list[dict]:
    """Apply diversity re-ranking using MMR (Maximal Marginal Relevance).

    Balances relevance (base_score) with diversity across specified dimensions.

    Args:
        tracks: Ranked tracks with base_score
        k: Number of tracks to return
        diversity_weight: λ in [0, 1] — 0 = pure relevance, 1 = pure diversity
        dimensions: Diversity dimensions ("artist", "genre", "era")

    Returns:
        Re-ranked list of length min(k, len(tracks))
    """
    if not tracks or k >= len(tracks) or diversity_weight <= 0:
        return tracks[:k]

    # Extract diversity attributes
    def get_attrs(track: dict) -> dict[str, str]:
        attrs = {}
        attrs["artist"] = (track.get("artist") or "").strip().lower()
        # Genre not in track — would need external lookup
        attrs["genre"] = ""
        # Era from release_date
        release = track.get("release_date")
        if release:
            import re
            match = re.search(r"(\d{4})", str(release))
            if match:
                year = int(match.group(1))
                if year < 1960:
                    attrs["era"] = "pre1960"
                elif year < 1970:
                    attrs["era"] = "1960s"
                elif year < 1980:
                    attrs["era"] = "1970s"
                elif year < 1990:
                    attrs["era"] = "1980s"
                elif year < 2000:
                    attrs["era"] = "1990s"
                elif year < 2010:
                    attrs["era"] = "2000s"
                else:
                    attrs["era"] = "2010s"
            else:
                attrs["era"] = "unknown"
        else:
            attrs["era"] = "unknown"
        return attrs

    track_attrs = [get_attrs(t) for t in tracks]
    scores = [base_ranking.get_base_score(t) for t in tracks]

    selected = []
    remaining = list(range(len(tracks)))

    # Pick first item (highest relevance)
    if remaining:
        selected.append(remaining.pop(0))

    # MMR selection
    while remaining and len(selected) < k:
        best_idx = None
        best_mmr = -1.0

        for idx in remaining:
            relevance = scores[idx]
            # Compute max similarity to already selected
            max_sim = 0.0
            for sel_idx in selected:
                sim = _compute_similarity(track_attrs[idx], track_attrs[sel_idx], dimensions)
                max_sim = max(max_sim, sim)

            mmr = (1 - diversity_weight) * relevance - diversity_weight * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx is not None:
            selected.append(best_idx)
            remaining.remove(best_idx)

    return [tracks[i] for i in selected]


def _compute_similarity(attrs1: dict, attrs2: dict, dimensions: tuple[str, ...]) -> float:
    """Compute similarity between two tracks across diversity dimensions."""
    matches = 0
    total = 0
    for dim in dimensions:
        v1 = attrs1.get(dim, "")
        v2 = attrs2.get(dim, "")
        if v1 and v2:
            total += 1
            if v1 == v2:
                matches += 1
    return matches / total if total > 0 else 0.0


def _generate_explanations(
    tracks: list[dict],
    emotion: str,
    user_profile: Optional[UserProfile],
) -> list[dict]:
    """Generate human-readable explanations for each recommendation.

    Uses ranking_signals from each track to produce truthful explanations.
    No hallucination — only signals that actually contributed.
    """
    for track in tracks:
        signals = track.get("ranking_signals", {})
        explanation = _build_explanation(signals, emotion, user_profile)
        track["explanation"] = explanation
    return tracks


def _build_explanation(
    signals: dict,
    emotion: str,
    user_profile: Optional[UserProfile],
) -> str:
    """Build explanation string from ranking signals."""
    parts = []

    # Mood match
    if signals.get("mood_match"):
        parts.append(f"Matches your {emotion} mood")

    # Personalization (Phase 2B)
    if signals.get("personalization", {}).get("applied"):
        pers = signals["personalization"]
        if pers.get("genre_match"):
            parts.append(f"You like {pers['genre_match']}")
        if pers.get("artist_match"):
            parts.append(f"You like {pers['artist_match']}")
        if pers.get("era_match"):
            parts.append(f"You like {pers['era_match']} music")

    # Bandit (exploration/exploitation)
    if signals.get("bandit"):
        bandit_sig = signals["bandit"]
        if bandit_sig.get("exploration"):
            parts.append("Exploration pick based on your preferences")
        elif bandit_sig.get("exploitation"):
            parts.append("Recommended based on your listening history")

    # Diversity
    if signals.get("diversity"):
        div = signals["diversity"]
        if div.get("artist_diversity"):
            parts.append("Adding artist variety")

    # Popularity/quality
    base = signals.get("base_score", 0)
    if base > 0.7:
        parts.append("Popular track in this mood")

    if not parts:
        return "Recommended for you"

    return ". ".join(parts) + "."


__all__ = [
    "run_pipeline",
    "PipelineError",
]