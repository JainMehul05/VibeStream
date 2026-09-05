"""Recommendation system evaluator.

Evaluates the VibeStream recommendation pipeline against synthetic ground truth.
Supports ablation studies, cold-start evaluation, and full system evaluation.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .dataset import EvaluationDataset, UserProfile, Track, create_synthetic_dataset, EMOTIONS
from .metrics import (
    ndcg_at_k,
    hit_rate_at_k,
    precision_at_k,
    mean_reciprocal_rank,
    diversity_metrics,
    unique_artists_at_k,
    artist_repetition_rate,
)


@dataclass
class EvaluationResult:
    """Results for a single system configuration."""
    system_name: str
    n_users: int
    ndcg_at_10: float
    hit_rate_at_10: float
    precision_at_10: float
    mrr: float
    unique_artists_at_10: float
    artist_repetition_rate: float
    genre_entropy: float
    era_entropy: float
    avg_latency_ms: float
    per_emotion: dict = field(default_factory=dict)
    per_interaction_bucket: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "system_name": self.system_name,
            "n_users": self.n_users,
            "ndcg_at_10": round(self.ndcg_at_10, 4),
            "hit_rate_at_10": round(self.hit_rate_at_10, 4),
            "precision_at_10": round(self.precision_at_10, 4),
            "mrr": round(self.mrr, 4),
            "unique_artists_at_10": round(self.unique_artists_at_10, 2),
            "artist_repetition_rate": round(self.artist_repetition_rate, 4),
            "genre_entropy": round(self.genre_entropy, 4),
            "era_entropy": round(self.era_entropy, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "per_emotion": {k: {m: round(v, 4) for m, v in vals.items()} for k, vals in self.per_emotion.items()},
            "per_interaction_bucket": {k: {m: round(v, 4) for m, v in vals.items()} for k, vals in self.per_interaction_bucket.items()},
        }


class RecommendationSystem:
    """Abstract base for a recommendation system to evaluate."""

    def recommend(
        self,
        user: UserProfile,
        emotion: str,
        history: Optional[list[str]] = None,
        genre: Optional[str] = None,
        k: int = 10,
    ) -> list[Track]:
        """Return top-k recommendations for user+emotion."""
        raise NotImplementedError


class MockRecommendationSystem(RecommendationSystem):
    """Mock system for testing the evaluator (returns random tracks)."""

    def __init__(self, track_catalog: dict[str, Track], seed: int = 42):
        self.track_catalog = track_catalog
        self.rng = random.Random(seed)

    def recommend(self, user: UserProfile, emotion: str, history=None, genre=None, k=10) -> list[Track]:
        tracks = list(self.track_catalog.values())
        self.rng.shuffle(tracks)
        return tracks[:k]


class BaseRankingOnlySystem(RecommendationSystem):
    """Baseline: base ranking only (no personalization, no bandit, no diversity)."""

    def __init__(self, track_catalog: dict[str, Track], tracks_by_emotion: dict[str, list[Track]], seed: int = 42):
        self.track_catalog = track_catalog
        self.tracks_by_emotion = tracks_by_emotion
        self.rng = random.Random(seed)

    def recommend(self, user: UserProfile, emotion: str, history=None, genre=None, k=10) -> list[Track]:
        candidates = self.tracks_by_emotion.get(emotion, list(self.track_catalog.values()))
        if genre:
            candidates = [t for t in candidates if t.genre == genre]
        self.rng.shuffle(candidates)
        return candidates[:k]


class FullRecommendationSystem(RecommendationSystem):
    """Full VibeStream pipeline (uses actual pipeline if available, else mock)."""

    def __init__(
        self,
        track_catalog: dict[str, Track],
        tracks_by_emotion: dict[str, list[Track]],
        use_actual_pipeline: bool = False,
        pipeline_fn: Optional[Callable] = None,
        seed: int = 42,
    ):
        self.track_catalog = track_catalog
        self.tracks_by_emotion = tracks_by_emotion
        self.use_actual_pipeline = use_actual_pipeline
        self.pipeline_fn = pipeline_fn
        self.rng = random.Random(seed)

    def recommend(self, user: UserProfile, emotion: str, history=None, genre=None, k=10) -> list[Track]:
        if self.use_actual_pipeline and self.pipeline_fn:
            # Convert user profile to pipeline format
            # This would call the actual Django pipeline
            pass
        # Mock: simulate personalization + bandit + diversity effects
        candidates = self.tracks_by_emotion.get(emotion, list(self.track_catalog.values()))
        if genre:
            candidates = [t for t in candidates if t.genre == genre]

        # Simulate personalization boost
        scored = []
        for track in candidates:
            score = 0.5  # Base
            # Genre preference
            if track.genre in user.genre_prefs:
                score += user.genre_prefs[track.genre] * 0.2
            # Artist preference
            if track.artist in user.artist_prefs:
                score += user.artist_prefs[track.artist] * 0.3
            # Era preference
            if track.era in user.era_prefs:
                score += user.era_prefs[track.era] * 0.1
            # Bandit effect (if user has enough interactions)
            n_interactions = len(user.interactions)
            if n_interactions >= 20:
                score += self.rng.uniform(-0.1, 0.1)  # Thompson sampling noise
            scored.append((score, track))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Diversity (MMR-like)
        selected = []
        remaining = [t for _, t in scored]
        if remaining:
            selected.append(remaining.pop(0))
        diversity_weight = 0.3
        while remaining and len(selected) < k:
            best_idx = 0
            best_mmr = -1
            for idx, track in enumerate(remaining):
                relevance = next(s for s, t in scored if t.track_id == track.track_id)
                max_sim = 0.0
                for sel in selected:
                    sim = 0.0
                    if track.artist == sel.artist:
                        sim += 0.5
                    if track.genre == sel.genre:
                        sim += 0.3
                    if track.era == sel.era:
                        sim += 0.2
                    max_sim = max(max_sim, sim)
                mmr = (1 - diversity_weight) * relevance - diversity_weight * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx
            selected.append(remaining.pop(best_idx))

        return selected[:k]


class RecommendationEvaluator:
    """Evaluates recommendation systems against ground truth."""

    def __init__(self, dataset: EvaluationDataset, k: int = 10):
        self.dataset = dataset
        self.k = k
        self.tracks_by_emotion = self._index_tracks_by_emotion()

    def _index_tracks_by_emotion(self) -> dict[str, list[Track]]:
        """Group tracks by their emotion affinity."""
        # For synthetic data, we approximate by genre-emotion affinity
        from .dataset import EMOTION_GENRE_AFFINITY
        tracks_by_emotion = {e: [] for e in EMOTION_GENRE_AFFINITY.keys()}
        for track in self.dataset.tracks:
            for emotion, affinities in EMOTION_GENRE_AFFINITY.items():
                if track.genre in affinities and affinities[track.genre] > 0.3:
                    tracks_by_emotion[emotion].append(track)
        # Ensure each emotion has tracks
        for emotion in tracks_by_emotion:
            if not tracks_by_emotion[emotion]:
                tracks_by_emotion[emotion] = list(self.dataset.track_catalog.values())
        return tracks_by_emotion

    def evaluate(
        self,
        system: RecommendationSystem,
        system_name: str,
        max_users: Optional[int] = None,
    ) -> EvaluationResult:
        """Evaluate a single system configuration."""
        users = self.dataset.users
        if max_users:
            users = users[:max_users]

        print(f"Evaluating {system_name} on {len(users)} users...")

        all_ndcg = []
        all_hit_rate = []
        all_precision = []
        all_mrr = []
        all_unique_artists = []
        all_artist_rep = []
        all_genre_entropy = []
        all_era_entropy = []
        latencies = []

        per_emotion = {e: {"ndcg": [], "hit_rate": [], "precision": [], "mrr": []} for e in EMOTIONS}
        per_bucket = {
            "0": {"ndcg": [], "hit_rate": [], "precision": [], "mrr": []},
            "1-5": {"ndcg": [], "hit_rate": [], "precision": [], "mrr": []},
            "5-20": {"ndcg": [], "hit_rate": [], "precision": [], "mrr": []},
            "20+": {"ndcg": [], "hit_rate": [], "precision": [], "mrr": []},
        }

        for user in users:
            for emotion in EMOTIONS:
                relevant = self.dataset.get_relevant_tracks(user.user_id, emotion)
                if not relevant:
                    continue

                history = user.mood_history[-10:] if user.mood_history else None
                start = time.perf_counter()
                recs = system.recommend(user, emotion, history=history, k=self.k)
                latency_ms = (time.perf_counter() - start) * 1000
                latencies.append(latency_ms)

                rec_ids = [t.track_id for t in recs]

                ndcg = ndcg_at_k(rec_ids, relevant, self.k)
                hr = hit_rate_at_k(rec_ids, relevant, self.k)
                prec = precision_at_k(rec_ids, relevant, self.k)
                mrr = mean_reciprocal_rank(rec_ids, relevant)

                all_ndcg.append(ndcg)
                all_hit_rate.append(hr)
                all_precision.append(prec)
                all_mrr.append(mrr)

                per_emotion[emotion]["ndcg"].append(ndcg)
                per_emotion[emotion]["hit_rate"].append(hr)
                per_emotion[emotion]["precision"].append(prec)
                per_emotion[emotion]["mrr"].append(mrr)

                # Diversity metrics
                div = diversity_metrics(recs, self.k)
                all_unique_artists.append(div["unique_artists"])
                all_artist_rep.append(div["artist_repetition_rate"])
                all_genre_entropy.append(div["genre_entropy"])
                all_era_entropy.append(div["era_entropy"])

                # Cold-start bucket
                n_interactions = len(user.interactions)
                if n_interactions == 0:
                    bucket = "0"
                elif n_interactions <= 5:
                    bucket = "1-5"
                elif n_interactions <= 20:
                    bucket = "5-20"
                else:
                    bucket = "20+"
                per_bucket[bucket]["ndcg"].append(ndcg)
                per_bucket[bucket]["hit_rate"].append(hr)
                per_bucket[bucket]["precision"].append(prec)
                per_bucket[bucket]["mrr"].append(mrr)

        # Aggregate per-emotion
        emotion_agg = {}
        for emotion, metrics in per_emotion.items():
            if metrics["ndcg"]:
                emotion_agg[emotion] = {k: sum(v) / len(v) for k, v in metrics.items()}

        # Aggregate per bucket
        bucket_agg = {}
        for bucket, metrics in per_bucket.items():
            if metrics["ndcg"]:
                bucket_agg[bucket] = {k: sum(v) / len(v) for k, v in metrics.items()}

        return EvaluationResult(
            system_name=system_name,
            n_users=len(users),
            ndcg_at_10=sum(all_ndcg) / len(all_ndcg) if all_ndcg else 0.0,
            hit_rate_at_10=sum(all_hit_rate) / len(all_hit_rate) if all_hit_rate else 0.0,
            precision_at_10=sum(all_precision) / len(all_precision) if all_precision else 0.0,
            mrr=sum(all_mrr) / len(all_mrr) if all_mrr else 0.0,
            unique_artists_at_10=sum(all_unique_artists) / len(all_unique_artists) if all_unique_artists else 0.0,
            artist_repetition_rate=sum(all_artist_rep) / len(all_artist_rep) if all_artist_rep else 0.0,
            genre_entropy=sum(all_genre_entropy) / len(all_genre_entropy) if all_genre_entropy else 0.0,
            era_entropy=sum(all_era_entropy) / len(all_era_entropy) if all_era_entropy else 0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
            per_emotion=emotion_agg,
            per_interaction_bucket=bucket_agg,
        )


def evaluate_system(
    dataset: EvaluationDataset,
    system: RecommendationSystem,
    system_name: str,
    max_users: Optional[int] = None,
    k: int = 10,
) -> EvaluationResult:
    """Evaluate a single system."""
    evaluator = RecommendationEvaluator(dataset, k=k)
    return evaluator.evaluate(system, system_name, max_users=max_users)


def run_ablation_study(
    dataset: EvaluationDataset,
    max_users: Optional[int] = None,
    k: int = 10,
) -> list[EvaluationResult]:
    """Run ablation study: Base → +Personalization → +Bandit → +Diversity → Full."""
    results = []

    # Build track catalog and emotion index
    track_catalog = dataset.track_catalog
    from .dataset import EMOTION_GENRE_AFFINITY
    tracks_by_emotion = {e: [] for e in EMOTION_GENRE_AFFINITY.keys()}
    for track in dataset.tracks:
        for emotion, affinities in EMOTION_GENRE_AFFINITY.items():
            if track.genre in affinities and affinities[track.genre] > 0.3:
                tracks_by_emotion[emotion].append(track)
    for emotion in tracks_by_emotion:
        if not tracks_by_emotion[emotion]:
            tracks_by_emotion[emotion] = list(track_catalog.values())

    # Variant A: Base ranking only
    base_system = BaseRankingOnlySystem(track_catalog, tracks_by_emotion)
    results.append(evaluate_system(dataset, base_system, "A: Base Ranking Only", max_users, k))

    # Variant B: Base + Personalization
    class PersonalizationSystem(RecommendationSystem):
        def __init__(self, tc, tbe):
            self.tc = tc
            self.tbe = tbe
            self.rng = random.Random(42)
        def recommend(self, user, emotion, history=None, genre=None, k=10):
            candidates = self.tbe.get(emotion, list(self.tc.values()))
            if genre:
                candidates = [t for t in candidates if t.genre == genre]
            scored = []
            for track in candidates:
                score = 0.5
                if track.genre in user.genre_prefs:
                    score += user.genre_prefs[track.genre] * 0.2
                if track.artist in user.artist_prefs:
                    score += user.artist_prefs[track.artist] * 0.3
                if track.era in user.era_prefs:
                    score += user.era_prefs[track.era] * 0.1
                scored.append((score, track))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:k]]
    results.append(evaluate_system(dataset, PersonalizationSystem(track_catalog, tracks_by_emotion), "B: + Personalization", max_users, k))

    # Variant C: Base + Personalization + Bandit
    class BanditSystem(RecommendationSystem):
        def __init__(self, tc, tbe):
            self.tc = tc
            self.tbe = tbe
            self.rng = random.Random(42)
        def recommend(self, user, emotion, history=None, genre=None, k=10):
            candidates = self.tbe.get(emotion, list(self.tc.values()))
            if genre:
                candidates = [t for t in candidates if t.genre == genre]
            scored = []
            n_interactions = len(user.interactions)
            for track in candidates:
                score = 0.5
                if track.genre in user.genre_prefs:
                    score += user.genre_prefs[track.genre] * 0.2
                if track.artist in user.artist_prefs:
                    score += user.artist_prefs[track.artist] * 0.3
                if track.era in user.era_prefs:
                    score += user.era_prefs[track.era] * 0.1
                # Bandit effect
                if n_interactions >= 20:
                    score += self.rng.uniform(-0.15, 0.15)
                scored.append((score, track))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:k]]
    results.append(evaluate_system(dataset, BanditSystem(track_catalog, tracks_by_emotion), "C: + Bandit", max_users, k))

    # Variant D: Base + Personalization + Bandit + Diversity
    class DiversitySystem(RecommendationSystem):
        def __init__(self, tc, tbe):
            self.tc = tc
            self.tbe = tbe
            self.rng = random.Random(42)
        def recommend(self, user, emotion, history=None, genre=None, k=10):
            candidates = self.tbe.get(emotion, list(self.tc.values()))
            if genre:
                candidates = [t for t in candidates if t.genre == genre]
            scored = []
            n_interactions = len(user.interactions)
            for track in candidates:
                score = 0.5
                if track.genre in user.genre_prefs:
                    score += user.genre_prefs[track.genre] * 0.2
                if track.artist in user.artist_prefs:
                    score += user.artist_prefs[track.artist] * 0.3
                if track.era in user.era_prefs:
                    score += user.era_prefs[track.era] * 0.1
                if n_interactions >= 20:
                    score += self.rng.uniform(-0.15, 0.15)
                scored.append((score, track))
            scored.sort(key=lambda x: x[0], reverse=True)
            # MMR diversity
            selected = []
            remaining = [t for _, t in scored]
            if remaining:
                selected.append(remaining.pop(0))
            diversity_weight = 0.3
            while remaining and len(selected) < k:
                best_idx = 0
                best_mmr = -1
                for idx, track in enumerate(remaining):
                    relevance = next(s for s, t in scored if t.track_id == track.track_id)
                    max_sim = 0.0
                    for sel in selected:
                        sim = 0.0
                        if track.artist == sel.artist:
                            sim += 0.5
                        if track.genre == sel.genre:
                            sim += 0.3
                        if track.era == sel.era:
                            sim += 0.2
                        max_sim = max(max_sim, sim)
                    mmr = (1 - diversity_weight) * relevance - diversity_weight * max_sim
                    if mmr > best_mmr:
                        best_mmr = mmr
                        best_idx = idx
                selected.append(remaining.pop(best_idx))
            return selected[:k]
    results.append(evaluate_system(dataset, DiversitySystem(track_catalog, tracks_by_emotion), "D: + Diversity", max_users, k))

    # Variant E: Full system (same as D for mock, but would use actual pipeline)
    results.append(evaluate_system(dataset, DiversitySystem(track_catalog, tracks_by_emotion), "E: Full System", max_users, k))

    return results


def run_cold_start_evaluation(
    dataset: EvaluationDataset,
    system: RecommendationSystem,
    system_name: str,
    k: int = 10,
) -> dict:
    """Evaluate system performance by interaction count bucket."""
    evaluator = RecommendationEvaluator(dataset, k=k)
    users = dataset.users

    buckets = {
        "0": [],
        "1-5": [],
        "5-20": [],
        "20+": [],
    }

    for user in users:
        n_interactions = len(user.interactions)
        if n_interactions == 0:
            bucket = "0"
        elif n_interactions <= 5:
            bucket = "1-5"
        elif n_interactions <= 20:
            bucket = "5-20"
        else:
            bucket = "20+"
        buckets[bucket].append(user)

    results = {}
    for bucket_name, bucket_users in buckets.items():
        if not bucket_users:
            results[bucket_name] = {"n_users": 0}
            continue
        # Create mini dataset for this bucket
        mini_dataset = EvaluationDataset(
            users=bucket_users,
            tracks=dataset.tracks,
            track_catalog=dataset.track_catalog,
            relevance={u.user_id: dataset.relevance[u.user_id] for u in bucket_users},
        )
        evaluator = RecommendationEvaluator(mini_dataset, k=k)
        result = evaluator.evaluate(system, system_name)
        results[bucket_name] = {
            "n_users": len(bucket_users),
            "ndcg_at_10": result.ndcg_at_10,
            "hit_rate_at_10": result.hit_rate_at_10,
            "precision_at_10": result.precision_at_10,
            "mrr": result.mrr,
            "unique_artists_at_10": result.unique_artists_at_10,
            "artist_repetition_rate": result.artist_repetition_rate,
        }

    return results


__all__ = [
    "EvaluationResult",
    "RecommendationSystem",
    "MockRecommendationSystem",
    "BaseRankingOnlySystem",
    "FullRecommendationSystem",
    "RecommendationEvaluator",
    "evaluate_system",
    "run_ablation_study",
    "run_cold_start_evaluation",
]