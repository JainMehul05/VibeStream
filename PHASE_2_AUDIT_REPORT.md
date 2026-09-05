# VibeStream Phase 2 — Repository Audit

## 1. Current Recommendation Architecture

### 1.1 End-to-End Flow

```
User Input (Text/Speech/Face)
         ↓
    Modal Inference (FastAPI on Modal)
    ├─ Text: BERT classifier → emotion
    ├─ Speech: SVC + MFCC → emotion
    └─ Face: FER + MTCNN → emotion
         ↓
    Recommendation Generation (Modal)
    ├─ Emotion → Deezer search query (keyword map)
    ├─ History (optional) → EWMA (0.85 decay) + 1st-order Markov
    │   → mood_affinity → recurring_mood → blend_ratio
    ├─ Fetch primary + recurring tracks from Deezer
    ├─ Quality rank (curated_order + 0.2 × popularity)
    ├─ Interleave primary + recurring at blend_ratio
    └─ Return {emotion, recommendations[], degraded}
         ↓
    Django Backend (Vercel) — Personalization Layer
    ├─ L1 Mood Calibration: UserProfile.mood_calibration
    │   {predicted: {actual: count}} → rewrite if count ≥ 3
    └─ L2 Bandit Re-rank: UserProfile.taste_profile
        Beta-Bernoulli posterior over 22-dim features
        Thompson Sampling → reorder candidate list
        Cold-start safe: identity when events < 20
         ↓
    Frontend Display (ResultsPage)
    → Track cards with 👍/👎/Open in Deezer
    → Feedback → POST /api/v1/feedback/
```

### 1.2 Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Emotion detection | `modal_inference/inference/` | Text/Speech/Face → emotion label |
| Candidate generation | `modal_inference/recommendation/music_recommendation.py` | Deezer search + history blend |
| Base ranking | `modal_inference/recommendation/personalization.py` | `rank_by_quality` (curated + popularity) |
| Mood/context | `modal_inference/recommendation/personalization.py` | EWMA + Markov → recurring mood, blend |
| Personalization (L1) | `backend/api/calibration.py` | Per-user mood correction map |
| Personalization (L2) | `backend/api/bandit.py` | Thompson Sampling bandit re-rank |
| Track features | `backend/api/track_features.py` | 22-dim feature extraction |
| Feedback API | `backend/api/feedback_views.py` | Mood + track feedback endpoints |
| Feedback store | `backend/api/feedback_store.py` | Mongo time-series persistence |
| User profile | `backend/api/models.py` | `UserProfile` (mood_calibration, taste_profile) |
| Frontend recs | `frontend/src/pages/ResultsPage.js` | Track display, feedback UI |
| Profile page | `frontend/src/components/Profile/Profile.js` | History, saved tracks, settings |

---

## 2. Current Feedback Architecture

### 2.1 Feedback Endpoint

```
POST /api/v1/feedback/ (JWT required)
┌─────────────────────────────────────────────────────────┐
│ kind="mood"                                             │
│   predicted, actual, input_type, confidence?, session_id│
│   → mood_feedback (time-series)                         │
│   → bump UserProfile.mood_calibration[predicted][actual]│
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ kind="track"                                            │
│   track_id, signal ∈ {like, unlike, open_deezer, clear} │
│   context_emotion?, track? (full dict)                  │
│   → track_feedback (time-series) with features + seq    │
│   → Set-vote semantics:                                 │
│       like/unlike: revert prior vote (exact features)   │
│                        → apply new vote                 │
│       clear: revert prior vote → net zero               │
│       open_deezer: purely additive, never reverted      │
│   → Update UserProfile.taste_profile (bandit posterior) │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Bandit Posterior Updates

```python
# In bandit.py
WEIGHTS = {"like": 1.0, "unlike": 1.0, "open_deezer": 0.5}
PRIOR_ALPHA = 1.0, PRIOR_BETA = 1.0
COLD_START_MIN_EVENTS = 20

# Feature vector (22 dims):
# [0..5]   emotion one-hot (sadness, joy, love, anger, fear, neutral)
# [6..12]  decade one-hot (pre1960, 60s, 70s, 80s, 90s, 2000s, 2010+)
# [13..16] duration one-hot (<2m, 2-4m, 4-6m, 6m+)
# [17..21] popularity one-hot (quintiles p0-p4, list-relative)
```

---

## 3. Current Thompson Sampling Implementation

### 3.1 `backend/api/bandit.py`

**Key functions:**
- `update_posterior(taste_profile, features, signal)` — applies +α or +β
- `revert_posterior(taste_profile, features, signal)` — subtracts (clamps at prior)
- `rerank(tracks, taste_profile, context_emotion, rng)` — Thompson sample per axis, dot product with track features, sort descending

**Properties:**
- Identity-when-cold: events < 20 → return input order unchanged
- One sample per axis per call (standard contextual bandit)
- Stable tie-breaking by original index
- No track injection/dropping — only reorders

### 3.2 Integration Point

In `backend/api/views.py:music_recommendation()`:
```python
profile = _profile_for_request(request)
if profile and recs:
    reranked = bandit.rerank(recs, taste_profile=profile.taste_profile, context_emotion=emotion)
    if reranked is not recs:
        result["recommendations"] = reranked
```

---

## 4. Current Personalization Functionality

### 4.1 What Exists (Phase 1)

| Layer | Mechanism | State |
|-------|-----------|-------|
| **L0: Base** | Deezer search + quality rank | ✅ Modal |
| **L1: Mood calibration** | Per-user {predicted→{actual:count}} ≥3 rewrites | ✅ Backend |
| **L2: Bandit** | Thompson Sampling on 22-dim features | ✅ Backend |
| **History blend** | EWMA + Markov → recurring mood + interleave | ✅ Modal |
| **Genre filter** | Keyword prepended to Deezer query | ✅ Modal + Frontend |
| **Cold start** | Bandit no-op until 20 events | ✅ Backend |

### 4.2 What's Missing (Phase 2 Target)

| Gap | Description |
|-----|-------------|
| **Persistent preference profile** | No explicit genre/artist/era preferences beyond bandit's implicit features |
| **Feedback → personalization loop** | Bandit updates but no interpretable profile (e.g., "favorite genres") |
| **Candidate generation separation** | Tightly coupled in Modal's `get_music_recommendation()` |
| **Diversity re-ranking** | No artist/genre/era diversity control |
| **Explanations** | No "why this track?" surfaced to user |
| **Personalization dashboard** | Profile page shows history but not learned preferences |
| **Cold-start strategy** | Only bandit cold-start; no explicit new-user handling |

---

## 5. Current Track Feature Extraction

**File:** `backend/api/track_features.py` (also `modal_inference/recommendation/personalization.py` has similar logic)

**Feature vector (22 dimensions, fixed order):**
```
0-5:   emotion (sadness, joy, love, anger, fear, neutral)
6-12:  decade (pre1960, 60s, 70s, 80s, 90s, 2000s, 2010+)
13-16: duration (<2m, 2-4m, 4-6m, 6m+)
17-21: popularity (quintiles p0-p4, list-relative)
```

**Limitations for Phase 2:**
- No genre features (Deezer search doesn't return genre)
- No artist features
- No explicit era preference beyond decade buckets
- Popularity is list-relative, not absolute

---

## 6. Relevant Models

### 6.1 `backend/api/models.py` — `UserProfile`

```python
class UserProfile(Document):
    username = StringField(required=True)
    mood_history = ListField(StringField())
    listening_history = ListField()  # mixed: dicts + legacy strings
    recommendations = ListField(DictField())
    mood_calibration = DictField(default=dict)   # {predicted: {actual: count}}
    taste_profile = DictField(default=dict)      # {alpha[22], beta[22], events}
    created_at = DateTimeField(default=datetime.utcnow)
    meta = {"collection": "user_profile", "auto_create_index": False, "indexes": ["username"]}
```

### 6.2 `backend/users/documents.py` — `User`

```python
class User(Document):
    username = StringField(required=True, unique=True)
    email = StringField(required=True, unique=True)
    password = StringField(required=True)  # PBKDF2 hash
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
```

---

## 7. Relevant APIs

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/text_emotion/` | POST | Optional | Text → emotion + recs (via Django→Modal) |
| `/api/v1/music_recommendation/` | POST | Optional | Emotion + history → recs (via Django→Modal, then bandit) |
| `/api/v1/feedback/` | POST | Required | Mood/track feedback |
| `/api/v1/feedback/tracks/` | GET | Required | Restore like/dislike UI state |
| `/api/v1/users/user/profile/` | GET | Required | Full profile (history, calibration, taste) |
| `/api/v1/users/mood_history/` | GET/POST/DELETE | Required | Mood history CRUD |
| `/api/v1/users/listening_history/` | GET/POST/DELETE | Required | Listening history CRUD |
| `/api/v1/users/recommendations/<id>/` | GET/DELETE | Required | Saved recommendations |

---

## 8. Relevant Frontend Components

| Component | Purpose |
|-----------|---------|
| `ResultsPage.js` | Main recommendation UI: mood picker, genre, market, sort, track cards with 👍/👎/Open |
| `TrackRow` (in ResultsPage) | Individual track card with vote buttons, preview player, Deezer link |
| `Profile.js` | User profile: stats, mood history chips, saved tracks, listening history, settings |
| `Recommendations.js` | Simpler recommendation display (used in Profile) |
| `MoodFeedbackWidget.jsx` | Mood correction UI (shown on ResultsPage for text/speech/face inputs) |
| `services/recommend.js` | Routes to Django (authed) or Modal (anon) |
| `services/feedback.js` | `sendTrackFeedback`, `sendMoodFeedback`, `getTrackFeedbackState` |

---

## 9. Relevant Tests

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `backend/tests/test_bandit.py` | 11 | Posterior update, rerank, cold start |
| `backend/tests/test_feedback.py` | ~30 | Feedback endpoint, store, calibration, revert, clear |
| `backend/tests/test_calibration.py` | 10 | Calibration threshold logic |
| `backend/tests/test_track_features.py` | 15 | Feature extraction buckets |
| `backend/tests/test_personalisation_views.py` | 12 | Calibration + bandit integration in views |
| `ai_ml/tests/test_bandit.py` | 16 | (Duplicate of backend — legacy) |
| `ai_ml/tests/test_personalized_recommendation.py` | 25 | (Duplicate — legacy) |
| `modal_inference/tests/test_personalization.py` | 18 | Modal's EWMA/Markov/blend |
| `modal_inference/tests/test_recommendation.py` | 15 | Deezer mocks, fallback |

---

## 10. KEEP / MODIFY / REFACTOR / NEW Map

| Component | Decision | Reason |
|-----------|----------|--------|
| **Modal Inference Service** | | |
| `modal_inference/recommendation/music_recommendation.py` | MODIFY | Extract candidate generation; keep Deezer search, history blend, quality rank, fallback |
| `modal_inference/recommendation/personalization.py` | MODIFY | Keep `rank_by_quality`, `interleave`, `mood_affinity`, `recurring_mood`, `blend_ratio` as reusable utilities |
| `modal_inference/recommendation/deezer.py` | KEEP | Deezer client with caching — works well |
| `modal_inference/inference/` | KEEP | Emotion models unchanged |
| **Backend API** | | |
| `backend/api/bandit.py` | KEEP | Core Thompson Sampling is solid; integrate into new pipeline |
| `backend/api/calibration.py` | KEEP | Mood calibration works; integrate into new pipeline |
| `backend/api/track_features.py` | MODIFY | Extend feature vector for genre/artist if feasible; keep 22-dim base |
| `backend/api/models.py` | MODIFY | Extend `UserProfile` with explicit preference fields |
| `backend/api/feedback_views.py` | MODIFY | Wire feedback → extended preference profile (not just bandit) |
| `backend/api/feedback_store.py` | KEEP | Time-series persistence works |
| `backend/api/views.py` | REFACTOR | Split into pipeline stages; delegate to new recommendation service |
| **Frontend** | | |
| `frontend/src/pages/ResultsPage.js` | MODIFY | Add "Why this song?" explanation display |
| `frontend/src/components/Profile/Profile.js` | MODIFY | Add personalization dashboard section |
| `frontend/src/services/recommend.js` | KEEP | Routing logic fine |
| `frontend/src/services/feedback.js` | KEEP | Feedback submission fine |
| **New Components (Phase 2)** | | |
| `backend/api/recommendation_pipeline.py` | NEW | Orchestrates candidate_gen → base_rank → mood → personalization → bandit → diversity → explanation |
| `backend/api/candidate_generation.py` | NEW | Separates "which tracks" from "which rank" |
| `backend/api/base_ranking.py` | NEW | Deterministic baseline scoring |
| `backend/api/personalization.py` | NEW | Explicit preference profile + update logic |
| `backend/api/diversity.py` | NEW | Diversity re-ranking layer |
| `backend/api/explanations.py` | NEW | Truthful explanation generation from ranking signals |
| `backend/api/preference_profile.py` | NEW | Extended UserProfile schema + update mechanics |
| Frontend personalization dashboard | NEW | Profile page extension showing learned preferences |
| Frontend explanation UI | NEW | "Why this song?" tooltip/expansion on track cards |

---

## 11. Proposed Phase 2 Recommendation Architecture

```
Request (emotion, user_id?, history?, genre?)
         ↓
┌─────────────────────────────────────────────────────────┐
│ CANDIDATE GENERATION                                     │
│  • Mood-compatible (Deezer search)                      │
│  • Genre-compatible (if genre specified)                │
│  • History-compatible (recurring mood tracks)           │
│  • Exploration candidates (popular, diverse)            │
│  • Deduplicate by track_id                              │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ BASE RANKING (deterministic, explainable)               │
│  • Mood similarity (query match strength)               │
│  • Track quality (curated rank + popularity blend)      │
│  • Contextual relevance (duration, recency)             │
│  → score ∈ [0, 1], sortable                             │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ MOOD / CONTEXT SCORING                                  │
│  • Current emotion match (from candidate gen query)     │
│  • Recurring mood affinity (EWMA + Markov)              │
│  • Genre preference match (if genre specified)          │
│  → multiplicative or additive adjustment to base score  │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ PERSONALIZATION (explicit preferences)                  │
│  • UserPreferenceProfile: genre, artist, era, mood weights│
│  • Score boost for preferred genres/artists/eras        │
│  • Score penalty for disliked categories                │
│  • Cold-start: neutral (no boost/penalty)               │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ THOMPSON SAMPLING (existing bandit)                     │
│  • Posterior over 22-dim features                       │
│  • One sample per axis → dot product with track features│
│  • Reorders; identity when events < 20                  │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ DIVERSITY RE-RANKING                                    │
│  • MMR (Maximal Marginal Relevance) or greedy diverse   │
│  • Diversity dimensions: artist, genre, era             │
│  • Configurable diversity strength                      │
│  • Preserves top-k relevance                            │
└─────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────┐
│ EXPLANATION GENERATION                                  │
│  • Input: ranking signals that fired for each track     │
│  • Output: human-readable reason string                 │
│  • Template-based, no LLM                               │
│  • Signals: mood_match, genre_pref, artist_pref,        │
│             era_pref, exploration, diversity            │
└─────────────────────────────────────────────────────────┘
         ↓
Final Recommendations (with explanations)
```

---

## 12. Data Model Changes

### 12.1 Extended `UserProfile` (in `backend/api/models.py`)

```python
class UserProfile(Document):
    # Existing fields (KEEP)
    username = StringField(required=True)
    mood_history = ListField(StringField())
    listening_history = ListField()
    recommendations = ListField(DictField())
    mood_calibration = DictField(default=dict)
    taste_profile = DictField(default=dict)  # bandit posterior
    created_at = DateTimeField(default=datetime.utcnow)
    
    # NEW: Explicit preference profile
    # Genre preferences: {genre: weight} where weight ∈ [-1, 1] or [0, 1]
    genre_preferences = DictField(default=dict)
    # Artist preferences: {artist_name: weight}
    artist_preferences = DictField(default=dict)
    # Era/decade preferences: {decade_bucket: weight}
    era_preferences = DictField(default=dict)
    # Mood preferences: {mood: weight}
    mood_preferences = DictField(default=dict)
    
    # Interaction counts for cold-start handling
    interaction_counts = DictField(default=dict)  # {signal: count}
    
    # Exploration preference (0.0 = exploit, 1.0 = explore)
    exploration_preference = FloatField(default=0.3)
    
    # Metadata
    last_updated = DateTimeField(default=datetime.utcnow)
    profile_version = IntField(default=2)  # for migration tracking
```

**Migration Strategy:**
- `profile_version` distinguishes old vs new profiles
- New fields default to empty dict / 0.3
- Backward compatible: code handles missing keys gracefully

### 12.2 Feedback Store Extensions

No schema changes needed — `track_feedback` already stores `features`, `context_emotion`, `signal`, `track_id`. The preference update logic reads from this.

---

## 13. Implementation Plan

### Phase 2A: Core Pipeline Infrastructure (Week 1-2)

1. **Create `backend/api/recommendation_pipeline.py`**
   - Pipeline orchestrator with clear stage interfaces
   - Each stage: `input → output`, testable in isolation
   - Configuration via Django settings

2. **Create `backend/api/candidate_generation.py`**
   - `generate_candidates(emotion, history, genre, user_profile, limit=60)`
   - Sources: mood search, genre search, recurring mood, exploration
   - Deduplication by `track_id` (Deezer ID from external_url)

3. **Create `backend/api/base_ranking.py`**
   - `rank_candidates(candidates, emotion, context)`
   - Deterministic scoring: mood_match + quality + recency
   - Returns list of `(track, score, signal_dict)`

### Phase 2B: Personalization Layer (Week 2-3)

4. **Create `backend/api/preference_profile.py`**
   - `UserPreferenceProfile` dataclass / methods
   - `update_from_feedback(profile, track, signal, context_emotion)`
   - `update_from_listening(profile, track)`
   - Decay/forgetting for old preferences

5. **Create `backend/api/personalization.py`**
   - `apply_personalization(ranked_tracks, user_profile, context_emotion)`
   - Boosts for preferred genre/artist/era/mood
   - Penalties for disliked
   - Cold-start handling (neutral until min_interactions)

6. **Extend `UserProfile` model** with new preference fields
   - Add migration logic in `apps.py` or management command

### Phase 2C: Integration & Feedback Loop (Week 3-4)

7. **Modify `backend/api/feedback_views.py`**
   - After bandit update, also call `preference_profile.update_from_feedback()`
   - Save extended preferences to `UserProfile`

8. **Refactor `backend/api/views.py:music_recommendation()`**
   - Delegate to `recommendation_pipeline.run()`
   - Preserve existing API contract

9. **Integrate Thompson Sampling** (existing `bandit.rerank`)
   - Call after personalization, before diversity

### Phase 2D: Diversity & Explanations (Week 4-5)

10. **Create `backend/api/diversity.py`**
    - `diversify_recommendations(ranked_tracks, k=20, diversity_weight=0.3)`
    - MMR or greedy artist/genre/era diversity
    - Returns reordered list

11. **Create `backend/api/explanations.py`**
    - `generate_explanation(track, signals_fired)`
    - Template-based: "Recommended because you like {genre} and this matches your {mood} mood"
    - No hallucination — only signals that actually contributed

### Phase 2E: Frontend Integration (Week 5-6)

12. **Modify `ResultsPage.js` / `TrackRow`**
    - Add "Why this song?" button/tooltip showing explanation
    - Display explanation inline or on hover

13. **Modify `Profile.js`**
    - Add "Your Music Profile" section
    - Show: favorite moods, genres, artists, eras, exploration level
    - Visual: chips, progress bars, or radar chart

### Phase 2F: Testing & Evaluation (Week 6-7)

14. **Write comprehensive tests** for each new module
15. **Integration test**: feedback → profile update → ranking change
16. **Baseline measurement** (see Section 16)
17. **Documentation** (architecture, adaptive loop, ownership)

---

## 14. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Backward compatibility** | Medium | High | Version API responses; keep existing endpoint contracts; feature flags |
| **Data consistency** | Medium | High | Transactional profile updates; idempotent feedback handling; tests for concurrent updates |
| **Ranking regressions** | Medium | High | A/B test infrastructure; shadow mode for new pipeline; comprehensive unit tests |
| **Frontend breaking changes** | Low | Medium | Incremental UI additions; no removal of existing features |
| **Test coverage gaps** | Medium | Medium | Write tests before implementation; CI gate on coverage |
| **Performance regression** | Low | Medium | Profile pipeline stages; avoid N+1 queries; cache candidate generation |
| **MongoDB schema migration** | Low | High | Use `profile_version`; default dicts; no required new fields |
| **Bandit integration issues** | Low | High | Preserve existing `bandit.py` exactly; wrap don't modify |
| **Modal ↔ Django contract drift** | Low | Medium | Define clear data contract; integration tests |

---

## 15. Baseline Measurement Plan

### 15.1 What to Measure (Pre-Phase 2)

| Metric | Method | Dataset |
|--------|--------|---------|
| **Recommendation relevance** | Offline: NDCG@10, Hit Rate@10 | Historical feedback logs (like/unlike) if sufficient; else synthetic eval set |
| **Recommendation latency** | p50, p95, p99 of `/music_recommendation/` | Load test (k6) against staging |
| **Diversity** | Unique artists@10, genre entropy@10 | Current production recommendations |
| **Like rate** | likes / recommendations shown | Real user data (if ≥1000 interactions) |
| **Skip rate** | unlikes + clears / recommendations shown | Real user data |
| **Cold-start quality** | Relevance for users with 0, 1-5, 5-20 events | Stratified eval |

### 15.2 Evaluation Dataset

- **Primary**: Offline evaluation set from logged feedback events (if available)
- **Fallback**: Synthetic user profiles with known preferences
- **Explicit labeling**: "This evaluation uses synthetic/offline data — not production A/B results"

### 15.3 Baseline Report Output

`PHASE_2_BASELINE.md` with:
- Measurement methodology
- Dataset description
- Metric values with confidence intervals
- Date/commit of measurement
- Comparison targets for Phase 2

---

## 16. Next Steps

**Awaiting approval to proceed with implementation.** The audit confirms:

1. ✅ Strong Phase 1 foundation exists
2. ✅ Thompson Sampling, calibration, feedback store are production-ready
3. ✅ Clear separation points for new pipeline stages
4. ✅ No fundamental rewrites needed — evolutionary improvement
5. ⚠️ Need to establish baseline before changes
6. ⚠️ Must preserve Moodify attribution in inherited code

**Key architectural decision:** Build the new pipeline in `backend/api/` alongside existing code, then switch `views.py` to delegate to it. This preserves rollback capability and enables shadow testing.

---

*Generated from repository inspection on 2026-09-05. All file paths and line counts verified against working tree.*