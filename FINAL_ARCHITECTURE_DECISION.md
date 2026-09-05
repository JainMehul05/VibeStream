# VibeStream — Final Architecture Decision

**Date:** 2026-09-05  
**Status:** APPROVED WITH TARGETED CHANGES (Option B)

---

## KEEP

The following components are correct, integrated, and should remain unchanged:

### Core Architecture
- **Django API Gateway** — Auth, orchestration, persistence, GenAI tool layer
- **Modal Inference Service** — ML models (text/speech/facial), Deezer recommendations, personalization (EWMA+Markov)
- **MongoDB Atlas** — UserProfile, User, time-series feedback, metrics
- **Redis** — Recommendation cache, idempotency keys, event queue, dead letter queue
- **Background Worker** — Async event processing (when deployed separately)

### Recommendation Pipeline (8 Stages)
1. **Candidate Generation** — Modal/Deezer search + history blend + fallback (60 tracks)
2. **Base Ranking** — Normalized scores [0,1], preserves Modal order
3. **Mood/Context** — Signal extraction for explanations
4. **Personalization** — Explicit prefs (genre/artist/era/mood), cold-start guard (5 interactions), decay (0.995)
5. **Thompson Sampling** — Beta-Bernoulli (22 dims), cold-start guard (20 events), correct sampling
6. **Diversity (MMR)** — λ=0.3, artist/era dimensions, after bandit
7. **Explanations** — Truthful, signal-based only, no hallucination
8. **Final Truncation** — Top-20

### Feedback & Learning
- **Dual Feedback Surfaces** — Mood correction + Track signals (like/unlike/open_deezer/clear)
- **Event-Driven Processing** — Structured events, Redis queue, retry (3x), DLQ
- **Calibration** — Per-user mood correction map (predicted → actual counts)
- **Bandit Posterior** — Persisted in UserProfile.taste_profile
- **Preference Profile** — Explicit weights [-1,1], updated from feedback

### Security & Auth
- **JWT (HS256)** — 7d access / 14d refresh, shared key with Modal
- **WebAuthn/Passkeys** — RP ID = frontend origin, challenge TTL 300s
- **User Isolation** — Ownership checks on all profile endpoints
- **Rate Limiting** — DRF (anon 60/min, user 240/min) + Modal tiered limits

### GenAI Assistant
- **Structured Intent Extraction** — LLM → JSON → Pydantic validation
- **5 Validated Tools** — recommend_music, get_preferences, get_explanation, submit_feedback, get_profile
- **Auth Enforcement** — Tools require user JWT, call Django API
- **Classification** — GenAI-powered assistant with structured tool calling (NOT Agentic AI)

### Observability & Reliability
- **Structured Logging** — JSON, correlation IDs, request IDs
- **Health Checks** — Liveness / Readiness / Detail (with dependency checks)
- **Metrics** — Live (in-process) + Persisted (Mongo time-series), percentiles, error rates
- **Retry Policies** — Exponential backoff + jitter, classified exceptions, predefined policies

### Evaluation & Quality
- **Ablation Framework** — Base → +Personalization → +Bandit → +Diversity → Full
- **Cold-Start Evaluation** — 4 buckets (0, 1-5, 5-20, 20+ interactions)
- **Synthetic Dataset** — 200 users, 1000 tracks, reproducible (seed=42)
- **Metrics** — NDCG@10, HitRate@10, Precision@10, MRR, Diversity (entropy)

### Infrastructure & DevOps
- **CI/CD** — Multi-job (format, backend, modal, ai_ml, frontend, coverage, docker, deploy)
- **Security Workflows** — SAST, dependency scanning, secrets detection
- **Infrastructure as Code** — Terraform, Helm, Kubernetes, docker-compose
- **Multi-Cloud Ready** — AWS, GCP, Azure, Oracle configurations

---

## MODIFY

Targeted changes required before production deployment:

### 1. MANDATORY: Fix Async Feedback Processing
**File:** `backend/api/feedback_views.py:279-288`

**Current Problem:** API processes feedback synchronously, blocking the request. Worker exists but not wired in.

```python
# CURRENT (sync - blocks request)
from .events import process_feedback_track, process_feedback_mood
redis_client = cache._cache.get_client(write=True)
if event.type == EventType.FEEDBACK_MOOD:
    process_feedback_mood(event, redis_client)
else:
    process_feedback_track(event, redis_client)
```

**Required Change:** Enqueue only, return 202 immediately.
```python
# FIXED (async - non-blocking)
from .events import enqueue_event
redis_client = cache._cache.get_client(write=True)
enqueue_event(redis_client, event)
```

**Deploy Worker Separately:** Run `python -m api.worker` as background service (Render worker, K8s Deployment, or Modal function).

**Impact:** Eliminates 50-100ms blocking on feedback; enables true async architecture.
**Risk:** Low — worker code already tested and functional.
**Mandatory:** **YES**

---

### 2. MANDATORY: Replace Redis KEYS with SCAN
**File:** `backend/api/cache.py:116` and `backend/api/events.py:347`

**Current Problem:** `KEYS` command blocks Redis single-threaded event loop at scale.

```python
# CURRENT (blocks Redis)
keys = client.keys(pattern)
if keys:
    deleted = client.delete(*keys)
```

**Required Change:** Use SCAN iterator.
```python
# FIXED (non-blocking)
deleted = 0
cursor = 0
while True:
    cursor, keys = client.scan(cursor, match=pattern, count=100)
    if keys:
        deleted += client.delete(*keys)
    if cursor == 0:
        break
```

**Impact:** Prevents Redis latency spikes during cache invalidation under load.
**Risk:** Low — standard Redis pattern.
**Mandatory:** **YES**

---

### 3. RECOMMENDED: Remove Double Popularity Weighting
**File:** `backend/api/base_ranking.py:66`

**Current Problem:** Modal already applies popularity weight (0.2) in `personalization.rank_by_quality()`. Django re-applies it.

```python
# CURRENT (double weighting)
base_score = (1.0 - _POPULARITY_WEIGHT) * curated_score + _POPULARITY_WEIGHT * pop_norm
```

**Recommended Change:** Trust Modal's ranking; only normalize position.
```python
# RECOMMENDED
base_score = curated_score  # Modal already blended popularity
```

**Impact:** Slightly cleaner score semantics; no behavioral change expected.
**Risk:** Very low.
**Mandatory:** No (minor)

---

### 4. REFACTOR: Consolidate Duplicated Feedback Processing Logic
**Files:** `backend/api/events.py` and `backend/api/worker.py`

**Current Problem:** 6 functions duplicated identically:
- `_bump_calibration`
- `_featurize`
- `_apply_posterior`
- `_revert_posterior`
- `_update_preferences`
- `_invalidate_user_cache`

**Recommended Change:** Extract to `backend/api/feedback_processing.py`, import in both.

**Impact:** Eliminates drift risk, single source of truth.
**Risk:** Low (pure refactor).
**Mandatory:** No (technical debt)

---

### 5. CLEANUP: Fix datetime.utcnow() Deprecation
**Files:** Multiple (preference_profile.py:128, passkey_views.py, documents.py)

**Change:** `datetime.utcnow()` → `datetime.now(timezone.utc)`

**Impact:** Eliminates deprecation warnings in Python 3.12+.
**Risk:** None.
**Mandatory:** No (cosmetic)

---

### 6. DOCUMENT: Genre Diversity Limitation
**File:** `backend/api/recommendation_pipeline.py:298`

**Current Problem:** Genre diversity dimension always empty (Deezer doesn't provide genre).

**Action:** Add comment documenting limitation; consider Last.fm/MusicBrainz integration post-launch.

**Mandatory:** No (documentation)

---

## REMOVE / CONSOLIDATE

Items that are genuinely redundant or harmful:

### 1. Test Shim in Production Code
**File:** `backend/api/views.py:40-42`

```python
def modal_music(emotion, market=None, history=None, genre=None):  # noqa: ARG001
    """Test shim -- not used in production."""
    return {"emotion": emotion, "market": market, "recommendations": []}
```

**Action:** Remove or move to `conftest.py` / test fixtures.

---

### 2. Frontend PageBackground WebGL Detection
**File:** `frontend/src/components/PageBackground.jsx:43-45`

**Problem:** Causes 5 snapshot test failures in jsdom (no WebGL implementation).

**Action:** Add graceful fallback for test environment or mock `HTMLCanvasElement.prototype.getContext` in test setup.

---

## Summary

| Category | Count | Mandatory Before Deploy |
|----------|-------|------------------------|
| **KEEP** | 16 major components | — |
| **MODIFY** | 6 items | 2 (async feedback, Redis KEYS) |
| **REMOVE** | 2 items | 0 |

**Final Verdict:** Architecture is **approved for production** after the 2 mandatory fixes. No structural changes needed.