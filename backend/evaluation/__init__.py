"""Evaluation package for VibeStream recommendation quality assessment."""

from .metrics import (
    ndcg_at_k,
    hit_rate_at_k,
    precision_at_k,
    mean_reciprocal_rank,
    diversity_metrics,
    artist_repetition_rate,
    genre_entropy,
)
from .dataset import (
    SyntheticDatasetGenerator,
    EvaluationDataset,
    create_synthetic_dataset,
)
from .evaluator import (
    RecommendationEvaluator,
    evaluate_system,
    run_ablation_study,
    run_cold_start_evaluation,
    RecommendationSystem,
    MockRecommendationSystem,
    BaseRankingOnlySystem,
    FullRecommendationSystem,
)

__all__ = [
    "ndcg_at_k",
    "hit_rate_at_k",
    "precision_at_k",
    "mean_reciprocal_rank",
    "diversity_metrics",
    "artist_repetition_rate",
    "genre_entropy",
    "SyntheticDatasetGenerator",
    "EvaluationDataset",
    "create_synthetic_dataset",
    "RecommendationEvaluator",
    "evaluate_system",
    "run_ablation_study",
    "run_cold_start_evaluation",
    "RecommendationSystem",
    "MockRecommendationSystem",
    "BaseRankingOnlySystem",
    "FullRecommendationSystem",
]