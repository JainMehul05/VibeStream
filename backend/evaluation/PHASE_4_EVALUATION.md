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
- **Generated**: 2026-09-05T10:27:56.079184+00:00

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
| A: Base Ranking Only | 0.0349 | 0.1438 | 0.0170 | 0.0608 | 8.94 | 0.1176 | 1.9514 | 2.2864 |
| B: + Personalization | 0.8729 | 0.9020 | 0.3346 | 0.8813 | 2.74 | 0.8068 | 0.5482 | 2.0585 |
| C: + Bandit | 0.7824 | 0.8954 | 0.3092 | 0.8031 | 3.12 | 0.7640 | 0.6493 | 2.1099 |
| D: + Diversity | 0.5076 | 0.8105 | 0.1654 | 0.7754 | 8.37 | 0.1808 | 1.9210 | 2.3683 |
| E: Full System | 0.5076 | 0.8105 | 0.1654 | 0.7754 | 8.37 | 0.1808 | 1.9210 | 2.3683 |

## Cold-Start Evaluation

| Interaction Bucket | N Users | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate |
|--------------------|---------|---------|-------------|--------------|-----|-------------------|-----------------|
| 0 | 41 | 0.7111 | 0.9583 | 0.2146 | 0.9479 | 7.77 | 0.2477 |
| 1-5 | 57 | 0.5915 | 0.9286 | 0.1988 | 0.8807 | 7.80 | 0.2447 |
| 5-20 | 48 | 0.5978 | 0.8451 | 0.1915 | 0.8451 | 8.03 | 0.2191 |
| 20+ | 54 | 0.4149 | 0.7671 | 0.1493 | 0.7412 | 8.96 | 0.1157 |

## Per-Emotion Breakdown (Full System)

| Emotion | NDCG@10 | Hit Rate@10 | Precision@10 | MRR |
|---------|---------|-------------|--------------|-----|
| sadness | 0.5419 | 0.8667 | 0.1717 | 0.8440 |
| joy | 0.5739 | 0.8605 | 0.1767 | 0.8605 |
| love | 0.5041 | 0.8269 | 0.1904 | 0.7607 |
| anger | 0.6021 | 0.9531 | 0.1969 | 0.9167 |
| fear | 0.6210 | 0.8649 | 0.1838 | 0.7921 |
| neutral | 0.4737 | 0.7500 | 0.1750 | 0.7500 |

## Relevance vs Diversity Tradeoff

| System | NDCG@10 (Relevance) | Unique Artists@10 (Diversity) | Artist Rep Rate |
|--------|---------------------|-------------------------------|-----------------|
| A: Base Ranking Only | 0.0349 | 8.94 | 0.1176 |
| B: + Personalization | 0.8729 | 2.74 | 0.8068 |
| C: + Bandit | 0.7824 | 3.12 | 0.7640 |
| D: + Diversity | 0.5076 | 8.37 | 0.1808 |
| E: Full System | 0.5076 | 8.37 | 0.1808 |

## Latency (Mock)

- Average recommendation latency: 51.00 ms
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