# VibeStream Phase 3 — Reliability Model Documentation

## 1. Reliability Goals

Phase 3 implements a reliability model that ensures VibeStream can handle real-world production concerns:

- **Availability**: System remains responsive despite partial failures
- **Consistency**: User data remains correct despite concurrent operations
- **Durability**: Events and feedback are never lost
- **Observability**: Full visibility into system behavior
- **Recoverability**: Graceful degradation and automatic recovery

---

## 2. Failure Domain Analysis

### 2.1 Component Failure Modes

| Component | Failure Modes | Detection | Mitigation |
|-----------|---------------|-----------|------------|
| **Django API** | Process crash, OOM, deadlock | Health endpoint, process monitor | Stateless, horizontal scaling, fast restart |
| **Redis** | Connection loss, OOM, network partition | Health endpoint, Redis INFO | Fail-open cache, fail-open rate limit |
| **MongoDB** | Connection loss, replica set failover | Health endpoint, driver retry | Silent fail (metrics/feedback), request continues |
| **Modal Inference** | Cold start, model OOM, timeout | Health endpoint, circuit breaker | Retry 3x → 502 with curated fallback |
| **Worker** | Process crash, event processing error | Dead letter queue, metrics | Event requeue, dead letter, alert |

### 2.2 Network Failure Modes

| Path | Failure | Handling |
|------|---------|----------|
| Client → Django | Timeout, 5xx, connection reset | Client retry (idempotent) |
| Django → Redis | Connection refused, timeout | Fail-open (cache miss, rate limit allow) |
| Django → MongoDB | Connection refused, timeout | Silent fail (metrics/feedback), request continues |
| Django → Modal | Timeout, 5xx, network error | Retry 3x → 502 with curated fallback |
| Client → Modal (speech/facial) | Timeout, upload error | Client retry, Modal handles |

---

## 3. Consistency Model

### 3.1 Eventual Consistency (Feedback Loop)

```
Feedback Request
    ↓
202 Accepted (event enqueued)
    ↓
Worker processes (async, ~10-100ms)
    ├── MongoDB time-series insert
    ├── Bandit posterior update
    ├── Calibration map update
    ├── Preference profile update
    └── Redis cache invalidation
    ↓
Next Recommendation Request
    ↓
Cache miss → Full pipeline with updated preferences
    ↓
Personalized Results
```

**Consistency Window**: ~10-100ms (worker processing time)

**User Experience**: 
- Immediate UI feedback (optimistic update)
- Next recommendation reflects feedback
- No stale reads due to cache invalidation

### 3.2 Strong Consistency (User Profile)

| Operation | Consistency | Mechanism |
|-----------|-------------|-----------|
| Profile Read | Strong | MongoDB read |
| Profile Update | Strong | MongoDB write + cache invalidation |
| Bandit Update | Strong | MongoDB write (single document) |
| Calibration Map | Strong | MongoDB write (single document) |
| Preference Update | Strong | MongoDB write (single document) |

**All user profile operations are strongly consistent** within a single MongoDB document.

### 3.3 Cache Consistency

| Cache | Consistency Model | Invalidation |
|-------|-------------------|--------------|
| Recommendation | Eventual (10min TTL) | Explicit on feedback |
| Idempotency | Strong (Redis SETNX) | TTL expiry |
| Rate Limit | Eventual (sliding window) | TTL expiry |

**Cache Invalidation Trigger**: Every feedback event for a user invalidates `rec:{user_id}:*` keys.

---

## 4. Idempotency Guarantees

### 4.1 Idempotency Key Contract

| Property | Guarantee |
|----------|-----------|
| **Scope** | Per-user (`idem:{user_id}:{key}`) |
| **TTL** | 24 hours |
| **Storage** | Redis SETNX (atomic) |
| **Cached** | Response body + status (2xx only) |
| **Replay** | Returns cached response with `X-Idempotency-Replay: true` |

### 4.2 Idempotency Guarantees by Endpoint

| Endpoint | Idempotent? | Key Source |
|----------|-------------|------------|
| `POST /feedback/` | Yes | Client-provided header |
| `POST /music_recommendation/` | No (read-only) | N/A |
| `POST /text_emotion/` | No (read-only) | N/A |
| `POST /users/login/` | Yes (token rotation) | Client-provided |

### 4.2 Duplicate Request Handling

| Scenario | Behavior |
|----------|----------|
| Same key, same request | Return cached 202 with `X-Idempotency-Replay: true` |
| Same key, different request | Reject 409 (key conflict) |
| No key | Process normally (no deduplication) |
| Key expired | Process as new request |

---

## 5. Retry & Failure Handling

### 5.1 Retry Policies by Operation

```python
MODAL_RETRY = RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=10.0)
MONGODB_RETRY = RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=5.0)
REDIS_RETRY = RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=1.0)
```

### 5.2 Retry Exhaustion Handling

| Operation | Exhaustion Behavior |
|-----------|---------------------|
| Modal API | Return 502, log error, curated fallback |
| MongoDB Write | Log error, continue request (silent fail) |
| Redis Write | Fail-open (cache miss, rate limit allow) |
| Worker Event | Requeue (max 3x) → Dead Letter Queue |

### 5.3 Dead Letter Queue

- **Location**: Redis list `vibestream:events:dead_letter`
- **Content**: Full event + failure reason + timestamp
- **Retention**: Manual cleanup / alerting
- **Replay**: Manual via admin tool

---

## 6. Data Durability

### 6.1 Write Paths

| Data | Durability | Replication |
|------|------------|-------------|
| User Profile | Strong (MongoDB write) | MongoDB Replica Set |
| Mood Feedback | Strong (time-series) | MongoDB Replica Set |
| Track Feedback | Strong (time-series) | MongoDB Replica Set |
| Metrics | Best-effort | MongoDB Replica Set |
| Events (Queue) | In-memory (Redis) | Redis persistence (AOF) |
| Cache | Ephemeral | Redis persistence (RDB/AOF) |

### 6.2 Recovery Scenarios

| Scenario | Recovery |
|-----------|----------|
| Django restart | Stateless, immediate |
| Redis restart | Events persist (AOF), cache rebuilt |
| MongoDB failover | Driver auto-reconnect, retry |
| Worker restart | Events re-processed from queue |
| Modal cold start | 1-2s with memory snapshots |

---

## 6. Capacity & Scaling

### 6.1 Current Limits

| Resource | Limit | Headroom |
|----------|-------|----------|
| Django workers | Vercel auto-scale | 1000+ req/s |
| Redis connections | 1000 | 90% headroom |
| MongoDB connections | 100 | 90% headroom |
| Modal containers | 5 (MAX_CONTAINERS) | Cost ceiling |
| Worker processes | 1 (dev) / N (prod) | Horizontal scaling |

### 6.2 Scaling Triggers

| Metric | Threshold | Action |
|--------|-----------|--------|
| Django CPU | >70% | Vercel auto-scale |
| Redis memory | >80% | Alert, increase instance |
| MongoDB connections | >80 | Alert, increase pool |
| Worker queue depth | >100 | Scale worker processes |
| Modal containers | >4 | Alert, check traffic |

---

## 7. Monitoring & Alerting

### 7.1 Key Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| API p99 latency | <2s | >2s for 5min |
| Error rate | <1% | >1% for 5min |
| Redis hit rate | >80% | <50% for 10min |
| Worker queue depth | <10 | >100 for 5min |
| Modal error rate | <1% | >5% for 5min |

### 7.2 Health Checks

| Probe | Endpoint | Frequency | Timeout |
|-------|----------|-----------|---------|
| Liveness | `/api/v1/health/live/` | 10s | 2s |
| Readiness | `/api/v1/health/ready/` | 30s | 5s |
| Deep | `/api/v1/health/detail/` | Manual | 10s |

---

## 7. Disaster Recovery

| Scenario | RTO | RPO | Procedure |
|----------|-----|-----|-----------|
| Django restart | 30s | 0 | Vercel auto-restart |
| Redis restart | 60s | 0 (AOF) | Redis auto-restart |
| MongoDB failover | 30s | <1s | Atlas auto-failover |
| Worker crash | 30s | 0 | Process manager restart |
| Region outage | 15min | <1min | DNS failover to standby |

---

## 7. Testing Reliability

### 6.1 Chaos Tests

| Test | Scenario | Expected |
|------|----------|----------|
| Redis down | Kill Redis | Cache miss, rate limit allow, requests succeed |
| MongoDB down | Kill MongoDB | Silent fail (metrics/feedback), requests succeed |
| Modal timeout | Delay Modal 10s | 3 retries → 502 with fallback |
| Worker crash | Kill worker | Events requeued on restart |
| Duplicate request | Same idempotency key | 202 replay, no duplicate effects |

### 6.2 Load Testing

| Test | Target | Pass Criteria |
|------|--------|---------------|
| Steady state | 100 req/s for 10min | p99 < 2s, error rate < 0.1% |
| Burst | 500 req/s for 1min | No 5xx, p99 < 3s |
| Cache warmup | 1000 requests | Hit rate > 80% after 100 |

---

## 7. Runbooks

### 6.1 Redis Down

**Symptoms**: Cache misses spike, rate limit headers missing, worker queue stalls

**Actions**:
1. Check Redis health endpoint
2. Check Redis memory/CPU
3. Failover to replica (if clustered)
4. Monitor cache hit rate recovery

### 6.2 Worker Queue Backlog

**Symptoms**: Queue depth > 100, feedback not reflected in recommendations

**Actions**:
1. Check worker process health
2. Scale worker processes horizontally
3. Check dead letter queue
4. Manual replay if needed

### 6.3 Modal Timeout Spike

**Symptoms**: 502 errors increase, fallback recommendations served

**Actions**:
1. Check Modal dashboard for container health
2. Check Modal cold start metrics
3. Consider increasing MAX_CONTAINERS
4. Alert Modal support if persistent

---

*Generated: 2026-09-05 | Phase 3 Reliability Model v1.0*