"""Base ranking for the recommendation pipeline.

Provides a deterministic, explainable baseline ranking before personalization,
bandit, and diversity layers. Reuses Modal's existing quality ranking logic.

The base rank combines:
  1. Modal's curated order (already applied by Modal's quality rank)
  2. Popularity blend (already applied by Modal)
  3. Mood similarity (implicit in Modal's search query)

Since Modal already returns a quality-ranked list, this module primarily
provides:
  - Score normalization to [0, 1] for downstream combination
  - Explicit signal extraction for explanations
  - Extension point for additional base signals
"""

from __future__ import annotations

from typing import Optional


def rank_candidates(
    candidates: list[dict],
    emotion: str,
    context: Optional[dict] = None,
) -> list[dict]:
    """Apply base ranking to candidate tracks.

    Modal already returns candidates ranked by its quality algorithm
    (curated order + popularity blend). This function:
    1. Preserves Modal's order as the primary signal
    2. Adds normalized base_score ∈ [0, 1] for downstream combination
    3. Extracts ranking signals for explanation generation

    Args:
        candidates: Track dicts from candidate generation (already ranked by Modal)
        emotion: Current emotion context
        context: Optional additional context (genre, history, etc.)

    Returns:
        List of tracks with added 'base_score' and 'ranking_signals' fields.
        Order preserved from Modal's quality ranking.
    """
    if not candidates:
        return []

    n = len(candidates)
    ranked = []

    for idx, track in enumerate(candidates):
        # Curated component: 1.0 at top, 0.0 at bottom (Modal's implicit ranking)
        # Modal already applied popularity blend in rank_by_quality, so we use
        # pure position-based score for downstream combination.
        curated_score = 1.0 - (idx / max(1, n - 1)) if n > 1 else 1.0

        # Popularity component (normalized to [0, 1]) - for explanation only
        try:
            pop = float(track.get("popularity") or 0)
        except (TypeError, ValueError):
            pop = 0.0
        pop_norm = max(0.0, min(1.0, pop / 100.0))

        # Base score uses only curated rank since Modal already blended popularity
        base_score = curated_score

        # Extract signals for explanation
        signals = {
            "curated_rank": idx + 1,
            "curated_score": round(curated_score, 3),
            "popularity": pop,
            "popularity_normalized": round(pop_norm, 3),
            "base_score": round(base_score, 3),
        }

        # Add mood match signal (implicit — Modal searched for this emotion)
        signals["mood_match"] = True
        signals["mood"] = emotion

        # Add genre signal if context provided
        if context and context.get("genre"):
            signals["genre_bias"] = context["genre"]

        # Create enriched track dict (shallow copy to avoid mutating original)
        enriched = dict(track)
        enriched["base_score"] = base_score
        enriched["ranking_signals"] = signals
        ranked.append(enriched)

    return ranked


def get_base_score(track: dict) -> float:
    """Extract base_score from enriched track, defaulting to 0.5."""
    return float(track.get("base_score", 0.5))


def get_ranking_signals(track: dict) -> dict:
    """Extract ranking_signals from enriched track, defaulting to empty dict."""
    return track.get("ranking_signals", {})


__all__ = [
    "rank_candidates",
    "get_base_score",
    "get_ranking_signals",
]