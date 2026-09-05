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
- **Generated**: 2026-09-05T13:21:10.042251+00:00

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
| A: Base Ranking Only | 0.0187 | 0.0978 | 0.0103 | 0.0315 | 8.87 | 0.1256 | 1.9555 | 2.2674 |
| B: + Personalization | 0.8454 | 0.8587 | 0.3098 | 0.8542 | 2.73 | 0.8080 | 0.5087 | 2.0904 |
| C: + Bandit | 0.7678 | 0.8587 | 0.2973 | 0.7812 | 3.19 | 0.7566 | 0.6722 | 2.0927 |
| D: + Diversity | 0.5331 | 0.7717 | 0.1685 | 0.7498 | 8.62 | 0.1528 | 1.8931 | 2.3842 |
| E: Full System | 0.5331 | 0.7717 | 0.1685 | 0.7498 | 8.62 | 0.1528 | 1.8931 | 2.3842 |

## Cold-Start Evaluation

| Interaction Bucket | N Users | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate |
|--------------------|---------|---------|-------------|--------------|-----|-------------------|-----------------|
| 0 | 41 | 0.5715 | 0.8281 | 0.2188 | 0.8281 | 7.88 | 0.2361 |
| 1-5 | 57 | 0.6551 | 0.9278 | 0.1938 | 0.9278 | 8.30 | 0.1890 |
| 5-20 | 48 | 0.6364 | 0.8222 | 0.2000 | 0.8222 | 7.88 | 0.2358 |
| 20+ | 54 | 0.3320 | 0.6786 | 0.1238 | 0.5887 | 9.02 | 0.1085 |

## Per-Emotion Breakdown (Full System)

| Emotion | NDCG@10 | Hit Rate@10 | Precision@10 | MRR |
|---------|---------|-------------|--------------|-----|
| sadness | 0.5987 | 0.8413 | 0.1540 | 0.8192 |
| joy | 0.5502 | 0.8696 | 0.1725 | 0.8496 |
| love | 0.5812 | 0.8871 | 0.2097 | 0.8398 |
| anger | 0.5979 | 0.9091 | 0.2273 | 0.8677 |
| fear | 0.5484 | 0.7250 | 0.1625 | 0.7036 |
| neutral | 0.5460 | 0.8000 | 0.1543 | 0.7500 |

## Relevance vs Diversity Tradeoff

| System | NDCG@10 (Relevance) | Unique Artists@10 (Diversity) | Artist Rep Rate |
|--------|---------------------|-------------------------------|-----------------|
| A: Base Ranking Only | 0.0187 | 8.87 | 0.1256 |
| B: + Personalization | 0.8454 | 2.73 | 0.8080 |
| C: + Bandit | 0.7678 | 3.19 | 0.7566 |
| D: + Diversity | 0.5331 | 8.62 | 0.1528 |
| E: Full System | 0.5331 | 8.62 | 0.1528 |

## Latency (Mock)

- Average recommendation latency: 41.12 ms
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