# Kafka Evaluation for VibeStream

**Date:** 2026-09-05  
**Status:** NOT ADOPTED — Current Architecture Sufficient

---

## Executive Summary

After evaluating Kafka against VibeStream's current event architecture, **Kafka is NOT adopted**. The existing Redis-backed event queue with a dedicated worker process meets all current requirements with lower operational complexity.

---

## Current Event Architecture

```
POST /api/v1/feedback/
        │
        ▼
Create Event (FEEDBACK_TRACK / FEEDBACK_MOOD)
        │
        ▼
Redis LPUSH → vibestream:events:queue
        │
        ▼
Background Worker (api/worker.py)
        │
        ├── BRPOP (blocking, 5s timeout)
        ├── Process Event
        │   ├── Update UserProfile (calibration, taste_profile, preferences)
        │   ├── Persist to MongoDB time-series collections
        │   └── Invalidate Redis recommendation cache
        ├── Retry (max 3) → Requeue
        └── DLQ (max retries exceeded) → vibestream:events:dead_letter
```

### Current Capabilities
- ✅ Durable event persistence (Redis LIST + MongoDB time-series)
- ✅ At-least-once delivery (worker requeue on failure)
- ✅ Dead letter queue for poison messages
- ✅ Idempotency via `Idempotency-Key` header (API level)
- ✅ Retry with exponential backoff (3 attempts)
- ✅ Consumer scaling (run multiple worker processes)
- ✅ Event replay (MongoDB time-series collections)
- ✅ Ordering per user (single-threaded worker per queue)

---

## Kafka Comparison

| Criterion | Current (Redis + Worker) | Kafka | Winner |
|-----------|--------------------------|-------|--------|
| **Durability** | Redis LIST (in-memory, RDB/AOF) + MongoDB | Disk-backed, replicated | Kafka |
| **Throughput** | ~10K events/sec (single worker) | 100K+/sec per partition | Kafka |
| **Ordering** | Per-user (single queue) | Per-partition | Tie |
| **Replay** | MongoDB time-series | Native log retention | Kafka |
| **Multi-consumer** | Manual (multiple workers) | Consumer groups | Kafka |
| **Operations** | 1 Redis + 1 worker process | 3+ brokers, ZK/KRaft, monitoring | Current |
| **Local Dev** | `docker run redis` + `python worker.py` | Docker Compose (3+ services) | Current |
| **Cost** | 1 Redis instance | 3+ broker nodes | Current |
| **Latency** | ~1-5ms queue overhead | ~2-10ms broker overhead | Current |
| **Schema Registry** | Manual (Pydantic) | Confluent Schema Registry | Tie |

---

## When Kafka Would Be Justified

Kafka should be adopted **only if** one or more of these conditions are met:

1. **Multiple independent consumers** need the same events
   - e.g., Analytics service + Profile service + Notification service all need feedback events
   - Currently: only one consumer (worker) exists

2. **Event replay for new consumers** is a frequent requirement
   - e.g., New ML feature needs 6 months of historical feedback
   - Currently: MongoDB time-series serves this need

3. **Throughput exceeds 50K events/sec sustained**
   - Current: ~100 feedback events/sec peak
   - Projected: < 1K events/sec for 100K DAU

4. **Cross-region event streaming** required
   - Current: Single-region deployment

5. **Audit/compliance requires immutable event log**
   - Current: MongoDB time-series with TTL (365 days)

---

## Decision

**Kafka NOT ADOPTED** for the following reasons:

1. **No demonstrated need** — Current architecture handles all requirements
2. **Operational complexity** — Kafka adds 3+ services (brokers, KRaft, monitoring)
3. **Cost** — 3+ broker nodes vs 1 Redis instance
4. **Local development friction** — Kafka requires Docker Compose with 3+ services
5. **Team expertise** — Current team is proficient with Redis/worker pattern
6. **YAGNI** — No immediate requirement for multi-consumer or massive scale

### Redis Responsibilities (Retained)
- Recommendation cache (`rec:*`)
- Idempotency keys (`idem:{user}:{key}`)
- Rate limiting (in-process `SlidingWindowLimiter`)
- Event queue (`vibestream:events:queue`)
- Dead letter queue (`vibestream:events:dead_letter`)

### Kafka Responsibilities (Not Needed)
- Durable event streaming
- Multi-consumer fan-out
- Long-term event replay
- Cross-region replication

---

## Future Re-evaluation Triggers

Re-evaluate Kafka adoption if **any** of these occur:

- [ ] Feedback volume exceeds 10K events/sec sustained
- [ ] 3+ independent services need feedback events
- [ ] Regulatory requirement for immutable event log > 7 years
- [ ] Multi-region deployment with event sync
- [ ] New real-time analytics pipeline requiring event streaming

---

## Conclusion

The current Redis + Worker architecture is **sufficient, simpler, and cheaper** for VibeStream's current and projected scale. Kafka introduces significant operational overhead without solving any existing problem.

**Recommendation: Keep current architecture. Re-evaluate at 100K DAU or when multi-consumer requirement emerges.**