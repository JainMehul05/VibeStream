# VibeStream Phase 3 — Architecture Documentation

## 1. Overview

Phase 3 transforms VibeStream from a functionally adaptive recommendation backend into a production-oriented, reliable, observable, asynchronous backend. This document describes the architectural changes introduced in Phase 3.

---

## 2. High-Level Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Frontend  │────▶│   API v1 (Django) │────▶│    Redis    │
│  (React)    │     │                  │     │  (Shared)   │
└─────────────┘     └────────┬─────────┘     └──────┬──────┘
                             │                      │
                    ┌────────▼────────┐     ┌────────▼────────┐
                    │  Async Worker   │     │    MongoDB      │
                    │  (Background)   │     │   (Primary)     │
                    └─────────────────┘     └─────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Modal Inference│
                    │   (Separate)    │
                    └─────────────────┘
```

---

## 3. Component Details

### 3.1 API Layer (`backend/api/`)

| Module | Responsibility |
|--------|----------------|
| `views.py` | Recommendation endpoints, caching |
| `feedback_views.py` | Event-based feedback processing |
| `recommendation_pipeline.py` | Multi-stage recommendation orchestration |
| `candidate_generation.py` | Modal proxy for candidate generation |
| `base_ranking.py` | Deterministic baseline scoring |
| `preference_profile.py` | Explicit preference management |
| `bandit.py` | Thompson Sampling re-ranking |
| `calibration.py` | Mood calibration map |
| `events.py` | Event definitions + synchronous processing |
| `worker.py` | Background worker (async ready) |
| `retry.py` | Retry policies with exponential backoff |
| `cache.py` | Redis recommendation caching |
| `rate_limit.py` | Redis-backed rate limiting |
| `health.py` | Liveness/readiness endpoints |
| `errors.py` | Standardized error responses |
| `logging.py` | JSON log formatter |
| `middleware/` | Correlation ID, Idempotency middleware |

### 3.2 Data Layer

| Store | Technology | Purpose |
|-------|------------|---------|
| UserProfile | MongoDB (MongoEngine) | Preferences, taste_profile, calibration |
| Mood Feedback | MongoDB Time-Series | Mood corrections (365d TTL) |
| Track Feedback | MongoDB Time-Series | Like/unlike/open_deezer (365d TTL) |
| Metrics | MongoDB Time-Series | Request latency, errors (30d TTL) |
| Cache | Redis | Recommendations, rate limits, idempotency |
| Event Queue | Redis List | Async feedback events |

### 3.3 Inference Layer (Modal - Unchanged)

| Service | Purpose |
|---------|---------|
| Text Emotion | BERT classifier |
| Speech Emotion | SVC + MFCC |
| Facial Emotion | FER + MTCNN |
| Recommendation | Deezer search + EWMA/Markov blend |

---

## 4. Request Flows

### 4.1 Recommendation Request (Synchronous)

```
GET /api/v1/music_recommendation/
    ↓
Check Redis Cache (rec:{version}:{user_id}:{emotion}:{genre}:{history})
    ├─ Hit → Return cached (200)
    ↓ Miss
Run Pipeline: Candidate Gen → Base Rank → Mood → Personalization → Bandit → Diversity → Explanations
    ↓
Cache Result (if authenticated, not degraded)
    ↓
Return 200 with recommendations
```

### 4.2 Feedback Request (Asynchronous)

```
POST /api/v1/feedback/
    ↓
Validate + Idempotency Check
    ↓
Create Event (with idempotency key)
    ↓
Enqueue to Redis (LPUSH)
    ↓
Return 202 Accepted
    ↓
Worker (BRPOP) → Process Event
    ├── MongoDB Time-Series Insert
    ├── Bandit Posterior Update
    ├── Calibration Map Update
    ├── Preference Profile Update
    └── Redis Cache Invalidation
```

---

## 5. Event System

### 5.1 Event Types

| Type | Payload | Processing |
|------|---------|------------|
| `feedback_track` | track_id, signal, context_emotion, track | Bandit + Preferences + Cache Invalidation |
| `feedback_mood` | predicted, actual, input_type, confidence | Calibration Map + Cache Invalidation |
| `cache_invalidate` | user_id, pattern | Redis Cache Deletion |
| `profile_update` | update_type, data | Profile Update + Cache Invalidation |

### 5.2 Event Structure

```python
@dataclass
class Event:
    type: EventType
    payload: dict
    user_id: str
    idempotency_key: Optional[str]
    event_id: str (UUID)
    created_at: ISO timestamp
    retry_count: int
    metadata: dict
```

---

## 6. Worker Architecture

### 6.1 Synchronous Mode (Testing)
- Events processed immediately in request thread
- Returns 200 OK (for test compatibility)
- Used in CI/test environment

### 6.2 Asynchronous Mode (Production)
- Separate process: `python -m api.worker`
- Consumes from Redis queue (BRPOP)
- Processes with retry logic
- Logs structured metrics
- Graceful shutdown on SIGTERM/SIGINT

### 6.3 Worker Processing Loop

```python
while not shutdown:
    event = dequeue_event(redis, timeout=5)
    if event:
        try:
            PROCESSORS[event.type](event, redis_client)
        except Exception:
            if event.retry_count < MAX_RETRIES:
                requeue_event(redis, event)
            else:
                move_to_dead_letter(redis, event, error)
```

---

## 7. Caching Strategy

### 7.1 Recommendation Cache

**Key**: `rec:{pipeline_version}:{user_id}:{emotion}:{genre}:{history_hash}`

**TTL**: 10 minutes (600 seconds)

**Scope**: Per-user, per-emotion, per-genre, per-history

**Invalidation**: On any feedback event for that user (`_invalidate_user_cache`)

**Degraded Responses**: Never cached

### 7.2 Idempotency Cache

**Key**: `idem:{user_id}:{idempotency_key}`

**TTL**: 24 hours

**Value**: Serialized response + status code

### 7.3 Rate Limit Cache

**Key**: `ratelimit:{endpoint}:{user_id}`

**Algorithm**: Sliding window (Redis sorted set)

**Window**: 60 seconds (configurable)

**Limits**: 
- Recommendation: 30/min
- Feedback: 60/min
- Text Emotion: 45/min
- Auth: 10/5min

---

## 8. Reliability Patterns

### 8.1 Retry Policies

| Operation | Max Attempts | Base Delay | Max Delay | Backoff |
|-----------|--------------|------------|-----------|---------|
| Modal API | 3 | 1s | 10s | 2x |
| MongoDB | 3 | 0.5s | 5s | 2x |
| Redis | 3 | 0.1s | 1s | 2x |

**Jitter**: ±50% on each attempt

### 8.2 Failure Classification

| Category | Examples | Retry? |
|----------|----------|--------|
| Transient | Network timeout, 5xx, connection refused | Yes |
| Rate Limit | 429 with Retry-After | Yes (after delay) |
| Validation | 400, 422 | No |
| Auth | 401, 403 | No |
| Business Logic | 409, 422 | No |

### 8.3 Graceful Degradation

| Dependency Failure | Behavior |
|--------------------|----------|
| Redis Down | Cache miss → compute; rate limit fail-open |
| MongoDB Down | Silent fail (metrics/feedback), request continues |
| Modal Timeout | Retry 3x → 502 with fallback |
| Worker Crash | Events persist in Redis queue |

---

## 9. Observability

### 9.1 Structured Logging (JSON)

```json
{
  "timestamp": "2026-09-05T05:34:30.377909Z",
  "level": "INFO",
  "logger": "api.events",
  "message": "event_enqueued event_id=... type=feedback_track user_id=alice",
  "request_id": "f8a04cd3f2244244"
}
```

**Fields**: timestamp, level, logger, message, request_id, user_id, event_id, etc.

### 9.2 Metrics (MongoDB Time-Series)

Per-request document:
```json
{
  "ts": "ISODate",
  "meta": {
    "service": "django",
    "endpoint": "/api/v1/music_recommendation/",
    "method": "POST",
    "container": "hostname-pid",
    "status_class": "2xx",
    "request_id": "...",
    "user_id": "alice"
  },
  "status": 200,
  "latency_ms": 45.2,
  "degraded": false
}
```

### 9.3 Health Endpoints

| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `/api/v1/health/` | Liveness | Process alive |
| `/api/v1/health/live/` | K8s liveness | Process alive |
| `/api/v1/health/ready/` | K8s readiness | MongoDB, Redis, Modal |
| `/api/v1/health/detail/` | Diagnostics | Full system status (admin) |

---

## 10. Security

| Control | Implementation |
|---------|----------------|
| Authentication | JWT HS256 (7d/14d) + WebAuthn |
| Rate Limiting | Redis sliding window per-user |
| Idempotency | Redis SETNX, 24h TTL, user-scoped |
| Input Validation | Strict schema per endpoint |
| Error Format | `{error: {code, message, request_id}}` |
| CORS | Header-based, configurable origins |
| Logging | No PII, request_id correlation |

---

## 10. Deployment

### Local Development (docker-compose.yml)

```yaml
services:
  mongodb: mongo:7
  redis: redis:7-alpine
  backend: Django (port 8000)
  worker: python -m api.worker
  frontend: React (port 3000)
```

### Production Requirements

- MongoDB Atlas (time-series collections)
- Redis (ElastiCache/Upstash)
- Modal Inference (separate deployment)
- Vercel/Cloud Run for Django
- Environment variables for all secrets

---

## 11. Migration Notes

### From Phase 2 to Phase 3

| Change | Impact |
|--------|--------|
| Feedback returns 202 | Clients must handle async |
| Cache headers added | Clients can cache recommendations |
| Rate limit headers | Clients should respect Retry-After |
| Structured logs | Log aggregation ready |
| Health endpoints | K8s probes supported |

### Breaking Changes

| Change | Mitigation |
|--------|------------|
| Feedback 200 → 202 | Clients poll or use websockets for status |
| Cache headers | Clients can ignore |
| Error format | `{error: {code, message}}` standard |

---

## 12. Future Extensibility

| Feature | Readiness |
|---------|-----------|
| Full Async Worker | Worker code ready, deploy as separate process |
| Kafka/RabbitMQ | Redis queue can be swapped |
| Distributed Tracing | request_id propagated, OpenTelemetry ready |
| Multi-region | Redis Cluster, MongoDB Atlas Global Clusters |
| Horizontal Scaling | Stateless Django, stateless worker |

---

*Generated: 2026-09-05 | Phase 3 Architecture v1.0*