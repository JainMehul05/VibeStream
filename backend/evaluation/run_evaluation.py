#!/usr/bin/env python3
"""Run complete Phase 4 recommendation evaluation.

This script:
1. Generates synthetic evaluation dataset (OFFLINE SYNTHETIC EVALUATION)
2. Runs ablation study (5 variants)
3. Runs cold-start evaluation
4. Produces PHASE_4_EVALUATION.md with tables
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluation import (
    create_synthetic_dataset,
    run_ablation_study,
    run_cold_start_evaluation,
    FullRecommendationSystem,
)
from evaluation.dataset import EMOTIONS


def main():
    print("=" * 60)
    print("VibeStream Phase 4 — Recommendation Evaluation")
    print("OFFLINE SYNTHETIC EVALUATION")
    print("=" * 60)

    # Generate dataset (smaller for speed)
    print("\n[1/4] Generating synthetic dataset...")
    dataset = create_synthetic_dataset(n_users=200, n_tracks=1000, seed=42)
    print(f"    Users: {len(dataset.users)}")
    print(f"    Tracks: {len(dataset.tracks)}")
    print(f"    Emotions: {len(dataset.relevance.get(list(dataset.relevance.keys())[0], {}))}")

    # Build track catalog and emotion index for evaluator
    track_catalog = dataset.track_catalog
    from evaluation.dataset import EMOTION_GENRE_AFFINITY
    tracks_by_emotion = {e: [] for e in EMOTION_GENRE_AFFINITY.keys()}
    for track in dataset.tracks:
        for emotion, affinities in EMOTION_GENRE_AFFINITY.items():
            if track.genre in affinities and affinities[track.genre] > 0.3:
                tracks_by_emotion[emotion].append(track)
    for emotion in tracks_by_emotion:
        if not tracks_by_emotion[emotion]:
            tracks_by_emotion[emotion] = list(track_catalog.values())

    # Ablation study
    print("\n[2/4] Running ablation study...")
    ablation_results = run_ablation_study(dataset, max_users=100, k=10)

    # Cold-start evaluation
    print("\n[3/4] Running cold-start evaluation...")
    full_system = FullRecommendationSystem(track_catalog, tracks_by_emotion)
    cold_start_results = run_cold_start_evaluation(dataset, full_system, "Full System", k=10)

    # Full system evaluation (larger sample)
    print("\n[4/4] Running full system evaluation...")
    from evaluation import evaluate_system
    full_result = evaluate_system(dataset, full_system, "Full System", max_users=200, k=10)

    # Generate report
    print("\nGenerating PHASE_4_EVALUATION.md...")
    generate_report(dataset, ablation_results, cold_start_results, full_result)

    print("\n" + "=" * 60)
    print("Evaluation complete!")
    print("=" * 60)


def generate_report(dataset, ablation_results, cold_start_results, full_result):
    """Generate PHASE_4_EVALUATION.md with all results."""
    lines = []
    lines.append("# Phase 4 Evaluation Report — VibeStream")
    lines.append("")
    lines.append("**Label: OFFLINE SYNTHETIC EVALUATION**")
    lines.append("")
    lines.append("This evaluation uses a synthetic dataset generated to mimic real user behavior.")
    lines.append("Results should NOT be interpreted as production performance.")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- **Users**: {len(dataset.users):,}")
    lines.append(f"- **Tracks**: {len(dataset.tracks):,}")
    lines.append(f"- **Genres**: {len(set(t.genre for t in dataset.tracks))}")
    lines.append(f"- **Artists**: {len(set(t.artist for t in dataset.tracks))}")
    lines.append(f"- **Eras**: {len(set(t.era for t in dataset.tracks))}")
    lines.append(f"- **Emotions**: {len(EMOTIONS)} ({', '.join(EMOTIONS)})")
    lines.append(f"- **Seed**: {dataset.metadata.get('seed', 'N/A')}")
    lines.append(f"- **Generated**: {dataset.metadata.get('generated_at', 'N/A')}")
    lines.append("")
    lines.append("### Interaction Distribution")
    lines.append("")
    interaction_counts = [len(u.interactions) for u in dataset.users]
    lines.append(f"- Mean interactions/user: {sum(interaction_counts)/len(interaction_counts):.1f}")
    lines.append(f"- Median interactions/user: {sorted(interaction_counts)[len(interaction_counts)//2]}")
    lines.append(f"- Min: {min(interaction_counts)}, Max: {max(interaction_counts)}")
    lines.append(f"- Users with 0 interactions: {sum(1 for c in interaction_counts if c == 0)}")
    lines.append(f"- Users with 1-5 interactions: {sum(1 for c in interaction_counts if 1 <= c <= 5)}")
    lines.append(f"- Users with 5-20 interactions: {sum(1 for c in interaction_counts if 5 < c <= 20)}")
    lines.append(f"- Users with 20+ interactions: {sum(1 for c in interaction_counts if c > 20)}")
    lines.append("")

    # Ablation table
    lines.append("## Ablation Study")
    lines.append("")
    lines.append("| System | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate | Genre Entropy | Era Entropy |")
    lines.append("|--------|---------|-------------|--------------|-----|-------------------|-----------------|---------------|-------------|")
    for r in ablation_results:
        lines.append(f"| {r.system_name} | {r.ndcg_at_10:.4f} | {r.hit_rate_at_10:.4f} | {r.precision_at_10:.4f} | {r.mrr:.4f} | {r.unique_artists_at_10:.2f} | {r.artist_repetition_rate:.4f} | {r.genre_entropy:.4f} | {r.era_entropy:.4f} |")
    lines.append("")

    # Cold-start table
    lines.append("## Cold-Start Evaluation")
    lines.append("")
    lines.append("| Interaction Bucket | N Users | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate |")
    lines.append("|--------------------|---------|---------|-------------|--------------|-----|-------------------|-----------------|")
    for bucket, metrics in cold_start_results.items():
        if metrics.get("n_users", 0) > 0:
            lines.append(f"| {bucket} | {metrics['n_users']} | {metrics['ndcg_at_10']:.4f} | {metrics['hit_rate_at_10']:.4f} | {metrics['precision_at_10']:.4f} | {metrics['mrr']:.4f} | {metrics['unique_artists_at_10']:.2f} | {metrics['artist_repetition_rate']:.4f} |")
        else:
            lines.append(f"| {bucket} | 0 | N/A | N/A | N/A | N/A | N/A | N/A |")
    lines.append("")

    # Per-emotion breakdown
    lines.append("## Per-Emotion Breakdown (Full System)")
    lines.append("")
    lines.append("| Emotion | NDCG@10 | Hit Rate@10 | Precision@10 | MRR |")
    lines.append("|---------|---------|-------------|--------------|-----|")
    for emotion, metrics in full_result.per_emotion.items():
        lines.append(f"| {emotion} | {metrics.get('ndcg', 0):.4f} | {metrics.get('hit_rate', 0):.4f} | {metrics.get('precision', 0):.4f} | {metrics.get('mrr', 0):.4f} |")
    lines.append("")

    # Diversity tradeoff
    lines.append("## Relevance vs Diversity Tradeoff")
    lines.append("")
    lines.append("| System | NDCG@10 (Relevance) | Unique Artists@10 (Diversity) | Artist Rep Rate |")
    lines.append("|--------|---------------------|-------------------------------|-----------------|")
    for r in ablation_results:
        lines.append(f"| {r.system_name} | {r.ndcg_at_10:.4f} | {r.unique_artists_at_10:.2f} | {r.artist_repetition_rate:.4f} |")
    lines.append("")

    # Latency
    lines.append("## Latency (Mock)")
    lines.append("")
    lines.append(f"- Average recommendation latency: {full_result.avg_latency_ms:.2f} ms")
    lines.append("(Mock system — actual pipeline latency will differ)")
    lines.append("")

    # Limitations
    lines.append("## Limitations")
    lines.append("")
    lines.append("1. **OFFLINE SYNTHETIC EVALUATION** — No real user data used.")
    lines.append("2. Ground truth relevance derived from latent preferences + emotion-genre affinity, not observed behavior.")
    lines.append("3. Mock recommendation systems simulate personalization/bandit/diversity effects; actual pipeline may differ.")
    lines.append("4. Dataset assumes stationary preferences; real users evolve.")
    lines.append("5. No position bias, no exposure bias correction (no logged bandit data).")
    lines.append("6. Cold-start buckets based on synthetic interaction counts, not real onboarding.")
    lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append("### Synthetic Dataset Generation")
    lines.append("- Users: 1,000 with latent Dirichlet-distributed genre preferences, sparse artist/era preferences")
    lines.append("- Tracks: 5,000 across 18 genres with realistic popularity (Beta) and era distributions")
    lines.append("- Interactions: ~50/user average, signal probability = base + preference match")
    lines.append("- Relevance: track is relevant if latent_score(genre, artist, era, emotion_affinity) > 0.3")
    lines.append("")
    lines.append("### Metrics")
    lines.append("- **NDCG@10**: Normalized Discounted Cumulative Gain at 10")
    lines.append("- **Hit Rate@10**: Fraction of users with ≥1 relevant track in top 10")
    lines.append("- **Precision@10**: Fraction of top 10 that are relevant")
    lines.append("- **MRR**: Mean Reciprocal Rank of first relevant item")
    lines.append("- **Unique Artists@10**: Count of distinct artists in top 10")
    lines.append("- **Artist Rep Rate**: Fraction of consecutive same-artist pairs in top 10")
    lines.append("- **Genre/Era Entropy**: Shannon entropy of genre/era distribution in top 10")
    lines.append("")
    lines.append("### Ablation Variants")
    lines.append("A. Base Ranking Only (random shuffle per emotion)")
    lines.append("B. + Personalization (genre/artist/era preference boost)")
    lines.append("C. + Bandit (Thompson Sampling noise for users with 20+ events)")
    lines.append("D. + Diversity (MMR with lambda=0.3 across artist/genre/era)")
    lines.append("E. Full System (same as D for mock)")

    with open("PHASE_4_EVALUATION.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("Report written to PHASE_4_EVALUATION.md")


if __name__ == "__main__":
    main()