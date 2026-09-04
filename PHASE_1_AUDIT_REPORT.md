# VibeStream Phase 1 - Repository Audit Report

## 1. Repository Structure

### Root Level
```
VIBESTREAM/
├── .claude/                    # Claude config (not part of app)
├── .devcontainer/              # VS Code dev container config
├── .github/                    # GitHub workflows
├── .idea/                      # IntelliJ IDE config
├── ai_ml/                      # LEGACY - Original ML training code (local training)
├── argocd/                     # Argo CD GitOps manifests
├── aws/                        # AWS Terraform + Kubernetes configs
├── backend/                    # ACTIVE - Django REST API (Vercel-deployed)
├── data_analytics/             # LEGACY - Spark/Hadoop analytics scripts
├── docs/                       # Documentation (to be created)
├── frontend/                   # ACTIVE - React web app (Vercel-deployed)
├── gcp/                        # GCP Terraform + Kubernetes configs
├── helm/                       # Helm charts for self-host deployment
├── images/                     # Static images for README
├── index.html                  # Legacy single-file demo (unused)
├── k8s-addons/                 # Kubernetes addons
├── kubernetes/                 # Kubernetes manifests (blue-green, canary)
├── mobile/                     # OPTIONAL - React Native app (Expo)
├── modal_inference/            # ACTIVE - Modal ML inference service (FastAPI)
├── nginx/                      # NGINX config for self-host
├── oracle-cloud/               # Oracle Cloud Terraform
├── packages/                   # Unused/empty
├── performance-tests/          # k6 load test scripts
├── scripts/                    # Deployment scripts
├── terraform/                  # Terraform modules (multi-cloud)
├── .env.example                # Minimal env example (6 lines only)
├── .gitignore                  # Standard gitignore
├── .prettierignore
├── ARCHITECTURE.md             # Comprehensive architecture doc
├── composer.json               # Unused (PHP?)
├── DEPLOYMENT.md               # Deployment runbook
├── docker-compose.yml          # Local dev stack (MongoDB + backend + frontend)
├── INFRASTRUCTURE_SETUP.md     # Self-host infra guide
├── jenkins_cicd.sh             # Jenkins setup script
├── Jenkinsfile                 # CI/CD pipeline
├── LICENSE                     # MIT license
├   llms.txt                    # LLM context file
├── Makefile                    # Root task runner
├── manage_docker.sh            # Docker helper
├── manage_moodify.sh           # Moodify management script
├── MOBILE_APPS.md              # Mobile documentation
├── openapi.yaml                # OpenAPI spec
├── package.json                # Root package.json (minimal)
├── pyproject.toml              # Python project config
├── README.md                   # Main documentation (Moodify branded)
├── render.yaml                 # Render.com deploy config
├── requirements.txt            # Root Python requirements (minimal)
├── robots.txt
└── sitemap.xml
```

### Directory Classification

| Directory | Status | Purpose | Key Files |
|-----------|--------|---------|-----------|
| `backend/` | **ACTIVE** | Django REST API (serverless, Vercel) | `manage.py`, `backend/settings.py`, `api/`, `users/`, `observability/` |
| `frontend/` | **ACTIVE** | React SPA (Vercel) | `src/App.js`, `src/components/`, `src/pages/`, `src/services/` |
| `modal_inference/` | **ACTIVE** | ML Inference on Modal (FastAPI) | `service.py`, `modal_app.py`, `inference/`, `recommendation/` |
| `ai_ml/` | **LEGACY** | Local ML training (not used in production) | `src/models/train_*.py`, `models/` |
| `data_analytics/` | **LEGACY** | Spark/Hadoop analytics (offline) | `*.py`, `spark-hadoop/` |
| `mobile/` | **OPTIONAL** | React Native/Expo app | `App.js`, `components/`, `pages/` |
| `kubernetes/` | **REFERENCE** | K8s manifests for self-host | `backend-deployment.yaml`, `frontend-deployment.yaml` |
| `helm/` | **REFERENCE** | Helm charts for self-host | `moodify-backend/`, `moodify-frontend/`, `monitoring/` |
| `terraform/` | **REFERENCE** | IaC for multi-cloud | `modules/`, `environments/` |
| `argocd/` | **REFERENCE** | GitOps manifests | `applications/`, `install-argocd.yaml` |
| `aws/`, `gcp/`, `oracle-cloud/` | **REFERENCE** | Cloud-specific overlays | `terraform/`, `kubernetes/` |

---

## 2. Runtime Architecture

### Active Production Path (Vercel + Modal)

```
┌─────────────┐     HTTPS      ┌──────────────────┐
│   Browser   │◄──────────────►│  Frontend (Vercel)│
│  (React)    │  REST + JWT    │  Static SPA       │
└─────────────┘                └────────┬─────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
            │ Backend API   │   │  Modal ML     │   │  Deezer API   │
            │ (Django/Vercel)│   │  (FastAPI)    │   │  (Public)     │
            │  /users/*     │   │  /text_emotion│   │  /search      │
            │  /api/*       │   │  /speech_emo  │   └───────────────┘
            └───────┬───────┘   │  /facial_emo  │
                    │           │  /music_rec   │
                    │           └───────┬───────┘
                    │                   │
                    ▼                   ▼
            ┌─────────────────────────────────────┐
            │        MongoDB Atlas                │
            │  users, user_profile,               │
            │  mood_feedback (TS),                │
            │  track_feedback (TS),               │
            │  webauthn_credentials,              │
            │  webauthn_challenges,               │
            │  backend_metrics (TS),              │
            │  inference_metrics (TS)             │
            └─────────────────────────────────────┘
```

### Component Communication

| Path | Protocol | Auth | Purpose |
|------|----------|------|---------|
| Frontend → Backend | HTTPS/REST | JWT Bearer | Auth, profiles, history, text/music proxy |
| Frontend → Modal | HTTPS/REST | JWT Bearer | Speech/facial uploads (direct, bypass Django) |
| Backend → Modal | HTTPS/REST | Service Token | Text emotion + music recommendation proxy |
| Backend → MongoDB | MongoDB Wire | URI creds | All persistence |
| Modal → MongoDB | MongoDB Wire | URI creds | Metrics persistence only |
| Modal → Deezer | HTTPS/REST | None (keyless) | Music search |

---

## 3. Authentication Flow

### JWT Authentication (Primary)

```
Registration:
  POST /users/register/ {username, email, password}
    → Creates User document + empty UserProfile
    → Returns 201 {message}

Login:
  POST /users/login/ {username|email, password}
    → Lookup by username, fallback to case-insensitive email
    → Verify PBKDF2 hash
    → Returns 200 {access, refresh} or 503 (cold Mongo)
    → Access: 7 days, Refresh: 14 days (HS256, JWT_SIGNING_KEY)

Token Refresh:
  POST /users/token/refresh/ {refresh}
    → Validate refresh token, lookup user
    → Returns new {access, refresh} pair (rotation)

Protected Requests:
  Authorization: Bearer <access>
  → MongoJWTAuthentication decodes, fetches User by sub
  → Attaches as request.user

Logout:
  Client-side only (clearTokens) - no server call
```

### Passkeys / WebAuthn (Secondary, layered on JWT)

```
Register Begin:  POST /users/passkeys/register/begin/ (Bearer)
  → Returns {options, flowId} with excludeCredentials

Register Complete: POST /users/passkeys/register/complete/ (Bearer)
  → Verify attestation, store WebAuthnCredential

Login Begin:     POST /users/passkeys/login/begin/ {username?}
  → Returns {options, flowId} (usernameless if omitted)

Login Complete:  POST /users/passkeys/login/complete/
  → Verify assertion, advance sign_count
  → Returns {access, refresh, username} (same JWT as password login)
```

**RP Config (must match frontend domain):**
- `WEBAUTHN_RP_ID`: bare domain (e.g., `vibestream-app.vercel.app`)
- `WEBAUTHN_RP_NAME`: display name (e.g., `VibeStream`)
- `WEBAUTHN_EXPECTED_ORIGINS`: comma-separated frontend origins

### Cold-Start Resilience
- First Mongo read after idle retries 3× with 0.4s backoff
- Failure → 503 "Service is waking up" (not 401)
- Prevents misleading "invalid credentials" on cold start

---

## 4. Recommendation Flow

### Complete Path: User Input → Recommendations

```
1. USER INPUT (Frontend)
   ├─ Text:     POST /api/text_emotion/ {text}        → Django → Modal (service token)
   ├─ Speech:   POST /speech_emotion (multipart)      → Modal (direct, user JWT)
   ├─ Facial:   POST /facial_emotion (multipart)      → Modal (direct, user JWT)

2. EMOTION DETECTION (Modal)
   ├─ Text:     BERT classifier → emotion label
   ├─ Speech:   SVC + MFCC (sklearn) → emotion label
   ├─ Facial:   FER + MTCNN → emotion label
   └─ All:      Fallback to "neutral" + degraded=true on any failure

3. RECOMMENDATION GENERATION (Modal)
   ├─ Emotion → query map → Deezer search
   ├─ History (optional) → EWMA + Markov → recurring mood
   ├─ Blend primary + recurring tracks via interleave
   ├─ Curated fallback (14 tracks) if Deezer fails
   └─ Return {emotion, recommendations[], degraded}

4. PERSONALIZATION (Django - AFTER Modal returns)
   ├─ L1 Mood Calibration:  UserProfile.mood_calibration
   │   {predicted: {actual: count}} → rewrite if count ≥ 3
   └─ L2 Bandit Re-rank:    UserProfile.taste_profile
       Beta-Bernoulli posterior over 22-dim features
       Thompson Sampling → reorder candidate list
       Cold-start safe: identity when events < 20

5. FRONTEND DISPLAY
   → ResultsPage renders track cards with 👍/👎/Deezer
   → Feedback → POST /api/feedback/ {kind, ...}
```

### Feedback / RL Pipeline

```
POST /api/feedback/ (Bearer JWT)
├─ kind=mood:     {predicted, actual, input_type, confidence?, session_id?}
│   → Insert to mood_feedback (TS collection)
│   → Bump UserProfile.mood_calibration[predicted][actual]
│
└─ kind=track:    {track_id, signal, context_emotion?, track?}
    → signal ∈ {like, unlike, open_deezer, clear}
    → Insert to track_feedback (TS collection) with features + seq
    → Set-vote semantics:
      - like/unlike: revert prior vote (exact features) → apply new
      - clear: revert prior vote → net zero
      - open_deezer: purely additive, never reverted
    → Update UserProfile.taste_profile (bandit posterior)

GET /api/feedback/tracks/?ids=...
  → Returns {feedback: {track_id: "like"|"unlike"}}
  → Used to restore button state after reload
```

---

## 5. Database

### Database Type
- **MongoDB Atlas** (cloud-managed)
- Connection via `mongoengine` ODM
- **No SQL database** - `DATABASES = {}` in Django settings

### Collections

| Collection | Defined In | Purpose |
|------------|------------|---------|
| `users` | `users/documents.py` | Auth-bearing accounts (replaces Django auth_user) |
| `user_profile` | `api/models.py` | Mood/listening history, saved recs, RL state |
| `mood_feedback` | `api/feedback_store.py` | Time-series: mood corrections (365-day TTL) |
| `track_feedback` | `api/feedback_store.py` | Time-series: track signals + features (365-day TTL) |
| `webauthn_credentials` | `users/documents.py` | Passkeys (many per user) |
| `webauthn_challenges` | `users/documents.py` | Single-use ceremony challenges |
| `backend_metrics` | `observability/store.py` | Django SRE metrics (30-day TTL) |
| `inference_metrics` | `modal_inference/metrics_store.py` | Modal SRE metrics (30-day TTL) |

### Key Documents

**User** (`users/documents.py`):
```python
username (unique), email (unique), password (PBKDF2), is_active, created_at
```

**UserProfile** (`api/models.py`):
```python
username (FK by value), mood_history[], listening_history[], recommendations[],
mood_calibration{predicted: {actual: count}}, taste_profile{alpha[22], beta[22], events}, created_at
```

**WebAuthnCredential** (`users/documents.py`):
```python
user_id, username, credential_id (unique), public_key (COSE), sign_count,
transports[], aaguid, device_type, backed_up, name, created_at, last_used_at
```

### Indexes
- `auto_create_index=False` on all documents (serverless pattern)
- Indexes managed once in Atlas, not per cold start
- Key indexes: `username` on users/user_profile, `credential_id` on webauthn_credentials

---

## 6. Redis

### Current Usage
- **Optional** - only if `CACHE_REDIS_URL` is set
- Default: `LocMemCache` (per-instance, not shared)
- If configured: `django.core.cache.backends.redis.RedisCache` (e.g., Upstash)
- Used for: Django cache framework (generic), not heavily utilized in current code
- **No Redis in Modal inference** - all caches are in-process `TTLCache`

### Modal In-Process Caches (not Redis)

| Cache | Key | TTL | Max Entries | Purpose |
|-------|-----|-----|-------------|---------|
| `text_emotion` | `text.strip().lower()` | 24h | 2048 | BERT deterministic output |
| `deezer_search` | `(query.lower(), limit)` | 1h | 256 | Deezer search results |
| `speech_emotion` | `sha256(upload_bytes)` | 6h | 256 | Defends retry storms |
| `facial_emotion` | `sha256(upload_bytes)` | 6h | 256 | Defends retry storms |

---

## 7. AI/Inference

### Modal Inference Service (ACTIVE - Production)

**Deployment**: Modal serverless (`modal deploy modal_app.py`)
- Scales to zero (`MIN_CONTAINERS=0`)
- CPU memory snapshots (`@modal.enter(snap=True)`) → 1-2s cold restore
- Max 5 containers (`MAX_CONTAINERS=5`) - hard cost ceiling
- Single container holds all 3 models (parallel load amortizes cold start)

**Models**:
| Model | Library | Weights | Output Labels |
|-------|---------|---------|---------------|
| Text | Transformers (BERT) | HF Hub → Modal Volume | sadness, joy, love, anger, fear, neutral |
| Speech | sklearn SVC + librosa MFCC | Bundled in image | calm, happy, sad, angry, fearful, disgust, surprised, neutral |
| Face | FER (Keras) + MTCNN | Bundled with fer | angry, disgust, fear, happy, sad, surprise, neutral |

**Endpoints** (all require Bearer JWT or service token):
- `GET /health` - liveness + cache + rate-limit stats
- `POST /text_emotion` - JSON `{text}` → EmotionResponse
- `POST /speech_emotion` - multipart file ≤12MB → EmotionResponse
- `POST /facial_emotion` - multipart file ≤12MB → EmotionResponse
- `POST /music_recommendation` - JSON `{emotion, market?, history?, genre?}` → EmotionResponse
- `GET /metrics` - SRE telemetry (service token only)

**Resilience**: Never returns 500 on main endpoints. Model failures → `degraded: true` + neutral fallback + curated tracks.

### ai_ml/ (LEGACY - Local Training Only)

- Contains training scripts for all three models
- Not used in production runtime
- Models trained locally → uploaded to HF Hub → pulled to Modal Volume
- `src/models/train_text_emotion.py`, `train_speech_emotion_model.py`, `train_facial_emotion_model.py`
- `emotion_models.ipynb` - exploration notebook
- **Status**: Reference/legacy. Production inference uses Modal service exclusively.

### Duplicate Implementations
- `ai_ml/src/rl/bandit.py` + `backend/api/bandit.py` - **SAME LOGIC** (backend is active)
- `ai_ml/src/rl/calibration.py` + `backend/api/calibration.py` - **SAME LOGIC** (backend is active)
- `ai_ml/src/rl/track_features.py` + `backend/api/track_features.py` - **SAME LOGIC** (backend is active)
- `ai_ml/src/recommendation/music_recommendation.py` - similar to Modal's but local Flask
- `ai_ml/src/recommendation/personalized_recommendation.py` - similar to Modal's personalization

---

## 8. Infrastructure

### Active Deployment (Verified)
| Component | Platform | Status |
|-----------|----------|--------|
| Frontend | Vercel | ✅ Live at moodify-app.vercel.app |
| Backend API | Vercel | ✅ Live at moodify-backend-api.vercel.app |
| ML Inference | Modal | ✅ Live at modal.run URL |
| Database | MongoDB Atlas | ✅ Configured via env |
| Metrics | MongoDB Atlas (TS) | ✅ Both services write |

### Reference/Optional Infrastructure
| Component | Purpose | Status |
|-----------|---------|--------|
| Docker Compose | Local dev stack | ✅ Working (MongoDB + backend + frontend) |
| Kubernetes | Self-host K8s | 📋 Manifests exist, not actively deployed |
| Helm | K8s package management | 📋 Charts exist |
| Terraform | Multi-cloud IaC | 📋 Modules exist (AWS/GCP/OCI) |
| Argo CD | GitOps | 📋 Manifests exist |
| Jenkins | CI/CD | 📋 Jenkinsfile exists |
| NGINX | Load balancer (self-host) | 📋 Config exists |

**Important**: Only Vercel + Modal is the canonical production path. All Kubernetes/Terraform/Helm/ArgoCD is **reference infrastructure** for self-hosting, not actively deployed.

---

## 9. Testing

### Test Suites

| Suite | Framework | Command | Tests | Coverage |
|-------|-----------|---------|-------|----------|
| Frontend | Jest + RTL | `npm test` | Snapshots + unit | `--coverage` available |
| Backend | pytest + mongomock | `pytest` | 221 tests | All offline (mongomock) |
| Modal Inference | pytest | `pytest` | 181 tests | Fast (171) + functional (10) |

### Backend Test Files (221 tests)
- `test_auth_endpoints.py` (17) - register, login, refresh, password reset
- `test_api_views.py` (12) - health, text_emotion proxy, music_rec proxy
- `test_history_endpoints.py` (14) - mood/listening/recommendations CRUD
- `test_profile_endpoints.py` (5) - profile read/update/delete
- `test_inference_client.py` (8) - Modal HTTP client retry behavior
- `test_functional_journey.py` (1) - E2E: register → login → analyse → save → fetch
- `test_users.py` (23) - User/UserProfile document tests
- `test_passkeys.py` (19) - WebAuthn ceremonies
- `test_personalisation_views.py` (10) - calibration + bandit integration
- `test_feedback.py` (20) - feedback endpoint + store
- `test_bandit.py` (6) - Thompson Sampling logic
- `test_calibration.py` (2) - calibration threshold logic
- `test_track_features.py` (5) - feature extraction
- `test_tokens.py` (1) - JWT encode/decode
- `test_documents.py` (1) - User document
- `test_authentication.py` (2) - MongoJWTAuthentication
- `test_metrics.py` (9) - observability recorder/store/middleware

### Modal Inference Test Files (181 tests)
- `test_service.py` (20) - full FastAPI surface
- `test_cache.py` (25) - TTLCache + endpoint integration
- `test_rate_limit.py` (28) - SlidingWindowLimiter + 429
- `test_metrics.py` (30) - recorder + store + /metrics
- `test_personalization.py` (18) - EWMA, Markov, blend
- `test_recommendation.py` (15) - Deezer mocks, fallback
- `test_auth.py` (8) - JWT + service token
- `test_config.py` (5) - env loading
- `test_download_models.py` (3) - HF download
- `test_inference_modules.py` (9) - model interfaces
- `test_schemas.py` (10) - Pydantic validation
- `test_functional.py` (10) - real models (auto-skipped without ML stack)

### Frontend Tests
- Snapshot tests for every screen (Landing, Home, Profile, Results, Recommendations, NotFound, ForgotPassword, Passkeys, PrivacyPolicy, TermsOfService)
- Component tests under `src/components/__tests__/`

---

## 10. Problems Identified

### CRITICAL
1. **No git repository** - This is a fresh copy, not a cloned repo. Need to initialize git before making changes.
2. **No `.env.example` with real values** - Root `.env.example` only has 6 lines, missing all required variables.
3. **Duplicate RL implementations** - `ai_ml/src/rl/` duplicates `backend/api/{bandit,calibration,track_features}.py`. Must consolidate.

### HIGH
4. **No API versioning** - All endpoints at `/users/`, `/api/` without version prefix.
5. **Inconsistent branding** - Everywhere says "Moodify", not "VibeStream".
6. **Root `.env.example` incomplete** - Missing: `JWT_SIGNING_KEY`, `MODAL_INFERENCE_URL`, `MODAL_SERVICE_TOKEN`, `WEBAUTHN_RP_ID`, `WEBAUTHN_EXPECTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, Sentry, Redis, etc.
7. **Frontend `.env.example`** only has 2 vars - should document all.
8. **Backend `.env.example`** exists but not comprehensive.

### MEDIUM
9. **Legacy `ai_ml/` directory** - Training code not needed for runtime. Could be archived or moved to separate repo.
10. **Legacy `data_analytics/`** - Spark/Hadoop scripts not used in production.
11. **Mobile app** - Optional, not part of core web platform.
12. **Multiple deployment configs** - Kubernetes/Helm/Terraform/ArgoCD are reference only, create noise.
13. **Index.html at root** - Legacy single-file demo, unused.
14. **composer.json, package.json at root** - Minimal/unused.
15. **Inconsistent env var naming** - `MONGO_DB_URI` vs `MONGO_URI`, `MODAL_INFERENCE_URL` vs `MODAL_API_URL`.

### LOW
16. **`manage_moodify.sh`** - Legacy management script.
17. **`manage_docker.sh`** - Redundant with Makefile.
18. **`jenkins_cicd.sh`** - Setup script, not needed if using GitHub Actions.
19. **`render.yaml`** - Render.com config, not used (Vercel is prod).
20. **`MOBILE_APPS.md`** - Mobile-specific doc, could be merged.

---

## 11. Phase 1 Action Plan Summary

Based on this audit, Phase 1 should:

1. **Initialize git repo** and create `vibestream-phase-1` branch
2. **Verify baseline** - run all tests, confirm working state
3. **Document architecture** - create clean `docs/ARCHITECTURE.md` (trim aspirational K8s stuff)
4. **Rebrand** - Moodify → VibeStream across all user-facing surfaces
5. **Restructure backend** - Organize into clear domains (auth, users, mood, recommendations, feedback, listening, analytics, integrations, common)
6. **Add API versioning** - `/api/v1/` prefix for all endpoints
7. **Remove legacy code** - Delete `ai_ml/`, `data_analytics/`, duplicate RL code, unused root files
8. **Clean configuration** - Comprehensive `.env.example` files, consistent naming
9. **Update documentation** - README, API docs, developer guide
10. **Final verification** - All tests pass, core flow works