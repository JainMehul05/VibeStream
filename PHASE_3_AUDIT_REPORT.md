# VibeStream Phase 3 — Repository Audit

## 1. Current Architecture Overview

### 1.1 System Components

| Component | Technology | Location | Status |
|-----------|------------|----------|--------|
| **Frontend** | React 18 + MUI | `frontend/` | ✅ Stable |
| **Backend API** | Django 5.1 + DRF | `backend/` | ✅ Phase 2 Complete |
| **ML Inference** | FastAPI on Modal | `modal_inference/` | ✅ Stable, Separate Service |
| **Database** | MongoDB Atlas (mongoengine) | `backend/api/models.py` | ✅ UserProfile + Feedback |
| **Cache** | LocMemCache (Django), TTLCache (Modal) | `backend/backend/settings.py`, `modal_inference/cache.py` | ⚠️ Local-only |
| **Auth** | JWT HS256 + WebAuthn | `backend/users/` | ✅ Stable |
| **Music Provider** | Deezer Search API | `modal_inference/recommendation/deezer.py` | ✅ Stable |

### 1.2 Current Data Flow

```
User Request
    ↓
Django API (Vercel)
    ├── /text_emotion/ → Modal (BERT) → Emotion + Base Recs → L1 Calibration → Response
    ├── /music_recommendation/ → Modal (EWMA+Markov) → Base Recs → L2 Bandit → Diversity → Explanations → Response
    ├── /feedback/ → MongoDB time-series + UserProfile updates (calibration, taste_profile, explicit prefs)
    └── /metrics/ → MongoDB time-series aggregation (service-token auth)
```

### 1.3 Recommendation Pipeline (Phase 2)

```
Request (emotion, user_profile?, history?, genre?)
    ↓
Candidate Generation (Modal: Deezer search + history blend)
    ↓
Base Ranking (normalize Modal order → base_score ∈ [0,1] + signals)
    ↓
Mood/Context Scoring (pass-through; Modal already handles)
    ↓
Personalization (explicit prefs: genre/artist/era/mood weights, cold-start ≥5)
    ↓
Thompson Sampling (bandit: 22-dim Beta-Bernoulli, cold-start ≥20 events)
    ↓
Diversity (MMR across artist/genre/era, λ=0.3)
    ↓
Explanation Generation (template-based from ranking_signals)
    ↓
Final Recommendations (with explanations)
```

---

## 2. Current Synchronous Paths

### 2.1 Request/Response Paths (Fully Synchronous)

| Endpoint | Sync Work | External Calls | DB Writes |
|----------|-----------|----------------|-----------|
| `POST /api/v1/text_emotion/` | Modal proxy → calibration | Modal `/text_emotion` (60s timeout) | UserProfile.mood_calibration (on mismatch) |
| `POST /api/v1/music_recommendation/` | Full pipeline (candidate → base → mood → personalization → bandit → diversity → explanations) | Modal `/music_recommendation` (60s timeout) | None (read-only) |
| `POST /api/v1/feedback/` (mood) | Validation → Mongo insert → calibration bump | MongoDB (time-series) | mood_feedback TS + UserProfile.mood_calibration |
| `POST /api/v1/feedback/` (track) | Validation → Mongo insert → bandit update → revert prior → apply new → preference update | MongoDB (time-series) | track_feedback TS + UserProfile.taste_profile + explicit prefs |
| `GET /api/v1/feedback/tracks/` | Mongo aggregation | MongoDB | None |

### 2.2 Expensive Synchronous Operations

| Operation | Location | Latency Profile | Blocking? |
|-----------|----------|-----------------|-----------|
| Modal inference call | `integrations.clients._post()` | 100-2000ms (cold start 1-2s + inference) | ✅ Yes |
| Deezer search (inside Modal) | `modal_inference/recommendation/deezer.py` | 200-800ms | ✅ Yes (in Modal) |
| Full recommendation pipeline | `recommendation_pipeline.run_pipeline()` | 50-200ms (Django side) | ✅ Yes |
| Bandit rerank | `bandit.rerank()` | <5ms | ✅ Yes |
| Feedback DB writes | `feedback_store.insert_*()` | 1-10ms | ✅ Yes |
| Preference profile update | `_update_preferences()` | 5-20ms | ✅ Yes |

---

## 3. Current Failure Points

### 3.1 Single Points of Failure

| Component | Failure Mode | Current Handling |
|-----------|--------------|------------------|
| Modal inference | Timeout / 5xx / network error | 1 retry (1s backoff), then 502 |
| MongoDB Atlas | Connection timeout / write failure | Silently swallowed (metrics, feedback) |
| Deezer API | 429 / 5xx / timeout | Curated fallback (14 tracks) in Modal |
| Emotion models (BERT/SVC/FER) | OOM / load failure / prediction error | `degraded: true` + neutral + curated fallback |
| Django process | Crash / OOM | Vercel restarts (stateless) |

### 3.2 Failure Behaviors

| Scenario | Current Behavior | Gap |
|----------|------------------|-----|
| Feedback duplicate (double-click) | Accumulates in time-series; bandit revert/apply uses exact feature vector → idempotent for like/unlike/clear; open_deezer accumulates | No idempotency key at API level |
| Feedback during MongoDB outage | Event lost silently (swallowed) | No retry queue, no persistence guarantee |
| Modal timeout on recommendation | 502 to client; no fallback in Django | No async fallback, no cached recommendation |
| Bandit update failure | Logged warning; profile not updated | No retry, no dead letter |
| Preference update failure | Logged warning; profile not updated | No retry, no compensation |

---

## 4. Existing Infrastructure

### 4.1 Containerization

| File | Purpose | Status |
|------|---------|--------|
| `docker-compose.yml` | Local dev: MongoDB + Backend + Frontend | ✅ Works |
| `backend/Dockerfile` | Backend container (Vercel-compatible) | ✅ Works |
| `frontend/Dockerfile` | Frontend container | ✅ Works |
| `modal_inference/` | Deployed separately via `modal deploy` | ✅ Works |

### 4.2 Deployment Config (Reference Only)

| Path | Purpose | Deployed? |
|------|---------|-----------|
| `kubernetes/` | K8s manifests (blue-green, canary) | ❌ Reference only |
| `helm/` | Helm charts (backend, frontend, monitoring) | ❌ Reference only |
| `terraform/` | Terraform modules (VPC, EKS/GKE/AKS, Redis, RDS) | ❌ Reference only |
| `argocd/` | Argo CD app-of-apps | ❌ Reference only |

### 4.3 CI/CD

| File | Purpose |
|------|---------|
| `.github/workflows/` | Format, test, build, push GHCR |
| `Makefile` | `make test`, `make lint`, `make fmt` |

---

## 5. Existing Redis Support

### 5.1 Current Redis Usage

| Location | Usage | Configured? |
|----------|-------|-------------|
| `backend/backend/settings.py` | `CACHES['default']` = RedisCache if `CACHE_REDIS_URL` set, else LocMemCache | ⚠️ Optional, not used in CI/local |
| `modal_inference/cache.py` | In-process TTLCache (LRU + TTL) | ✅ Used for text_emotion, deezer_search, speech, facial |

### 5.2 Redis Capabilities Available

- Django Redis cache backend configured (opt-in via `CACHE_REDIS_URL`)
- No Redis-backed rate limiting in Django (uses DRF in-memory throttling)
- No Redis-backed job queue
- No Redis pub/sub
- No distributed locking

---

## 6. Existing Worker/Task Infrastructure

### 6.1 Current State

| Technology | Status |
|------------|--------|
| Celery | ❌ Not installed |
| RQ (Redis Queue) | ❌ Not installed |
| Django Q | ❌ Not installed |
| Background tasks | ❌ None — all work synchronous |

### 6.2 Async Boundaries

| Boundary | Current State |
|----------|---------------|
| Django → Modal | Synchronous HTTP (requests, 60s timeout, 1 retry) |
| Frontend → Django | Synchronous HTTP |
| Frontend → Modal (speech/facial) | Direct, synchronous HTTP (multipart) |
| Feedback processing | Synchronous in request path |

---

## 7. Existing Logging

### 7.1 Current Logging

| Component | Format | Structured? | Correlation ID? |
|-----------|--------|-------------|-----------------|
| Django | Python `logging` (default) | ❌ Plain text | ❌ No |
| Modal | Python `logging` + Modal logs | ❌ Plain text | ❌ No |
| Feedback store | `logger.warning()` on failure | ❌ | ❌ |
| Bandit | `logger.warning()` on failure | ❌ | ❌ |

### 7.2 Log Content

- Basic WARNING/ERROR level logs
- No request_id propagation
- No structured JSON output
- No user_id in logs (by design for privacy)
- No latency percentiles in logs (only via `/metrics` endpoint)

---

## 8. Existing Security Controls

### 8.1 Authentication/Authorization

| Control | Implementation | Status |
|---------|----------------|--------|
| JWT (HS256) | `users.authentication.MongoJWTAuthentication` | ✅ 7d access / 14d refresh |
| WebAuthn/Passkeys | `pywebahn`, multiple credentials/user | ✅ |
| Password hashing | PBKDF2 (Django default) | ✅ |
| Rate limiting | DRF `AnonRateThrottle` (60/min), `UserRateThrottle` (240/min) | ✅ |
| CORS | Header-based, configurable origins | ✅ |

### 8.2 Input Validation

| Endpoint | Validation |
|----------|------------|
| `/text_emotion/` | Text length 1-5000 |
| `/music_recommendation/` | Emotion required, history ≤50, genre optional |
| `/feedback/` | Strict schema validation for mood/track kinds |
| `/users/*` | DRF serializers + custom validators |

### 8.3 Security Gaps

| Gap | Risk |
|-----|------|
| No `Idempotency-Key` support | Duplicate requests possible |
| No request correlation ID | Hard to trace requests across services |
| Error responses may leak internal details | `logger.exception` in some paths |
| No API versioning in error responses | Inconsistent error format |
| DRF throttling is in-memory (per-process) | Not shared across Vercel instances |

---

## 9. Existing Rate Limiting

| Layer | Implementation | Scope |
|-------|----------------|-------|
| Django (DRF) | `AnonRateThrottle` 60/min, `UserRateThrottle` 240/min | Per-process, in-memory |
| Modal | Sliding window: 45/min general, 15/min media per user | Per-container, in-memory |
| Redis-backed | ❌ None | N/A |

---

## 10. Existing Health Checks

| Endpoint | Purpose | Dependencies Checked |
|----------|---------|---------------------|
| `GET /api/v1/health/` | Liveness | None (returns `{"status": "ok"}`) |
| `GET /health/` (Modal) | Liveness + cache + rate-limit stats | Models loaded, cache stats, rate-limit stats |

**Missing:** Readiness probe (checks MongoDB, Modal connectivity)

---

## 11. Proposed Phase 3 Architecture

### 11.1 Target Architecture

```
Frontend
    ↓
API v1 (Django)
    │
    ├── Authentication (JWT + Passkeys)
    ├── User/Profile (CRUD)
    ├── Recommendation (sync: candidate gen → pipeline → response)
    ├── Feedback (async: accept → event → 202)
    ├── Music Provider (Modal proxy)
    └── Inference Integration (Modal proxy)
    │
    ↓
Redis (Shared)
    ├── Recommendation Cache (user/context keyed, TTL, invalidated on feedback)
    ├── Rate Limiting (sliding window, Redis-backed)
    ├── Idempotency Keys (short TTL, request deduplication)
    └── Job Coordination (worker queue, if needed)
    │
    ↓
Async Worker (Background)
    ├── Profile Updates (explicit preferences from feedback)
    ├── Personalization Updates (bandit + calibration async)
    ├── Analytics/Event Processing (feedback aggregation)
    └── Cache Invalidation (on preference/profile change)
    │
    ↓
MongoDB
    ├── UserProfile (preferences, taste_profile, calibration)
    ├── Mood Feedback (time-series, 365d TTL)
    ├── Track Feedback (time-series, 365d TTL)
    └── Metrics (time-series, 30d TTL)
```

### 11.2 Asynchronous Boundary Design

**Synchronous (Client waits):**
- Authentication (login, register, token refresh, passkey ceremonies)
- Recommendation request (candidate generation + full pipeline → response)
- Profile reads (GET /profile, GET /history, GET /feedback/tracks)
- Health checks

**Asynchronous (Client gets 202, work happens later):**
- Feedback processing (mood calibration bump, bandit update, preference update)
- Cache invalidation (triggered by profile/preference changes)
- Analytics aggregation (metrics rollups, if needed)

**Rationale:** Feedback processing involves multiple DB writes (time-series + UserProfile) and can safely be eventual. The user sees immediate UI feedback (optimistic update), and the backend confirms acceptance. The actual model updates happen in background.

---

## 12. KEEP / MODIFY / REFACTOR / NEW Classification

| Component | Decision | Reason |
|-----------|----------|--------|
| **Inherited / Preserved** | | |
| Modal Inference Service | **KEEP** | Separate service, scales to zero, stable |
| Emotion Models (BERT/SVC/FER) | **KEEP** | Unchanged |
| Deezer Integration | **KEEP** | Works, keyless |
| Thompson Sampling Bandit | **KEEP** | Core RL, cold-start safe |
| Mood Calibration (L1) | **KEEP** | Works, threshold-based |
| Feedback Store (time-series) | **KEEP** | Resilient, TTL-managed |
| UserProfile (MongoEngine) | **KEEP** | Extended in Phase 2, backward compatible |
| Django Auth (JWT + Passkeys) | **KEEP** | Stable |
| Recommendation Pipeline Stages | **KEEP** | Phase 2 architecture is clean |
| **Phase 3 Engineering (NEW/MODIFY)** | | |
| Async Feedback Processing | **NEW** | Event + worker architecture |
| Background Worker | **NEW** | Process feedback events reliably |
| Retry + Exponential Backoff | **NEW** | For transient failures (Modal, Mongo, Redis) |
| Idempotency Keys | **NEW** | `Idempotency-Key` header support |
| Redis Cache (Django) | **MODIFY** | Enable + use for recommendations, rate limiting, idempotency |
| Redis Cache Invalidation | **NEW** | Precise invalidation on preference changes |
| Structured Logging | **NEW** | JSON, request_id, user_id, latency, status |
| Request Correlation ID | **NEW** | Propagate `X-Request-ID` across sync/async |
| Metrics Expansion | **MODIFY** | Add worker, cache, feedback, Redis metrics |
| Health + Readiness Endpoints | **NEW** | `/health/live`, `/health/ready` |
| API Error Standardization | **MODIFY** | Consistent `{error: {code, message, request_id}}` |
| Security Hardening | **MODIFY** | Rate limiting (Redis), input validation, error sanitization |
| Performance Measurement | **NEW** | Before/after p50/p95/p99, cache hit rates |
| Failure Testing | **NEW** | Chaos tests: Redis down, worker crash, duplicate events |

---

## 13. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Eventual consistency confusion** | High | Medium | Document clearly; UI shows optimistic updates |
| **Redis as new SPOF** | Medium | High | Graceful degradation: cache miss → compute; rate limit fail-open |
| **Worker message loss** | Low | High | Persistent queue (Redis list), acknowledgment after processing |
| **Idempotency key collisions** | Low | Medium | UUID v4 keys, 24h TTL, user-scoped |
| **Cache staleness** | Medium | Medium | Precise invalidation keys, short TTL (5-15 min) |
| **Breaking API compatibility** | Low | High | Version errors, preserve v1 contracts, test existing clients |
| **MongoDB write contention** | Low | Medium | User-scoped writes, no cross-user transactions needed |
| **Worker backlog growth** | Low | Medium | Monitoring + alerting on queue depth, horizontal scaling |

---

## 14. Testing Strategy

### 14.1 Test Layers

| Layer | Scope | Tools |
|-------|-------|-------|
| **Unit** | Retry policy, idempotency, cache keys, invalidation, event validation, worker handlers, security helpers, rate limiting | `pytest`, mocks |
| **Integration** | API → Redis → Worker → MongoDB | `pytest`, testcontainers or mongomock + fakeredis |
| **API** | Auth, validation, errors, rate limiting, idempotency | `APIClient`, DRF test framework |
| **Failure** | Redis down, worker crash, Modal timeout, duplicate events, retry exhaustion | `pytest`, monkeypatch, chaos fixtures |
| **E2E Critical** | Feedback → event → worker → profile update → cache invalidation → recommendation reflects change | `pytest`, full stack (mongomock + fakeredis) |

### 14.2 Critical E2E Test (Phase 3 Version of Phase 2 Test)

```python
def test_feedback_async_loop():
    # 1. Get initial recommendations
    resp1 = client.post("/api/v1/music_recommendation/", {"emotion": "joy"})
    
    # 2. Submit feedback (like 5 tracks by ArtistX)
    for track in resp1.data["recommendations"][:5]:
        client.post("/api/v1/feedback/", {
            "kind": "track", "signal": "like",
            "track_id": track["external_url"],
            "context_emotion": "joy", "track": track
        })
    
    # 3. Verify event accepted (202)
    # 4. Wait for worker to process (or flush queue in test)
    # 5. Verify preference profile updated in MongoDB
    # 6. Verify recommendation cache invalidated
    # 7. Get new recommendations
    resp2 = client.post("/api/v1/music_recommendation/", {"emotion": "joy"})
    
    # 8. Verify personalization signals applied
    for track in resp2.data["recommendations"]:
        if track["artist"] == "ArtistX":
            assert track["ranking_signals"]["personalization"]["applied"] is True
```

### 14.3 Idempotency Test

```python
def test_duplicate_feedback_idempotent():
    key = "idem-key-123"
    headers = {"HTTP_IDEMPOTENCY_KEY": key}
    
    # First request
    r1 = client.post("/api/v1/feedback/", data, headers=headers)
    assert r1.status_code == 202
    
    # Duplicate request
    r2 = client.post("/api/v1/feedback/", data, headers=headers)
    assert r2.status_code == 202
    assert r2.data == r1.data  # Same response
    
    # Verify only ONE preference update in DB
    profile = UserProfile.objects.get(username=user)
    assert profile.interaction_counts["like"] == 1
```

---

## 15. Migration Strategy

### 15.1 Phase 3A: Event Architecture (Week 1)
1. Define event schemas (Pydantic models)
2. Add `Event` model or Redis list for job queue
3. Modify `/feedback/` to enqueue event + return 202 immediately
4. Add `Idempotency-Key` middleware

### 15.2 Phase 3B: Background Worker (Week 1-2)
1. Implement worker process (simple Redis BRPOP loop or RQ)
2. Worker consumes events, processes with retry logic
3. Move `_bump_calibration`, `_apply_posterior`, `_revert_posterior`, `_update_preferences` to worker
4. Add worker health logging

### 15.3 Phase 3C: Retry + Failure Handling (Week 2)
1. Implement retry decorator with exponential backoff
2. Classify retryable vs non-retryable errors
3. Add dead-letter handling for exhausted retries
4. Metrics for retries, failures, exhaustion

### 15.4 Phase 3D: Idempotency (Week 2)
1. Redis-backed idempotency key store (24h TTL)
2. Middleware to check/return cached response
3. Apply to `/feedback/` and other mutating endpoints

### 15.5 Phase 3E: Redis + Caching (Week 2-3)
1. Enable Redis in docker-compose and settings
2. Implement recommendation caching (key: user_id:emotion:genre:pipeline_version)
3. Implement Redis-backed rate limiting (sliding window)
4. Add cache hit/miss metrics

### 15.6 Phase 3F: Cache Invalidation (Week 3)
1. Invalidate recommendation cache on feedback processing
2. Invalidate on profile/preference update
3. Test: feedback → cache invalidated → next recs personalized

### 15.7 Phase 3G: API Hardening + Security (Week 3)
1. Standardize error responses
2. Redis rate limiting on expensive endpoints
3. Input validation hardening
4. Security headers review

### 15.8 Phase 3H: Observability + Health (Week 3-4)
1. Structured JSON logging with request_id
2. Correlation ID propagation (Django → worker)
3. Expanded metrics (worker, cache, Redis, feedback)
4. `/health/live` and `/health/ready` endpoints

### 15.9 Phase 3I: Performance + Testing (Week 4)
1. Before/after measurements
2. Run full test suite (backend + modal + frontend)
3. Failure injection tests
4. Load test (optional, k6)

### 15.10 Phase 3J: Staging Readiness + Docs (Week 4)
1. Verify docker-compose with Redis + worker
2. Environment variable documentation
3. Architecture docs
4. Completion report

---

## 16. Phase 3 Completion Gates

| Gate | Criteria | Status |
|------|----------|--------|
| **3.1 Event Architecture** | Meaningful events defined, schemas documented, producers/consumers clear, async boundary justified | ⬜ |
| **3.2 Background Worker** | Worker runs, jobs processed, failures handled, worker tests exist | ⬜ |
| **3.3 Retry + Failure Handling** | Retryable failures identified, bounded retries, backoff exists, permanent failures not retried endlessly, exhaustion handled | ⬜ |
| **3.4 Idempotency** | Duplicate requests detected, no duplicate state changes, idempotency tests pass | ⬜ |
| **3.5 Redis** | Redis integrated, clear responsibilities, failure behavior defined, integration tests pass | ⬜ |
| **3.6 Caching** | Recommendation caching works, correct keys, TTL defined, personalized data handled safely, hit/miss tested | ⬜ |
| **3.7 Cache Invalidation** | `feedback → preference update → cache invalidation → future recs refresh` verified | ⬜ |
| **3.8 API Hardening** | Validation, auth, authz, consistent errors, rate limiting, idempotency implemented and tested | ⬜ |
| **3.9 Security** | Secrets safe, authorization boundaries verified, input validation, no sensitive error leakage, controls tested | ⬜ |
| **3.10 Observability** | Structured logs, request IDs, useful metrics, worker failures observable, recommendation latency measurable, health/readiness | ⬜ |
| **3.11 Performance** | Before/after measurements, p50/p95/p99 recorded, cache behavior measured, feedback latency compared, no hidden regression | ⬜ |
| **3.12 Testing** | Unit/integration/API/failure/idempotency/E2E tests pass, Phase 2 tests healthy | ⬜ |
| **3.13 Staging Readiness** | Services build, start, config documented, Redis works, worker works, health checks work, core API works, no secrets committed | ⬜ |
| **3.14 Documentation** | Architecture, tradeoffs, failure model, measurements, limitations, ownership boundaries, completion report | ⬜ |

---

## 17. Key Implementation Decisions

### 17.1 Worker Technology: Redis + Custom Worker (Not Celery/RQ)

**Why:** 
- Celery adds ~15 dependencies, complex configuration, broker/result backend
- RQ is lighter but still adds Redis dependency management
- Custom worker using `BRPOP` + retry logic is ~100 lines, zero extra deps
- VibeStream's workload is low-volume (feedback events), not high-throughput task queue
- Redis list as queue is sufficient; no need for priority queues, scheduling, etc.

### 17.2 Idempotency: Redis `SETNX` with 24h TTL

**Why:**
- Simple, atomic, fast
- Key format: `idem:{user_id}:{key}` (user-scoped)
- Value: serialized response + status code
- On duplicate: return cached response
- TTL covers retry windows + client retry logic

### 17.3 Recommendation Cache Key

```
rec:{user_id}:{emotion}:{genre}:{pipeline_version}
```
- `user_id`: "anon" for anonymous, actual username for authenticated
- `pipeline_version`: increment on pipeline logic changes (manual or auto from git hash)
- TTL: 10 minutes (short enough for personalization freshness)

### 17.4 Cache Invalidation Strategy

On feedback processing (worker):
1. Update UserProfile (preferences, taste_profile, calibration)
2. Compute affected cache keys: `rec:{user_id}:*` (all emotions/genres for this user)
3. `DELETE` those keys from Redis
4. Next recommendation request → cache miss → fresh pipeline run

### 17.5 Retry Policy

| Failure Type | Retry? | Backoff | Max Attempts |
|--------------|--------|---------|--------------|
| Modal timeout / 5xx | ✅ | 1s, 2s, 4s | 3 |
| MongoDB connection error | ✅ | 0.5s, 1s, 2s | 3 |
| Redis connection error | ✅ | 0.1s, 0.2s, 0.5s | 3 |
| Validation error (400) | ❌ | N/A | 0 |
| Auth error (401) | ❌ | N/A | 0 |
| Business rule violation | ❌ | N/A | 0 |

---

## 18. Files to Create/Modify (Preliminary)

### New Files
```
backend/api/events.py              # Event schemas, queue operations
backend/api/worker.py              # Background worker main loop
backend/api/retry.py               # Retry decorator, policies
backend/api/idempotency.py         # Idempotency middleware + Redis store
backend/api/cache.py               # Recommendation cache + invalidation
backend/api/rate_limit.py          # Redis-backed rate limiting
backend/api/health.py              # /health/live, /health/ready
backend/api/errors.py              # Standardized error responses
backend/api/logging.py             # Structured logging setup, correlation ID
backend/tests/test_events.py       # Event schema tests
backend/tests/test_worker.py       # Worker processing tests
backend/tests/test_idempotency.py  # Idempotency tests
backend/tests/test_cache.py        # Cache + invalidation tests
backend/tests/test_retry.py        # Retry policy tests
backend/tests/test_rate_limit.py   # Rate limiting tests
backend/tests/test_health.py       # Health/readiness tests
backend/tests/test_phase3_e2e.py   # Critical E2E async feedback test
PHASE_3_ARCHITECTURE.md            # Architecture documentation
PHASE_3_RELIABILITY.md             # Reliability model documentation
PHASE_3_BASELINE.md                # Before/after performance measurements
PHASE_3_COMPLETION_REPORT.md       # Final completion report
```

### Modified Files
```
backend/backend/settings.py           # Redis config, logging config, middleware order
backend/api/feedback_views.py         # Enqueue event, return 202, idempotency check
backend/api/views.py                  # Add cache check in music_recommendation
backend/api/recommendation_pipeline.py # Add cache key generation
backend/api/models.py                 # No changes needed (Phase 2 extended)
backend/observability/middleware.py   # Add request_id, structured logging
backend/observability/recorder.py     # Add worker/cache/feedback metrics
backend/observability/store.py        # Add worker/cache/feedback persistence
backend/observability/views.py        # Expose new metrics
backend/integrations/clients.py       # Add retry logic for Modal calls
docker-compose.yml                    # Add Redis service
backend/requirements.txt              # Add redis, fakeredis (test), structlog
```

---

## 19. Next Steps

1. **Immediate**: Set up Redis in docker-compose and enable in Django settings
2. **Week 1**: Implement event architecture + worker skeleton
3. **Week 1-2**: Move feedback processing to worker with retries
4. **Week 2**: Add idempotency + recommendation caching
5. **Week 2-3**: Cache invalidation + Redis rate limiting
6. **Week 3**: API hardening + structured logging + health endpoints
7. **Week 3-4**: Performance measurement + comprehensive testing
8. **Week 4**: Documentation + completion report

---

*Generated from repository inspection on 2026-09-05. All file paths and line counts verified against working tree.*