# Phase 4 Final Architecture — VibeStream

## System Overview

```
                                    ┌─────────────────────┐
                                    │       User          │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │     Frontend        │
                                    │  (React + MUI)      │
                                    │  Vercel / Local     │
                                    └──────────┬──────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
         ┌─────────────────────┐     ┌─────────────────────┐    ┌─────────────────────┐
         │    Backend API      │     │   Modal Inference   │    │    GenAI Assistant  │
         │   (Django + DRF)    │     │   (FastAPI + ML)    │    │   (LLM + Tools)     │
         │   Vercel / Local    │     │   Modal / Local     │    │   Backend / Local   │
         └──────────┬──────────┘     └──────────┬──────────┘    └──────────┬──────────┘
                    │                           │                          │
         ┌──────────┴──────────┐                │                          │
         ▼                     ▼                │                          │
┌─────────────────┐   ┌─────────────────┐       │                          │
│     Redis       │   │    MongoDB      │       │                          │
│   (Cache +      │   │    Atlas        │       │                          │
│   Queue +       │   │  (Users,        │       │                          │
│   Rate Limit)   │   │   Profiles,     │       │                          │
│                 │   │   Feedback,     │       │                          │
│                 │   │   Metrics)      │       │                          │
└─────────────────┘   └─────────────────┘       │                          │
                    │                           │                          │
                    ▼                           ▼                          ▼
         ┌─────────────────────────────────────────────────────────────────────┐
         │                      Async Worker Process                           │
         │  • Feedback Processing  • Preference Updates  • Cache Invalidation │
         │  • Calibration Updates  • Bandit Posterior    • Dead Letter Queue  │
         └─────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Frontend (React 18 + MUI 6)
- **Deployment**: Vercel (production), `npm start` (local)
- **Routes**: Landing → Home (emotion input) → Results (recommendations) → Profile
- **Auth**: JWT in localStorage, Passkeys (WebAuthn)
- **GenAI Chat**: Natural language interface via `/api/v1/genai/chat/`

### 2. Backend API (Django 5.1 + DRF)
- **Deployment**: Vercel (serverless), Docker Compose (local)
- **Endpoints**:
  - `/api/v1/health/` — Liveness/readiness
  - `/api/v1/text_emotion/` — Text emotion + recommendations
  - `/api/v1/music_recommendation/` — Mood-based recommendations
  - `/api/v1/feedback/` — Unified feedback (mood + track)
  - `/api/v1/feedback/tracks/` — Like/dislike state
  - `/api/v1/users/*` — Auth, profile, history
  - `/api/v1/genai/*` — GenAI assistant
  - `/api/v1/metrics/` — SRE metrics (service token)

### 3. Modal Inference (FastAPI)
- **Deployment**: Modal serverless
- **Models**: BERT (text), SVC+MFCC (speech), FER+MTCNN (facial)
- **Recommendation**: Deezer search + EWMA/Markov blending
- **Caching**: TTLCache (in-process)
- **Rate Limiting**: Sliding window per user

### 4. Data Layer

#### Redis
- **Recommendation Cache**: `rec:{pipeline_version}:{user_id}:{emotion}:{genre}:{history_hash}` (TTL: 10 min)
- **Event Queue**: `vibestream:events:queue` (LPUSH/BRPOP)
- **Rate Limiting**: `ratelimit:{endpoint}:{user|ip}` (sorted sets, sliding window)
- **Dead Letter**: `vibestream:events:dead_letter`

#### MongoDB Atlas
- **Users**: Authentication (username, email, password hash, passkeys)
- **UserProfile**: Mood history, listening history, preferences, RL state
- **Feedback (Time-series)**: `mood_feedback`, `track_feedback` (TTL: 365 days)
- **Metrics (Time-series)**: `backend_metrics`, `inference_metrics` (TTL: 30 days)

### 5. Async Worker
- **Process**: Separate Python process (`python -m api.worker`)
- **Event Types**: `feedback_track`, `feedback_mood`, `cache_invalidate`, `profile_update`
- **Retries**: 3 attempts with requeue, then dead letter
- **Idempotency**: Via `Idempotency-Key` header + event deduplication

### 6. GenAI Assistant
- **LLM**: OpenAI GPT-4o-mini / Anthropic Claude-3-Haiku / Mock (testing)
- **Intent Extraction**: Structured output via Pydantic schemas
- **Tools**: `recommend_music`, `get_preferences`, `get_explanation`, `submit_feedback`, `get_profile`
- **Validation**: Schema validation before execution
- **Auth**: User JWT passed to tools for API calls
- **Fallback**: Graceful degradation when LLM unavailable

## Data Flow

### Recommendation Request (Authenticated)
```
User → Frontend → POST /api/v1/music_recommendation/ (JWT)
    → Check Redis cache (hit → return cached)
    → Run pipeline: Candidate Gen → Base Rank → Mood/Context → Personalization → Bandit → Diversity → Explanations
    → Cache result (10 min TTL)
    → Return {emotion, recommendations[], calibrated_from?, degraded?}
```

### Feedback Submission
```
User → Frontend → POST /api/v1/feedback/ (JWT + Idempotency-Key)
    → Validate → Create Event → Enqueue to Redis
    → Return 202 Accepted immediately
    → Worker dequeues → Process (calibration, bandit, preferences, cache invalidation)
    → Update MongoDB → Invalidate user's recommendation cache
```

### GenAI Interaction
```
User → Frontend → POST /api/v1/genai/chat/ (JWT)
    → Build prompt with conversation history
    → LLM → Structured intent (JSON)
    → Validate against schema
    → Execute tool via ToolRegistry (with user's JWT)
    → Format response → Return to user
```

## Security

| Layer | Mechanism |
|-------|-----------|
| Transport | HTTPS everywhere (Vercel, Modal) |
| Auth | JWT HS256 (7d access, 14d refresh), Passkeys (WebAuthn/FIDO2) |
| Rate Limiting | Sliding window (Redis): 30/min recommend, 60/min feedback, 45/min text, 10/5min auth |
| CORS | Header-based, configurable origins |
| Secrets | Environment variables only (Vercel, Modal dashboards) |
| GenAI Tools | User JWT validation, tool schema validation, no direct DB access |

## Observability

| Component | Implementation |
|-----------|----------------|
| Logs | structlog (JSON), request IDs, correlation IDs |
| Metrics | MongoDB time-series (request count, latency p50/p95/p99, error rate, throughput) |
| Health | `/health/live`, `/health/ready`, `/health/detail` |
| Alerts | CloudWatch (AWS) / Custom (TBD) |

## Deployment

### Production (Vercel + Modal)
- **Frontend**: `vercel deploy --prod` (GitHub Actions)
- **Backend**: `vercel deploy --prod` (GitHub Actions)
- **Inference**: `modal deploy modal_app.py` (GitHub Actions)
- **Database**: MongoDB Atlas (managed)
- **Cache/Queue**: Upstash Redis / Railway (managed)

### Local Development
```bash
docker compose up -d  # MongoDB + Redis + Backend + Frontend
modal serve modal_app.py  # Inference (separate terminal)
```

### CI/CD (GitHub Actions)
1. **Lint** → Ruff (Python), ESLint (JS)
2. **Test** → Backend (245), Modal (172), Frontend (60), GenAI (16), Evaluation
3. **Build** → Docker images → GHCR
4. **Deploy** → Modal → Vercel (backend) → Vercel (frontend)
5. **Verify** → Health checks + smoke tests

## Scaling Assumptions

| Component | Scaling Strategy |
|-----------|------------------|
| Backend | Vercel serverless (auto-scale to 1000+ concurrent) |
| Modal | Modal serverless (auto-scale, max 5 containers) |
| Redis | Managed (Upstash/Railway) - auto-scale |
| MongoDB | Atlas M10+ - auto-scale, read replicas |
| Worker | Single process (can run multiple replicas with Redis queue) |

## Failure Modes & Mitigations

| Failure | Behavior | Mitigation |
|---------|----------|------------|
| Modal unavailable | `degraded: true` + neutral + curated tracks | Fallback in pipeline, circuit breaker |
| Redis unavailable | Fail-open rate limit, no cache | Graceful degradation, worker uses direct MongoDB |
| Worker down | Events queue in Redis | Restart worker, events processed on recovery |
| MongoDB down | 500 on writes, reads may work | Atlas HA, connection pooling |
| LLM unavailable | GenAI returns error, UI falls back to standard UI | Mock client for testing, clear error messages |

---

*Architecture reflects actual deployed state as of Phase 4 completion.*