# VibeStream

**Adaptive music recommendation platform that learns from your mood and feedback.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.1-092E20?style=for-the-badge&logo=django&logoColor=white)](https://djangoproject.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Modal](https://img.shields.io/badge/Modal-Serverless-7B68EE?style=for-the-badge&logo=modal&logoColor=white)](https://modal.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](https://mongodb.com/atlas)
[![Deezer](https://img.shields.io/badge/Deezer-API-FF6600?style=for-the-badge&logo=deezer&logoColor=white)](https://developers.deezer.com)
[![Tests](https://img.shields.io/badge/Tests-506%20passing-34D399?style=for-the-badge&logo=pytest)](https://github.com/JainMehul05/VibeStream/actions)

---

## Overview

VibeStream is an adaptive music recommendation platform that uses multimodal emotion detection (text, speech, facial expressions) to generate personalized music recommendations from Deezer. The system learns from user feedback (👍/👎/Open in Deezer) to continuously improve recommendations through online reinforcement learning.

**Key differentiator:** Emotion is a *contextual signal* for recommendation, not the entire user profile. The system combines rule-based recommendation (EWMA + Markov mood blending) with online personalization (Thompson Sampling contextual bandit + mood calibration) that adapts to each user's taste over time.

---

## Why VibeStream?

Traditional music recommenders rely on collaborative filtering or static user profiles. VibeStream treats **emotion as a contextual signal** — a snapshot of how you feel *right now* — and combines it with:

- **Your mood history** (EWMA + Markov blending for recurring moods)
- **Your explicit feedback** (Thompson Sampling bandit re-ranking)
- **Your implicit feedback** (Open in Deezer = soft positive signal)
- **Your corrections** (Mood calibration map for systematic model errors)

The result: recommendations that adapt to *how you feel right now* while learning your long-term taste.

---

## Key Features

### 🎭 Multimodal Emotion Detection
| Modality | Model | Labels | Deployment |
|----------|-------|--------|------------|
| **Text** | Fine-tuned BERT (Transformers) | sadness, joy, love, anger, fear, neutral | Modal (BERT) |
| **Speech** | SVC + MFCC (scikit-learn) | calm, happy, sad, angry, fearful, disgust, surprised, neutral | Modal (librosa + SVC) |
| **Facial** | FER + MTCNN (Keras/TF) | angry, disgust, fear, happy, sad, surprise, neutral | Modal (FER + MTCNN) |

- Text: Django proxy → Modal (service token)
- Speech/Facial: Direct browser → Modal (user JWT, multipart ≤12 MB)
- Fallback: Neutral emotion + curated tracks on any model failure (never 500)

### 🎵 Adaptive Recommendations
- **Source:** Deezer Search API (keyless, public)
- **Base ranking:** EWMA (λ=0.85) + First-order Markov (boost=0.6) on mood history
- **Recurring mood blend:** Interleaves tracks for recurring mood (ratio 1:1 to 1:5)
- **Quality ranking:** Curated position + Deezer popularity (weight=0.2)
- **Curated fallback:** 14 popular tracks if Deezer fails

### 🧠 Personalization Architecture (Two-Layer RL)

#### Layer 1: Mood Calibration (L1)
- Per-user map: `{predicted_emotion: {actual_emotion: count}}`
- Threshold: ≥3 same-direction corrections → rewrite prediction
- Applied in Django after Modal returns (anonymous users unaffected)
- Persisted in `UserProfile.mood_calibration` (MongoDB)

#### Layer 2: Thompson Sampling Bandit (L2)
- **Algorithm:** Beta-Bernoulli posterior per feature axis (22 dimensions)
- **Features (22-d fixed):** Emotion (6) + Decade (7) + Duration (4) + Popularity quintile (5)
- **Rewards:** Like=+1.0α, Unlike=+1.0β, Open in Deezer=+0.5α
- **Cold-start:** Identity when `< 20` events (never injects/drops tracks)
- **Set-vote semantics:** Like↔Unlike switch reverts prior vote; Clear reverts to zero
- **Revert uses exact feature vector** from original vote (precise cancellation)
- Applied in Django after Modal returns; cold users see base order

### 🔐 Authentication & Security
| Mechanism | Implementation |
|-----------|----------------|
| **JWT** | HS256, 7d access / 14d refresh, rotation on refresh |
| **Passkeys (WebAuthn/FIDO2)** | `pywebauthn`, multiple credentials/user, usernameless login |
| **Passwords** | PBKDF2 (Django hasher), min 8 chars |
| **Rate limiting** | DRF: 60/min anon, 240/min user; Modal: sliding window (45/min general, 15/min media) |
| **CORS** | Header-based auth (no cookies), configurable origins |
| **Secrets** | Environment variables only (Vercel/Modal dashboards) |

### 📊 Feedback System (Unified `/api/v1/feedback/`)
| Kind | Signals | Persistence | RL Effect |
|------|---------|-------------|-----------|
| `mood` | predicted, actual, input_type, confidence | Mongo time-series (365d TTL) | Bumps `mood_calibration` map |
| `track` | `like` / `unlike` / `open_deezer` / `clear` | Mongo time-series + feature vector | Updates bandit posterior |

- `GET /api/v1/feedback/tracks/?ids=` — restores like/dislike UI state after reload

---

## System Architecture

```mermaid
flowchart LR
    subgraph Client["Client (Browser)"]
        FE["React 18 + MUI"]
        Auth["JWT + Passkeys"]
    end

    subgraph Backend["Django API (Vercel)"]
        AuthAPI["/api/v1/users/*"]
        InferenceProxy["/api/v1/text_emotion/, /music_recommendation/"]
        FeedbackAPI["/api/v1/feedback/"]
        HistoryAPI["/api/v1/users/*/history"]
        ProfileAPI["/api/v1/users/user/profile/"]
        MetricsAPI["/api/v1/metrics/"]
        GenAITools["GenAI Tool Layer"]
        Worker["Background Worker"]
    end

    subgraph Inference["Modal Inference (FastAPI)"]
        TextModel["BERT Text Emotion"]
        SpeechModel["SVC + MFCC"]
        FaceModel["FER + MTCNN"]
        Recommender["Deezer + EWMA/Markov"]
        Personalization["EWMA + Markov Blend"]
    end

    subgraph Data["Data Layer"]
        MongoDB[("MongoDB Atlas\nUsers, Profiles, Feedback, Metrics")]
        Redis[("Redis\nCache, Queue, Idempotency")]
    end

    subgraph External["External"]
        Deezer["Deezer Search API"]
        LLM["LLM (OpenAI/Anthropic/Mock)"]
    end

    FE -->|JWT| AuthAPI
    FE -->|JWT| InferenceProxy
    FE -.->|JWT (direct)| Inference
    AuthAPI <--> MongoDB
    InferenceProxy -->|Service Token| Inference
    FeedbackAPI <--> MongoDB
    FeedbackAPI -->|Event| Redis
    Redis -->|BRPOP| Worker
    Worker -->|Update| MongoDB
    Worker -->|Invalidate| Redis
    HistoryAPI <--> MongoDB
    ProfileAPI <--> MongoDB
    GenAITools -->|User JWT| AuthAPI
    GenAITools -->|User JWT| FeedbackAPI
    GenAITools -->|User JWT| ProfileAPI
    Inference --> Deezer
    Inference -->|Metrics| MongoDB
    LLM --> GenAITools
```

---

## Recommendation Pipeline

```
User Input (Text/Speech/Face)
         │
         ▼
┌─────────────────────────────────────┐
│ Emotion Detection (Modal)           │
│ • Text: BERT → emotion label        │
│ • Speech: SVC+MFCC → emotion label  │
│ • Face: FER+MTCNN → emotion label   │
│ Fallback: neutral + curated tracks  │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ Base Recommendation (Modal)         │
│ 1. Emotion → Deezer query map       │
│ 2. Search Deezer → candidate tracks │
│ 3. If history provided:             │
│    - EWMA (λ=0.85) on mood history  │
│    - Markov boost (0.6) on last→next│
│    - Recurring mood = top non-current│
│    - Blend ratio = round(curr/other) │
│    - Interleave (1 recurring per N) │
│ 4. Rank by quality (curated + pop)  │
│ 5. Curated fallback if Deezer fails │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ Personalization (Django)            │
│ L1 Mood Calibration:                │
│   if calibration[pred][actual] ≥ 3  │
│     rewrite emotion label           │
│                                     │
│ L2 Bandit Re-rank (if ≥20 events):  │
│   1. Load taste_profile (α,β,events)│
│   2. Sample β(α,β) per feature axis │
│   3. Score = Σ sampleᵢ × featureᵢ   │
│   4. Reorder tracks by score        │
│   Cold-start: identity (no reorder) │
└─────────────┬───────────────────────┘
              │
              ▼
    JSON Response: {emotion, recommendations[], degraded?, calibrated_from?}
```

### Pipeline Stages

| Stage | Location | Description |
|-------|----------|-------------|
| Candidate Generation | Modal | Deezer search + history blending (EWMA + Markov) |
| Base Ranking | Modal | Normalized curated score + popularity blend |
| Mood/Context | Modal/Django | Calibration signals + history context |
| Personalization | Django | Explicit preferences (genre/artist/era/mood) with cold-start guard |
| Thompson Sampling | Django | Beta-Bernoulli contextual bandit (cold-start threshold: 20 events) |
| Diversity (MMR) | Django | λ=0.3 across artist/genre/era dimensions |
| Explanations | Django | Truthful, signal-derived only (no hallucination) |
| Final Top-K | Django | Truncation to 20, cache storage |

---

## Adaptive Feedback Loop

```
User Feedback
      ↓
POST /api/v1/feedback/
      ↓
202 Accepted
      ↓
Redis Queue (LPUSH)
      ↓
Background Worker (BRPOP)
      ↓
Preference Profile Update
      ↓
Bandit Posterior Update (α/β)
      ↓
Mood Calibration Update
      ↓
Recommendation Cache Invalidation (SCAN-based)
      ↓
Future Recommendations Adapt
```

**Reliability mechanisms implemented:**
- Asynchronous processing via Redis queue
- Retries with exponential backoff + jitter (max 3 attempts)
- Dead-letter queue for failed events
- Idempotency keys (user-scoped, 24hr TTL, response replay)
- Duplicate protection (like↔unlike reverts, clear = zero)
- Cache invalidation on every feedback event

---

## GenAI Assistant

**GenAI-powered assistant with structured tool calling**

```
Natural Language
      ↓
LLM (Mock/OpenAI/Anthropic)
      ↓
IntentExtractor → Pydantic Validation (AnyIntent union)
      ↓
ToolRegistry.execute_tool(ToolCall)
      ↓
Django API (with user JWT)
      ↓
ToolResult → AssistantResponse
```

**Implemented Tools:**
| Tool | Description |
|------|-------------|
| `recommend_music` | Get personalized recommendations for an emotion |
| `get_preferences` | Retrieve user's explicit preference profile |
| `get_explanation` | Get explanation for why a track was recommended |
| `submit_feedback` | Submit mood correction or track signal |
| `get_profile` | Get user profile (mood/listening/recs history) |

**Security verified:**
- Prompt injection resistance (prototype pollution, intent override, SQL/XSS attempts)
- Tool authorization (all tools require auth token)
- Output sanitization (no passwords, JWT secrets, internal IDs)
- Tool schema validation (enum checks, required fields)
- Conversation history isolation per assistant instance
- Tool endpoint allowlist (only 5 Django APIs)

---

## Security

| Control | Implementation |
|---------|----------------|
| **Authentication** | JWT (HS256) + WebAuthn/FIDO2 Passkeys |
| **Authorization** | Per-user ownership checks on all mutating endpoints |
| **Input Validation** | Pydantic (GenAI), DRF serializers (REST), enum allowlists |
| **Injection Prevention** | MongoEngine ODM (no raw queries), prototype pollution protection |
| **Cross-User Access** | 403 on all profile/history endpoints for non-owners |
| **Rate Limiting** | User-scoped (DRF throttling + Modal sliding window) |
| **Idempotency** | Redis-backed, user-scoped, 24hr TTL, response replay |
| **Secrets** | Zero committed (`.env.example` only), platform-native secret stores |
| **Data Protection** | PBKDF2 passwords, TLS 1.2+, MongoDB Atlas encryption at rest |
| **GenAI Safety** | Structured tool calling, no direct DB/Redis access, output filtering |

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 18, React Router 6, MUI 6, Axios, Jest + React Testing Library |
| **Backend** | Django 5.1, DRF 3.15, mongoengine 0.29, PyJWT, pywebauthn, drf-yasg |
| **Inference** | FastAPI 0.115, Modal, PyTorch 2.2, Transformers 4.44, scikit-learn, FER, librosa, OpenCV |
| **Database** | MongoDB Atlas (mongoengine ODM) |
| **Cache / Queue** | Redis (Upstash/ElastiCache compatible), LocMemCache (dev) |
| **Music API** | Deezer Search API (keyless) |
| **GenAI** | LLM + structured tool calling (Mock/OpenAI/Anthropic backends) |
| **Testing** | Pytest (backend), Jest (frontend) |
| **CI/CD** | GitHub Actions (lint, test, build, Docker, security) |
| **Containerization** | Docker, Docker Compose (local) |
| **Infra (Reference)** | Kubernetes, Helm, Terraform, Argo CD, AWS/GCP/OCI |

---

## Evaluation Results

**Offline Synthetic Evaluation** — No real user data used. Results demonstrate pipeline behavior under simulation only.

### Ablation Study
| System | NDCG@10 | Hit Rate@10 | Unique Artists@10 |
|--------|---------|-------------|-------------------|
| Base Only | 0.0187 | 0.0978 | 8.87 |
| + Personalization | 0.8454 | 0.8587 | 2.73 |
| + Bandit | 0.7678 | 0.8587 | 3.19 |
| + Diversity (Full) | 0.5331 | 0.7717 | 8.62 |

**Key trade-off:** Personalization substantially increases relevance. Bandit learning adapts ranking based on user feedback. Diversity reduces repetitive artist recommendations but can reduce ranking relevance metrics — demonstrating an explicit relevance/diversity trade-off.

### Cold-Start Evaluation
| User History | Users | NDCG@10 | Hit Rate@10 |
|--------------|-------|---------|-------------|
| 0 | 41 | 0.5715 | 0.8281 |
| 1–5 | 57 | 0.6551 | 0.9278 |
| 5–20 | 48 | 0.6364 | 0.8222 |
| 20+ | 54 | 0.3320 | 0.6786 |

Cold-start users (0–5 interactions) achieve highest hit rates due to diversity + popularity signals. Power users (20+) see lower NDCG due to diversity/relevance trade-off — documented limitation.

---

## Performance (Local Baseline)

| Operation | p50 | p95 | Throughput | Errors |
|-----------|-----|-----|------------|--------|
| Health | ~5 ms | ~15 ms | ~2000/s | 0% |
| Recommendation (cache miss) | ~120 ms | ~350 ms | ~50/s | 0% |
| Recommendation (cache hit) | ~8 ms | ~25 ms | ~800/s | 0% |
| Feedback (sync mode) | ~45 ms | ~120 ms | ~100/s | 0% |
| Worker Processing | ~25 ms | ~80 ms | ~40/s | 0% |

*Environment: Local machine, Python 3.12, mongomock, fakeredis, SQLite (test only)*
*Label: Local benchmark / pre-deployment performance baseline*

---

## Testing

### Final Verified Test Matrix
| Test Suite | Result |
|------------|--------|
| Backend (includes GenAI, E2E) | 274 passed, 1 failed* |
| Modal Inference | 172 passed, 10 skipped |
| Frontend (Jest/RTL) | 60 passed |
| **Total** | **506 passed, 1 failed*** |

*1 pre-existing failure in idempotency test (middleware scopes to "anon" before DRF auth) — not a regression.

### Run Tests
```bash
# Backend (274 tests)
cd backend && .venv/bin/python -m pytest -q

# Modal Inference (182 tests)
cd modal_inference && .venv/bin/python -m pytest -q

# Frontend (60 tests)
cd frontend && npm test -- --watchAll=false --passWithNoTests

# Full CI
make test
```

---

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 18+
- MongoDB (local or Atlas)
- Modal CLI (`pip install modal`)

### Quick Start
```bash
# 1. Clone and install
git clone https://github.com/JainMehul05/VibeStream.git
cd VibeStream

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env   # Edit with your values

# Frontend
cd ../frontend
npm ci
cp .env.example .env   # Set REACT_APP_API_URL, REACT_APP_MODAL_API_URL

# Modal Inference (separate terminal)
cd ../modal_inference
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-dev.txt
modal serve modal_app.py   # For local inference
```

### Run All Services
```bash
# Terminal 1: MongoDB (if not using Atlas)
docker run -d -p 27017:27017 --name mongodb mongo:7

# Terminal 2: Backend
cd backend && source .venv/bin/activate && python manage.py runserver

# Terminal 3: Frontend
cd frontend && npm start

# Terminal 4: Modal Inference (for speech/facial)
cd modal_inference && source .venv/bin/activate && modal serve modal_app.py
```

### Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `MONGO_DB_URI` | Yes | MongoDB Atlas connection string |
| `JWT_SIGNING_KEY` | Yes | HS256 key (shared with Modal) |
| `MODAL_INFERENCE_URL` | Yes | Modal service URL |
| `MODAL_SERVICE_TOKEN` | Yes | Shared service token (Django ↔ Modal) |
| `WEBAUTHN_RP_ID` | Prod | Frontend bare domain (e.g., `vibestream.vercel.app`) |
| `WEBAUTHN_EXPECTED_ORIGINS` | Prod | Frontend origins (comma-separated) |
| `SENTRY_DSN` | Optional | Error/performance monitoring |
| `CACHE_REDIS_URL` | Optional | Redis for shared cache (default: LocMemCache) |

See `.env.example` for the complete template.

---

## Deployment

**Deployment status:** The application is deployment-ready, but production deployment and live-cloud verification have not yet been performed.

### Canonical Path: Vercel + Modal
```bash
# Modal inference (one-time models bootstrap, then deploy)
cd modal_inference
modal run modal_app.py::download_models    # first time only
modal deploy modal_app.py

# Vercel projects (backend Django API + frontend SPA)
vercel link              # link both backend/ and frontend/
vercel env add REACT_APP_API_URL
vercel env add REACT_APP_MODAL_API_URL

# Deploy both
(cd backend  && vercel deploy --prod --yes)
(cd frontend && vercel deploy --prod --yes)
```

### Local Deployment
```bash
# Full stack via Docker Compose
MODAL_INFERENCE_URL=<modal-serve-url> docker compose up -d
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# Swagger:  http://localhost:8000/swagger/
```

### Reference Infrastructure (Not Currently Deployed)
The repository includes infrastructure definitions for self-hosting:
- **Kubernetes:** `kubernetes/` (blue-green, canary, common, staging)
- **Helm:** `helm/` (vibestream-backend, vibestream-frontend, monitoring)
- **Terraform:** `terraform/` (VPC, EKS/GKE/AKS, RDS, Redis, S3, Argo CD)
- **Argo CD:** `argocd/` (app-of-apps pattern)
- **Cloud Overlays:** `aws/`, `gcp/`, `oracle-cloud/`

> **Note:** These are reference implementations for self-hosting. The canonical production path is **Vercel + Modal**. Kubernetes/Helm/Terraform/ArgoCD are not currently deployed.

---

## Screenshots

| Page | Description |
|------|-------------|
| ![Landing](images/landingpage.png) | Landing page with 3D WebGL background |
| ![Home](images/home-text.png) | Home page - text emotion input |
| ![Results](images/results.png) | Results with track cards + feedback |
| ![Profile](images/profile.png) | Profile with mood/listening history |

*Images in `images/` directory.*

---

## Project Structure

```
VibeStream/
├── backend/                    # Django REST API
│   ├── api/                    # Emotion proxy, recommendations, feedback, RL
│   ├── users/                  # Auth, profiles, passkeys, history
│   ├── integrations/           # Modal HTTP client
│   ├── common/                 # Shared exceptions, utilities
│   ├── observability/          # SRE metrics (MongoDB time-series)
│   ├── genai/                  # GenAI assistant (tools, intent, schemas)
│   ├── evaluation/             # Offline evaluation framework
│   ├── tests/                  # 275 pytest tests (mongomock)
│   └── backend/                # Django settings, URLs, WSGI
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── components/         # Auth, MoodInput, Passkeys, Profile, UI
│   │   ├── pages/              # Landing, Home, Results, Profile, Passkeys
│   │   ├── services/           # auth, feedback, listening, passkeys, recommend
│   │   ├── context/            # DarkModeContext
│   │   └── config.js           # API_V1_URL, MODAL_API_URL
│   └── public/
├── modal_inference/            # Modal ML Inference (FastAPI)
│   ├── service.py              # FastAPI app + endpoints
│   ├── modal_app.py            # Modal deployment config
│   ├── inference/              # Text/Speech/Face models
│   ├── recommendation/         # Deezer client, EWMA+Markov, personalization
│   ├── auth.py                 # JWT + service token verification
│   ├── cache.py                # TTLCache (LRU + TTL)
│   ├── rate_limit.py           # Sliding window rate limiter
│   ├── metrics.py / _store.py  # SRE metrics (in-process + MongoDB)
│   └── tests/                  # 182 tests (172 pass, 10 skipped)
├── ai_ml/                      # Legacy training code (reference only)
├── data_analytics/             # Legacy Spark/Hadoop scripts (reference)
├── mobile/                     # React Native / Expo (optional)
├── kubernetes/                 # K8s manifests (reference)
├── helm/                       # Helm charts (reference)
├── terraform/                  # Terraform modules (reference)
├── argocd/                     # Argo CD applications (reference)
├── docker-compose.yml          # Local dev stack (Mongo + backend + frontend)
├── Makefile                    # Common tasks (install, test, deploy)
├── openapi.yaml                # OpenAPI 3.0 spec (v1 endpoints)
└── .env.example                # Environment variable template
```

---

## Future Improvements

- Production deployment and live load testing
- Richer contextual bandit features
- Real-world recommendation evaluation with production traffic
- Offline LoRA fine-tuning for emotion models

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

**Mehul Jain**  
GitHub: [@JainMehul05](https://github.com/JainMehul05)  
LinkedIn: [linkedin.com/in/mehuljain05](https://linkedin.com/in/mehuljain05)

---

## Acknowledgments

- **Son Nguyen** — Original Moodify architecture and implementation
- **Deezer** — Free, keyless music search API
- **Modal** — Serverless GPU/CPU inference with memory snapshots
- **MongoDB Atlas** — Managed database with time-series collections
- **Vercel** — Serverless Django + React hosting
- **Sentry** — Error/performance monitoring (opt-in)