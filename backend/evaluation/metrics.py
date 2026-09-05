"""Recommendation quality metrics for offline evaluation.

Implements standard IR/recsys metrics: NDCG@K, Hit Rate@K, Precision@K, MRR,
plus diversity and repetition metrics specific to music recommendation.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable


def ndcg_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K.

    Args:
        recommended: Ordered list of recommended item IDs (top-1 first)
        relevant: Set of relevant/ground-truth item IDs
        k: Cutoff rank

    Returns:
        NDCG@K in [0, 1]. 1.0 = perfect ranking of all relevant items at top.
    """
    if not relevant or k <= 0:
        return 0.0

    # DCG: sum over recommended items of relevance / log2(rank + 1)
    dcg = 0.0
    for i, item_id in enumerate(recommended[:k]):
        if item_id in relevant:
            rank = i + 1
            dcg += 1.0 / math.log2(rank + 1)

    # IDCG: ideal DCG (all relevant items at top)
    n_relevant = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_relevant))

    return dcg / idcg if idcg > 0 else 0.0


def hit_rate_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Hit Rate at K — fraction of users with at least one relevant item in top-K.

    Args:
        recommended: Ordered list of recommended item IDs
        relevant: Set of relevant item IDs
        k: Cutoff rank

    Returns:
        1.0 if any relevant item in top-K, else 0.0
    """
    if not relevant or k <= 0:
        return 0.0
    return 1.0 if any(item in relevant for item in recommended[:k]) else 0.0


def precision_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Precision at K — fraction of top-K recommendations that are relevant.

    Args:
        recommended: Ordered list of recommended item IDs
        relevant: Set of relevant item IDs
        k: Cutoff rank

    Returns:
        Precision@K in [0, 1]
    """
    if k <= 0:
        return 0.0
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(top_k)


def mean_reciprocal_rank(recommended: list[str], relevant: set[str]) -> float:
    """Mean Reciprocal Rank — reciprocal of rank of first relevant item.

    Args:
        recommended: Ordered list of recommended item IDs
        relevant: Set of relevant item IDs

    Returns:
        MRR in [0, 1]. 1.0 if first item is relevant, 0 if no relevant items.
    """
    if not relevant:
        return 0.0
    for i, item_id in enumerate(recommended):
        if item_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def _get_track_attr(track, attr: str, default=""):
    """Get attribute from track (dict or object)."""
    if hasattr(track, "get"):
        return track.get(attr, default)
    return getattr(track, attr, default)


def artist_repetition_rate(recommended: list, k: int) -> float:
    """Artist repetition rate in top-K recommendations.

    Args:
        recommended: List of track dicts or objects with 'artist' field
        k: Cutoff rank

    Returns:
        Fraction of top-K slots that share artist with a previous slot.
        0.0 = all unique artists, 1.0 = all same artist.
    """
    if k <= 1:
        return 0.0
    top_k = recommended[:k]
    artists = [_get_track_attr(track, "artist", "").strip().lower() for track in top_k if _get_track_attr(track, "artist")]
    if len(artists) <= 1:
        return 0.0
    seen = set()
    repetitions = 0
    for artist in artists:
        if artist in seen:
            repetitions += 1
        else:
            seen.add(artist)
    return repetitions / (len(artists) - 1)  # Normalize by max possible repetitions


def unique_artists_at_k(recommended: list, k: int) -> int:
    """Count of unique artists in top-K recommendations."""
    top_k = recommended[:k]
    artists = {_get_track_attr(track, "artist", "").strip().lower() for track in top_k if _get_track_attr(track, "artist")}
    return len(artists)


def genre_entropy(recommended: list, k: int) -> float:
    """Shannon entropy of genre distribution in top-K.

    Higher = more diverse. Requires 'genre' field in track dicts.
    """
    top_k = recommended[:k]
    genres = [_get_track_attr(track, "genre", "").strip().lower() for track in top_k if _get_track_attr(track, "genre")]
    if not genres:
        return 0.0
    counts = Counter(genres)
    total = len(genres)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return entropy


def era_entropy(recommended: list, k: int) -> float:
    """Shannon entropy of era/decade distribution in top-K.

    Extracts decade from release_date field.
    """
    import re
    top_k = recommended[:k]
    eras = []
    for track in top_k:
        release = _get_track_attr(track, "release_date")
        if release:
            match = re.search(r"(\d{4})", str(release))
            if match:
                year = int(match.group(1))
                if year < 1960:
                    eras.append("pre1960")
                elif year < 1970:
                    eras.append("1960s")
                elif year < 1980:
                    eras.append("1970s")
                elif year < 1990:
                    eras.append("1980s")
                elif year < 2000:
                    eras.append("1990s")
                elif year < 2010:
                    eras.append("2000s")
                else:
                    eras.append("2010s")
    if not eras:
        return 0.0
    counts = Counter(eras)
    total = len(eras)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def diversity_metrics(recommended: list[dict], k: int = 10) -> dict:
    """Compute all diversity metrics for a recommendation list.

    Returns dict with:
        - unique_artists: count
        - artist_repetition_rate: float [0,1]
        - genre_entropy: float
        - era_entropy: float
    """
    return {
        "unique_artists": unique_artists_at_k(recommended, k),
        "artist_repetition_rate": artist_repetition_rate(recommended, k),
        "genre_entropy": genre_entropy(recommended, k),
        "era_entropy": era_entropy(recommended, k),
    }


def average_precision_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Average Precision at K (for single user)."""
    if not relevant or k <= 0:
        return 0.0
    score = 0.0
    hits = 0
    for i, item_id in enumerate(recommended[:k]):
        if item_id in relevant:
            hits += 1
            score += hits / (i + 1)
    return score / min(len(relevant), k) if hits > 0 else 0.0


def reciprocal_rank_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    """Reciprocal Rank at K (0 if first relevant > k)."""
    for i, item_id in enumerate(recommended[:k]):
        if item_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def coverage(recommended_all_users: list[list[str]], catalog: set[str]) -> float:
    """Catalog coverage — fraction of catalog appearing in any recommendation."""
    if not catalog:
        return 0.0
    recommended_union = set()
    for recs in recommended_all_users:
        recommended_union.update(recs)
    return len(recommended_union) / len(catalog)


def personalization_index(recommended_all_users: list[list[str]]) -> float:
    """Personalization index — 1 - mean Jaccard similarity between users' recs.

    Higher = more personalized (different users get different recommendations).
    """
    if len(recommended_all_users) < 2:
        return 1.0
    total_sim = 0.0
    pairs = 0
    for i in range(len(recommended_all_users)):
        for j in range(i + 1, len(recommended_all_users)):
            set_i = set(recommended_all_users[i])
            set_j = set(recommended_all_users[j])
            if not set_i and not set_j:
                sim = 1.0
            elif not set_i or not set_j:
                sim = 0.0
            else:
                sim = len(set_i & set_j) / len(set_i | set_j)
            total_sim += sim
            pairs += 1
    return 1.0 - (total_sim / pairs) if pairs > 0 else 1.0


__all__ = [
    "ndcg_at_k",
    "hit_rate_at_k",
    "precision_at_k",
    "mean_reciprocal_rank",
    "average_precision_at_k",
    "reciprocal_rank_at_k",
    "coverage",
    "personalization_index",
    "diversity_metrics",
    "artist_repetition_rate",
    "unique_artists_at_k",
    "genre_entropy",
    "era_entropy",
]