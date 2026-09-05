# Phase 4 Evaluation Report — VibeStream

**Label: OFFLINE SYNTHETIC EVALUATION**

This evaluation uses a synthetic dataset generated to mimic real user behavior.
Results should NOT be interpreted as production performance.

## Dataset

- **Users**: 200
- **Tracks**: 990
- **Genres**: 18
- **Artists**: 142
- **Eras**: 7
- **Emotions**: 6 (sadness, joy, love, anger, fear, neutral)
- **Seed**: 42
- **Generated**: 2026-09-05T08:02:57.073873

### Interaction Distribution

- Mean interactions/user: 21.3
- Median interactions/user: 6
- Min: 0, Max: 98
- Users with 0 interactions: 41
- Users with 1-5 interactions: 57
- Users with 5-20 interactions: 48
- Users with 20+ interactions: 54

## Ablation Study

| System | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate | Genre Entropy | Era Entropy |
|--------|---------|-------------|--------------|-----|-------------------|-----------------|---------------|-------------|
| A: Base Ranking Only | 0.0257 | 0.1111 | 0.0111 | 0.0295 | 8.91 | 0.1213 | 1.9746 | 2.2671 |
| B: + Personalization | 0.8559 | 0.8824 | 0.3026 | 0.8758 | 2.75 | 0.8054 | 0.6333 | 2.0968 |
| C: + Bandit | 0.7702 | 0.8693 | 0.2804 | 0.8004 | 3.22 | 0.7531 | 0.7589 | 2.1274 |
| D: + Diversity | 0.5284 | 0.8039 | 0.1601 | 0.7728 | 8.45 | 0.1721 | 1.9478 | 2.3829 |
| E: Full System | 0.5284 | 0.8039 | 0.1601 | 0.7728 | 8.45 | 0.1721 | 1.9478 | 2.3829 |

## Cold-Start Evaluation

| Interaction Bucket | N Users | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate |
|--------------------|---------|---------|-------------|--------------|-----|-------------------|-----------------|
| 0 | 41 | 0.7033 | 1.0000 | 0.1821 | 1.0000 | 7.87 | 0.2365 |
| 1-5 | 57 | 0.6666 | 0.9231 | 0.1885 | 0.9038 | 8.38 | 0.1795 |
| 5-20 | 48 | 0.6405 | 0.8750 | 0.1818 | 0.8750 | 8.16 | 0.2045 |
| 20+ | 54 | 0.4109 | 0.7500 | 0.1237 | 0.6595 | 9.13 | 0.0965 |

## Per-Emotion Breakdown (Full System)

| Emotion | NDCG@10 | Hit Rate@10 | Precision@10 | MRR |
|---------|---------|-------------|--------------|-----|
| sadness | 0.5814 | 0.9000 | 0.1671 | 0.8576 |
| joy | 0.5351 | 0.8636 | 0.1636 | 0.7920 |
| love | 0.6420 | 0.9000 | 0.1817 | 0.8618 |
| anger | 0.5819 | 0.8679 | 0.1642 | 0.8235 |
| fear | 0.5957 | 0.8158 | 0.1658 | 0.8026 |
| neutral | 0.4461 | 0.7500 | 0.1188 | 0.6964 |

## Relevance vs Diversity Tradeoff

| System | NDCG@10 (Relevance) | Unique Artists@10 (Diversity) | Artist Rep Rate |
|--------|---------------------|-------------------------------|-----------------|
| A: Base Ranking Only | 0.0257 | 8.91 | 0.1213 |
| B: + Personalization | 0.8559 | 2.75 | 0.8054 |
| C: + Bandit | 0.7702 | 3.22 | 0.7531 |
| D: + Diversity | 0.5284 | 8.45 | 0.1721 |
| E: Full System | 0.5284 | 8.45 | 0.1721 |

## Latency (Mock)

- Average recommendation latency: 46.79 ms
(Mock system — actual pipeline latency will differ)

## Limitations

1. **OFFLINE SYNTHETIC EVALUATION** — No real user data used.
2. Ground truth relevance derived from latent preferences + emotion-genre affinity, not observed behavior.
3. Mock recommendation systems simulate personalization/bandit/diversity effects; actual pipeline may differ.
4. Dataset assumes stationary preferences; real users evolve.
5. No position bias, no exposure bias correction (no logged bandit data).
6. Cold-start buckets based on synthetic interaction counts, not real onboarding.

## Methodology

### Synthetic Dataset Generation
- Users: 1,000 with latent Dirichlet-distributed genre preferences, sparse artist/era preferences
- Tracks: 5,000 across 18 genres with realistic popularity (Beta) and era distributions
- Interactions: ~50/user average, signal probability = base + preference match
- Relevance: track is relevant if latent_score(genre, artist, era, emotion_affinity) > 0.3

### Metrics
- **NDCG@10**: Normalized Discounted Cumulative Gain at 10
- **Hit Rate@10**: Fraction of users with ≥1 relevant track in top 10
- **Precision@10**: Fraction of top 10 that are relevant
- **MRR**: Mean Reciprocal Rank of first relevant item
- **Unique Artists@10**: Count of distinct artists in top 10
- **Artist Rep Rate**: Fraction of consecutive same-artist pairs in top 10
- **Genre/Era Entropy**: Shannon entropy of genre/era distribution in top 10

### Ablation Variants
A. Base Ranking Only (random shuffle per emotion)
B. + Personalization (genre/artist/era preference boost)
C. + Bandit (Thompson Sampling noise for users with 20+ events)
D. + Diversity (MMR with lambda=0.3 across artist/genre/era)
E. Full System (same as D for mock)