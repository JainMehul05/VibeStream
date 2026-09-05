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
- **Generated**: 2026-09-05T07:44:10.549397

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
| A: Base Ranking Only | 0.0244 | 0.1265 | 0.0151 | 0.0397 | 8.85 | 0.1278 | 1.9593 | 2.2893 |
| B: + Personalization | 0.9021 | 0.9217 | 0.3452 | 0.9046 | 2.92 | 0.7871 | 0.5193 | 1.9972 |
| C: + Bandit | 0.8049 | 0.9036 | 0.3175 | 0.8151 | 3.22 | 0.7530 | 0.6210 | 2.0695 |
| D: + Diversity | 0.5443 | 0.8434 | 0.1849 | 0.7824 | 8.16 | 0.2048 | 1.8903 | 2.4079 |
| E: Full System | 0.5443 | 0.8434 | 0.1849 | 0.7824 | 8.16 | 0.2048 | 1.8903 | 2.4079 |

## Cold-Start Evaluation

| Interaction Bucket | N Users | NDCG@10 | Hit Rate@10 | Precision@10 | MRR | Unique Artists@10 | Artist Rep Rate |
|--------------------|---------|---------|-------------|--------------|-----|-------------------|-----------------|
| 0 | 41 | 0.6804 | 1.0000 | 0.2651 | 1.0000 | 7.67 | 0.2584 |
| 1-5 | 57 | 0.6865 | 0.9474 | 0.2158 | 0.9091 | 7.60 | 0.2667 |
| 5-20 | 48 | 0.5560 | 0.7978 | 0.2011 | 0.7921 | 7.65 | 0.2609 |
| 20+ | 54 | 0.4571 | 0.7857 | 0.1114 | 0.7468 | 9.33 | 0.0746 |

## Per-Emotion Breakdown (Full System)

| Emotion | NDCG@10 | Hit Rate@10 | Precision@10 | MRR |
|---------|---------|-------------|--------------|-----|
| sadness | 0.6307 | 0.8889 | 0.2000 | 0.8374 |
| joy | 0.5735 | 0.8571 | 0.1629 | 0.8226 |
| love | 0.5617 | 0.8571 | 0.1821 | 0.8304 |
| anger | 0.5449 | 0.8654 | 0.2481 | 0.8316 |
| fear | 0.5814 | 0.8125 | 0.2313 | 0.7591 |
| neutral | 0.5276 | 0.7879 | 0.1485 | 0.7606 |

## Relevance vs Diversity Tradeoff

| System | NDCG@10 (Relevance) | Unique Artists@10 (Diversity) | Artist Rep Rate |
|--------|---------------------|-------------------------------|-----------------|
| A: Base Ranking Only | 0.0244 | 8.85 | 0.1278 |
| B: + Personalization | 0.9021 | 2.92 | 0.7871 |
| C: + Bandit | 0.8049 | 3.22 | 0.7530 |
| D: + Diversity | 0.5443 | 8.16 | 0.2048 |
| E: Full System | 0.5443 | 8.16 | 0.2048 |

## Latency (Mock)

- Average recommendation latency: 50.86 ms
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