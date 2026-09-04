# VibeStream Architecture

**Version**: 1.0 (Phase 1 Baseline)
**Status**: Documented from running production system

---

## 1. System Overview

VibeStream is an adaptive music recommendation platform that detects user emotions from text, speech, and facial expressions, then provides personalized music recommendations via Deezer's public API. The system learns from user feedback (👍/👎/open-in-Deezer) to personalize future recommendations using online reinforcement learning.

### Core Capabilities
- **Multi-modal emotion detection**: Text (BERT), Speech (SVC+MFCC), Facial (FER+MTCNN)
- **Real-time recommendations**: Deezer search + history-aware blending (EWMA + Markov)
- **Online personalization**: Thompson Sampling bandit + mood calibration map
- **Passwordless auth**: Passkeys (WebAuthn/FIDO2) layered on JWT
- **Serverless architecture**: Scales to zero, pay-per-use

---

## 2. High-Level Architecture

### Production Topology (Canonical: Vercel + Modal)

```
┌─────────────┐     HTTPS/REST      ┌──────────────────────┐
│   Browser   │◄──────────────────►│  Frontend (Vercel)   │
│  (React)    │     JWT Bearer      │  Static SPA + CDN    │
└─────────────┘                     └──────────┬───────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
            ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
            │  Backend API  │           │  Modal ML     │           │   Deezer API  │
            │  (Django)     │           │  (FastAPI)    │           │  (Public)     │
            │  /users/*     │           │  /text_emotion│           │  /search      │
            │  /api/*       │           │  /speech_emo  │           └───────────────┘
            └───────┬───────┘           │  /facial_emo  │
                    │                   │  /music_rec   │
                    │                   └───────┬───────┘
                    │                           │
                    ▼                           ▼
            ┌─────────────────────────────────────────────┐
            │           MongoDB Atlas                     │
            │  users, user_profile, mood_feedback (TS),   │
            │  track_feedback (TS), webauthn_credentials, │
            │  webauthn_challenges, backend_metrics (TS), │
            │  inference_metrics (TS)                     │
            └─────────────────────────────────────────────┘
```

### Component Communication Matrix

| Path | Protocol | Auth | Purpose |
|------|----------|------|---------|
| Frontend → Backend | HTTPS/REST | JWT Bearer | Auth, profiles, history, text/music proxy |
| Frontend → Modal | HTTPS/REST | JWT Bearer | Speech/facial uploads (direct, bypass Django) |
| Backend → Modal | HTTPS/REST | Service Token | Text emotion + music recommendation proxy |
| Backend → MongoDB | MongoDB Wire | URI Creds | All persistence |
| Modal → MongoDB | MongoDB Wire | URI Creds | Metrics persistence only |
| Modal → Deezer | HTTPS/REST | None (keyless) | Music search |

---

## 3. Frontend Architecture

### Tech Stack
- **Framework**: React 18.3 (Create React App)
- **Routing**: React Router 6.26
- **UI Library**: Material UI (MUI) 6.1
- **State**: React Context (DarkMode) + localStorage (tokens)
- **HTTP**: Axios with 401→refresh interceptor
- **3D/WebGL**: Three.js + React Three Fiber (landing page)
- **Testing**: Jest 27 + React Testing Library (snapshot tests)

### Key Components

```
src/
├── App.js                    # Routes, providers, transitions
├── config.js                 # API_URL, MODAL_API_URL from env
├── index.js                  # Entry, Sentry init (opt-in)
├── theme.js                  # MUI theme (light/dark)
├── context/
│   └── DarkModeContext.js    # Theme toggle + body class sync
├── services/
│   ├── auth.js               # Token storage, 401-refresh, claims
│   └── passkeys.js           # WebAuthn ceremony helpers
├── components/
│   ├── Navbar.js             # Account dropdown → Passkeys/Logout
│   ├── Footer.js
│   ├── RequireAuth.jsx       # Route guard (redirects to /login)
│   ├── RedirectIfAuthed.jsx  # Bounces authed users from auth pages
│   ├── Auth/Login.js, Register.js
│   ├── MoodInput/TextInput.js, SpeechInput.js, FacialInput.js
│   ├── ModalComponent.js     # Shared input modal
│   ├── MoodFeedbackWidget.jsx # "Was this right?" correction UI
│   ├── TrackPlayer.js        # 30s preview + Deezer link
│   ├── Passkeys/PasskeyPromptModal.jsx
│   └── Profile/Profile.js    # Mood/Listening/Recommendations tabs
├── pages/
│   ├── LandingPage.js        # 3D hero, marketing
│   ├── HomePage.js           # Mood input selection
│   ├── ResultsPage.js        # Recommendations + feedback UI
│   ├── ProfilePage.js        # History tabs + passkeys link
│   ├── PasskeysPage.js       # Add/rename/delete passkeys
│   └── Legal pages (Privacy, Terms, ForgotPassword)
└── styles/styles.css         # Global + body.dark-mode/light-mode
```

### Authentication Flow (Frontend)
1. App start → `installAuthInterceptor()` attaches Bearer token to all requests
2. 401 response → auto-refresh via `/users/token/refresh/` → replay request
3. Refresh fails → `logout()` clears tokens + dispatches `VibeStream:auth-change`
4. `Navbar`/`RequireAuth` listen for auth-change to update UI instantly

### State Management
- **Tokens**: localStorage (`token`, `refresh_token`) - no Redux
- **User claims**: Decoded from JWT client-side (`jwt-decode`)
- **Theme**: `DarkModeContext` + `localStorage.darkMode` + `body.classList`
- **No server-side session** - fully stateless JWT

---

## 4. Backend Architecture (Django)

### Tech Stack
- **Framework**: Django 5.1 + DRF 3.15
- **Database**: MongoDB Atlas via mongoengine 0.29 (no SQL)
- **Auth**: Custom `MongoJWTAuthentication` (HS256 JWT)
- **Passkeys**: `py_webauthn` 2.7 (WebAuthn/FIDO2)
- **HTTP Client**: `requests` to Modal (with retry)
- **Observability**: Custom middleware → MongoDB time-series
- **Deployment**: Vercel serverless (`vercel_wsgi.py` entry)

### Project Structure

```
backend/
├── manage.py
├── vercel_wsgi.py          # @vercel/python entrypoint
├── vercel.json             # Routes all to vercel_wsgi.py
├── requirements.txt        # Slim deps - NO ML packages
├── backend/                # Django project settings
│   ├── settings.py         # JWT, MongoDB, CORS, DRF, Swagger
│   ├── urls.py             # Root: /users/, /api/, /swagger/
│   ├── swagger.py          # CDN-loaded Swagger/Redoc UI
│   └── wsgi.py             # Standard WSGI
├── api/                    # Emotion + recommendation endpoints
│   ├── views.py            # health, text_emotion, music_recommendation
│   ├── urls.py             # /api/health, /text_emotion, /music_rec, /feedback
│   ├── models.py           # UserProfile (mood/listening/recs + RL state)
│   ├── bandit.py           # Thompson Sampling re-ranker (L2)
│   ├── calibration.py      # Mood calibration map (L1)
│   ├── track_features.py   # 22-dim fixed feature extractor
│   ├── feedback_views.py   # POST /feedback, GET /feedback/tracks
│   ├── feedback_store.py   # Mongo time-series persistence
│   └── services/
│       └── inference_client.py  # Modal HTTP client with retry
├── users/                  # Auth + account management
│   ├── views.py            # register, login, refresh, profile, history
│   ├── passkey_views.py    # WebAuthn begin/complete ceremonies
│   ├── urls.py             # /users/* + /users/passkeys/*
│   ├── authentication.py   # MongoJWTAuthentication
│   ├── documents.py        # User, WebAuthnCredential, WebAuthnChallenge
│   └── tokens.py           # JWT encode/decode (HS256)
└── observability/          # SRE metrics
    ├── middleware.py       # Per-request timing + insert
    ├── recorder.py         # In-process counters + reservoir
    ├── store.py            # Mongo time-series persistence
    └── views.py            # GET /api/metrics/ (admin token)
```

### Request Lifecycle

```
Client Request
    │
    ▼
Vercel Edge → vercel_wsgi.py → WhiteNoise → CommonMiddleware
    │
    ▼
CorsMiddleware → SecurityMiddleware → MetricsMiddleware
    │
    ▼
DRF Dispatcher → MongoJWTAuthentication (if protected)
    │         Decodes JWT → fetches User by sub → attaches request.user
    ▼
View Function (api/views.py or users/views.py)
    │
    ├──→ MongoDB (user_profile, feedback collections)
    ├──→ Modal Inference (service token, for text_emotion/music_rec proxy)
    └──→ Response
```

### API Endpoints (Current - No Versioning)

| Domain | Endpoints |
|--------|-----------|
| **Auth** | `POST /users/register/`, `POST /users/login/`, `POST /users/token/refresh/`, `GET /users/validate_token/` |
| **Passkeys** | `POST /users/passkeys/register/begin/`, `POST /users/passkeys/register/complete/`, `POST /users/passkeys/login/begin/`, `POST /users/passkeys/login/complete/`, `GET/PATCH/DELETE /users/passkeys/<id>/` |
| **Profile** | `GET/PUT/DELETE /users/user/profile/` |
| **History** | `GET/POST/DELETE /users/mood_history/<id>/`, `GET/POST/DELETE /users/listening_history/<id>/`, `GET/POST/DELETE /users/recommendations/<id>/` |
| **Inference Proxy** | `GET /api/health/`, `POST /api/text_emotion/`, `POST /api/music_recommendation/` |
| **Feedback/RL** | `POST /api/feedback/`, `GET /api/feedback/tracks/` |
| **Metrics** | `GET /api/metrics/` (admin token) |
| **Docs** | `/swagger/`, `/redoc/`, `/swagger.json` |

---

## 5. Modal Inference Service

### Tech Stack
- **Platform**: Modal (serverless containers, scale-to-zero)
- **Framework**: FastAPI 0.115 (`@modal.asgi_app()`)
- **Models**: PyTorch 2.2 (CPU), Transformers 4.44, scikit-learn, FER, OpenCV
- **Caching**: In-process `TTLCache` (LRU + per-entry TTL)
- **Rate Limiting**: In-process sliding window per user
- **Metrics**: In-process recorder + MongoDB time-series persistence

### Project Structure

```
modal_inference/
├── modal_app.py            # Modal App: Image, Volume, Secret, @app.cls
├── service.py              # build_app(): FastAPI surface + deps
├── config.py               # Env vars, model paths, cache/rate-limit knobs
├── auth.py                 # JWT + service-token verification
├── cache.py                # TTLCache primitive (thread-safe)
├── rate_limit.py           # SlidingWindowLimiter + caller_key
├── schemas.py              # Pydantic request/response models
├── download_models.py      # HF → Modal Volume sync
├── inference/
│   ├── text_emotion.py     # TextEmotionModel (BERT) + prediction cache
│   ├── speech_emotion.py   # SpeechEmotionModel (SVC + librosa MFCC)
│   └── facial_emotion.py   # FacialEmotionModel (FER + MTCNN)
├── recommendation/
│   ├── music_recommendation.py  # Orchestrator
│   ├── deezer.py           # Deezer HTTP client + search cache
│   └── personalization.py  # EWMA + Markov + ranker
├── assets/                 # Bundled model files (speech, text config)
├── metrics.py              # In-process MetricsRecorder
├── metrics_store.py        # Mongo time-series persistence
└── tests/                  # 181 tests (171 fast + 10 functional)
```

### Models

| Model | Library | Weights Location | Output Labels |
|-------|---------|------------------|---------------|
| **Text** | Transformers (BERT) | HF Hub → Modal Volume (`/models/text_emotion_model/`) | sadness, joy, love, anger, fear, neutral |
| **Speech** | sklearn SVC + librosa | Bundled in image (`/assets/speech_emotion_model/`) | calm, happy, sad, angry, fearful, disgust, surprised, neutral |
| **Face** | FER (Keras) + MTCNN | Bundled with `fer` package | angry, disgust, fear, happy, sad, surprise, neutral |

### Endpoints

| Method | Path | Auth | Rate Tier | Request | Response |
|--------|------|------|-----------|---------|----------|
| GET | `/health` | None | Exempt | — | `{status, models_loaded, caches, rate_limit}` |
| POST | `/text_emotion` | Bearer | General (45/min) | `{text: 1-5000 chars}` | `EmotionResponse` |
| POST | `/speech_emotion` | Bearer | Media (15/min) | multipart file ≤12MB | `EmotionResponse` |
| POST | `/facial_emotion` | Bearer | Media (15/min) | multipart file ≤12MB | `EmotionResponse` |
| POST | `/music_recommendation` | Bearer | General (45/min) | `{emotion, market?, history?, genre?}` | `EmotionResponse` |
| GET | `/metrics` | Service Token | Exempt | `?window=1h&endpoint=` | SRE telemetry |

**EmotionResponse** (all endpoints):
```json
{
  "emotion": "joy",
  "recommendations": [{name, artist, album, preview_url, external_url, image_url, popularity, duration_ms, release_date}],
  "degraded": false,
  "market": null
}
```

### Resilience Guarantees
- **Never 500 on main endpoints**: Model failures → `degraded: true` + neutral + curated tracks
- **Only non-200**: 401 (auth), 413 (upload too large), 422 (validation), 429 (rate limit)
- **Caches never serve stale**: TTL expiry + LRU eviction + container restart on deploy
- **Empty/failed results never cached**

### Cost Protection Stack
1. **TTLCache** - Collapses repeated work (~5ms vs 100-500ms)
2. **Per-user rate limit** - 45/min general, 15/min media
3. **MAX_CONTAINERS=5** - Hard parallelism ceiling
4. **Modal billing cap** - Dashboard kill switch

---

## 6. Database Architecture

### MongoDB Collections (Atlas)

| Collection | Type | TTL | Purpose |
|------------|------|-----|---------|
| `users` | Document | Permanent | Auth accounts (username, email, PBKDF2 hash, is_active) |
| `user_profile` | Document | Permanent | Mood/listening history, saved recs, RL state |
| `mood_feedback` | Time-series | 365 days | Mood corrections (username, predicted, actual, input_type) |
| `track_feedback` | Time-series | 365 days | Track signals + features + seq (like/unlike/open_deezer/clear) |
| `webauthn_credentials` | Document | Permanent | Passkeys (credential_id, public_key, sign_count, metadata) |
| `webauthn_challenges` | Document | Auto-expire | Single-use ceremony challenges (flowId) |
| `backend_metrics` | Time-series | 30 days | Django SRE metrics (per-request) |
| `inference_metrics` | Time-series | 30 days | Modal SRE metrics (per-request) |

### Key Documents

**User** (`users/documents.py`):
```python
_id, username (unique), email (unique), password (PBKDF2), is_active, created_at
```

**UserProfile** (`api/models.py`):
```python
_id, username, mood_history[], listening_history[], recommendations[],
mood_calibration{predicted: {actual: count}}, taste_profile{alpha[22], beta[22], events}, created_at
```

**WebAuthnCredential** (`users/documents.py`):
```python
_id, user_id, username, credential_id (unique), public_key (COSE), sign_count,
transports[], aaguid, device_type, backed_up, name, created_at, last_used_at
```

### Index Strategy
- `auto_create_index=False` on all documents (serverless best practice)
- Indexes managed **once in Atlas**, not per cold start
- Critical indexes: `username` (users, user_profile), `credential_id` (webauthn_credentials), `expires_at` (webauthn_challenges)

---

## 7. Authentication & Authorization

### JWT (Primary)
- **Algorithm**: HS256
- **Signing Key**: `JWT_SIGNING_KEY` (shared with Modal)
- **Access Token**: 7 days, **Refresh Token**: 14 days (rotation on refresh)
- **Claims**: `sub` (user ObjectId), `username`, `type` (access/refresh), `exp`, `iat`
- **Verification**: `MongoJWTAuthentication` decodes → fetches User by `sub`

### Passkeys / WebAuthn (Secondary, Layered on JWT)
- **Library**: `py_webauthn` (audited)
- **RP ID**: Frontend bare domain (e.g., `vibestream-app.vercel.app`)
- **Ceremonies**: 2-step (begin → complete) with `flowId` challenge persistence
- **Multiple passkeys/user**: Phone, laptop, hardware key, synced keys
- **Verification**: Attestation (registration) + Assertion (login) + sign_count
- **Output**: Same `{access, refresh}` JWT pair as password login

### Cold-Start Resilience
- First Mongo read after idle retries 3× with 0.4s backoff
- Failure → **503 "Service is waking up"** (not 401)
- Prevents misleading "invalid credentials" on cold start

---

## 8. Recommendation Pipeline

### Full Flow: User Input → Personalized Recommendations

```
1. INPUT (Frontend)
   ├─ Text:     POST /api/text_emotion/ {text}        → Django → Modal (service token)
   ├─ Speech:   POST /speech_emotion (multipart)      → Modal (direct, user JWT)
   └─ Facial:   POST /facial_emotion (multipart)      → Modal (direct, user JWT)

2. EMOTION DETECTION (Modal)
   ├─ Text:     BERT → emotion label
   ├─ Speech:   SVC+MFCC → emotion label
   ├─ Facial:   FER+MTCNN → emotion label
   └─ Fallback: "neutral" + degraded=true on any failure

3. BASE RECOMMENDATIONS (Modal)
   ├─ Emotion → query map → Deezer search
   ├─ History (optional) → EWMA (λ=0.85) + Markov (boost=0.6)
   ├─ Recurring mood → secondary search → interleave (ratio 1:1 to 1:5)
   ├─ rank_by_quality (curated pos + popularity weight 0.2)
   └─ Curated fallback (14 tracks) if Deezer fails

4. PERSONALIZATION (Django - AFTER Modal returns)
   ├─ L1 Mood Calibration:
   │   UserProfile.mood_calibration{predicted: {actual: count}}
   │   ≥3 same-direction corrections → rewrite predicted label
   │   Anonymous/cold users: untouched
   └─ L2 Bandit Re-rank (Thompson Sampling):
       UserProfile.taste_profile{alpha[22], beta[22], events}
       Beta-Bernoulli posterior over 22-dim features
       Sample once per axis → score tracks → reorder
       Cold-start safe: identity when events < 20
       Bounded blast radius: only reorders, never injects/drops

5. RESPONSE → Frontend renders TrackCards with 👍/👎/Deezer
```

### Feedback → Learning Loop

```
POST /api/feedback/ (JWT required)
├─ kind=mood:  {predicted, actual, input_type, confidence?, session_id?}
│   → mood_feedback (TS) + bump mood_calibration[predicted][actual]
└─ kind=track: {track_id, signal, context_emotion?, track?}
    signal ∈ {like, unlike, open_deezer, clear}
    → track_feedback (TS) with features + seq (time_ns tiebreaker)
    → Set-vote semantics:
       • like/unlike: revert prior vote (exact features) → apply new
       • clear: revert prior → net zero
       • open_deezer: additive only, never reverted
    → Update taste_profile (bandit posterior)

GET /api/feedback/tracks/?ids=...
  → {feedback: {track_id: "like"|"unlike"}}
  → Restores button state after reload
```

### Feature Vector (22 dimensions, fixed order)
```
0-5:   Emotion one-hot      (sadness, joy, love, anger, fear, neutral)
6-12:  Decade one-hot       (pre1960, 60s, 70s, 80s, 90s, 2000s, 2010plus)
13-16: Duration one-hot     (under_2m, 2_4m, 4_6m, over_6m)
17-21: Popularity quintile  (p0-p4, list-relative within candidate set)
```

---

## 9. Observability

### SRE Metrics Pipeline (Both Services)

```
Request → MetricsMiddleware (times call)
    │
    ├─→ In-process Recorder (ring buffer ~1000 samples)
    │     └─→ Live snapshot on GET /metrics
    │
    └─→ MongoDB Atlas Time-Series (1 doc/request, ~150B compressed)
          └─→ Aggregated on GET /metrics?window=1h
```

### Collections
| Collection | Service | Read Endpoint |
|------------|---------|---------------|
| `backend_metrics` | Django | `GET /api/metrics/` (admin token) |
| `inference_metrics` | Modal | `GET /metrics` (service token) |

### Per-Document Schema
```json
{
  "ts": "ISODate",
  "meta": {"service": "django|modal", "endpoint": "/route/template", "method": "POST", "container": "...", "status_class": "2xx"},
  "status": 200,
  "latency_ms": 142.3,
  "degraded": false
}
```

### Response Shape (both services)
```json
{
  "service": "django|modal",
  "window": {"label": "1h", "since": "...", "until": "...", "seconds": 3600},
  "persisted": {"available": true, "endpoints": [...]},
  "live": {"container": "...", "uptime_seconds": 412.5, "endpoints": [...]}
}
```

### Properties
- **Write**: Per-request sync (~1ms warm), failures swallowed
- **Cardinality**: Path params normalized to route template
- **TTL**: 30 days native (env-tunable)
- **Auth on `/metrics`**: Service token only (end-user JWTs rejected)
- **Resilience**: Metrics NEVER break the request (all layers defensive)

### Error Monitoring
- **Sentry**: Opt-in via `SENTRY_DSN` / `REACT_APP_SENTRY_DSN`
- **Frontend**: `@sentry/react` + ErrorBoundary (no PII by default)
- **Backend**: `sentry-sdk[django]` (10% trace sample, no PII)
- **Local/CI**: SDK no-ops when DSN unset

---

## 10. Deployment Architecture

### Canonical Production: Vercel + Modal

| Component | Platform | Config |
|-----------|----------|--------|
| Frontend | Vercel | SPA, `REACT_APP_API_URL`, `REACT_APP_MODAL_API_URL` |
| Backend | Vercel | Django serverless, `vercel_wsgi.py`, env vars in dashboard |
| ML Inference | Modal | `modal deploy modal_app.py`, memory snapshots, scale-to-zero |
| Database | MongoDB Atlas | M30+ cluster, time-series collections |
| Metrics | MongoDB Atlas | Same cluster, TS collections |

### Reference Infrastructure (Self-Host Path)
> **Not actively deployed** - available for organizations requiring self-hosting

- **Kubernetes**: `kubernetes/` (blue-green, canary, common, staging)
- **Helm**: `helm/vibestream-backend`, `helm/vibestream-frontend`, `helm/monitoring`
- **Terraform**: `terraform/modules/` (vpc, eks/gke/aks, rds, redis, s3, monitoring, argocd)
- **Argo CD**: `argocd/applications/` (app-of-apps pattern)
- **Cloud Overlays**: `aws/`, `gcp/`, `oracle-cloud/` (IRSA, Workload Identity, etc.)
- **NGINX**: `nginx/` (modular edge with snippets, exporter)

### CI/CD
- **GitHub Actions**: Primary CI (lint, test, build)
- **Jenkins**: `Jenkinsfile` defined (multi-env, blue-green, canary) - reference
- **Deploy**: `make deploy-prod` → `deploy-modal` + `deploy-vercel-*`

---

## 11. Request Flow Diagram

```
User submits mood (text/speech/face)
         │
         ▼
┌─────────────────────────────────────┐
│ Frontend (React)                    │
│ - Captures input                    │
│ - Attaches JWT Bearer               │
│ - POST to appropriate endpoint      │
└──────────────┬──────────────────────┘
               │
     ┌─────────┴─────────┐
     │                   │
     ▼                   ▼
Text/Speech/Facial     Text only
     │                   │
     ▼                   ▼
Modal Inference    Django Backend
(FastAPI)          (proxy via service token)
     │                   │
     ├─ Model predicts  │
     ├─ Deezer search   │
     ├─ EWMA+Markov     │
     └─ Base recs       │
     │                   │
     └─────────┬─────────┘
               ▼
    Django applies personalization
    ├─ L1: mood_calibration map
    └─ L2: bandit.rerank (if warm)
               │
               ▼
         JSON Response
    {emotion, recommendations[], degraded, calibrated_from?}
               │
               ▼
         Frontend renders
         TrackCards + Feedback UI
               │
               ▼
    User clicks 👍/👎/Deezer
               │
               ▼
    POST /api/feedback/ (JWT)
    ├─ track_feedback (TS) + features
    └─ taste_profile updated (bandit)
```

---

## 12. Security Architecture

### Layers
| Layer | Implementation |
|-------|----------------|
| **Transport** | TLS 1.3 everywhere (Vercel, Modal, Atlas) |
| **Authentication** | JWT (HS256) + Passkeys (WebAuthn/FIDO2) |
| **Authorization** | Per-user ownership checks on all mutating endpoints |
| **Rate Limiting** | DRF (60/min anon, 240/min user) + Modal sliding window |
| **Input Validation** | DRF serializers + Pydantic (Modal) |
| **CORS** | Configurable origins, credentials=false (header auth) |
| **Secrets** | Env vars only (Vercel/Modal dashboards), never in code |
| **CSRF** | N/A - stateless JWT, no cookies |

### Passkey Security
- Private key never leaves authenticator
- Server stores only COSE public key + sign_count
- Non-increasing sign_count → cloned key detection → rejection
- Challenge single-use + expiring (300s default)
- RP ID bound to frontend origin (browser enforces)

---

## 13. Technology Stack Summary

| Layer | Technology | Version |
|-------|------------|---------|
| **Frontend** | React, React Router, MUI, Axios, Three.js, Jest | 18.3, 6.26, 6.1, 1.7, r166, 27.5 |
| **Backend** | Django, DRF, mongoengine, PyJWT, py_webauthn | 5.1, 3.15, 0.29, 2.9, 2.7 |
| **ML Inference** | Modal, FastAPI, PyTorch, Transformers, sklearn, FER | 0.65+, 0.115, 2.2, 4.44, 1.3, 23.0 |
| **Database** | MongoDB Atlas | 7.x |
| **Music API** | Deezer Search | keyless |
| **Observability** | Sentry (opt-in), MongoDB TS metrics | 2.66, 1.0 |
| **Deployment** | Vercel, Modal, Docker Compose (local) | - |
| **IaC (Ref)** | Terraform, Helm, Kubernetes, Argo CD | - |

---

## 14. Scalability & Performance

### Current Production Characteristics
- **Frontend**: Static SPA on Vercel CDN (global edge)
- **Backend**: Vercel serverless functions (scale-to-zero, ~1-2s cold)
- **ML Inference**: Modal containers (scale-to-zero, memory snapshots ~1-2s cold)
- **Database**: MongoDB Atlas (managed, auto-scaling)
- **Caching**: In-process LRU/TTL in Modal (no Redis required)

### Performance Targets (Measured)
| Metric | Target | Actual (Prod) |
|--------|--------|---------------|
| Text emotion + recs | < 2s | ~200-500ms (warm), ~1-2s (cold) |
| Speech/Facial emotion | < 3s | ~500ms-1s (warm), ~1-3s (cold) |
| API health check | < 100ms | ~50ms |
| Frontend load | < 3s | < 2s (Vercel CDN) |

### Cost Profile (Estimated)
- **Vercel**: Free tier sufficient for current traffic
- **Modal**: Pennies to few $/month (scale-to-zero + caching)
- **MongoDB Atlas**: Free tier (M0) or low-tier paid
- **Total**: < $20/month for typical usage

---

## 15. Future Evolution (Post-Phase 1)

### Phase 2 Targets
- Advanced Redis caching (shared cache layer)
- Event-driven feedback processing (background workers)
- Cache invalidation strategies
- Idempotency keys for mutations
- Load testing + performance optimization

### Phase 3 Targets
- Kubernetes self-host hardening
- Advanced observability (distributed tracing)
- Recommendation evaluation framework
- A/B testing infrastructure

### Phase 4 Targets
- Multi-region deployment
- Advanced security (mTLS, secrets rotation)
- Cost optimization at scale
- Compliance certifications

---

*This document reflects the **actual running architecture** as of Phase 1 baseline. Aspirational components (Kubernetes, Terraform, etc.) are documented in `INFRASTRUCTURE_SETUP.md` and `DEPLOYMENT.md` as reference implementations for self-hosting.*
