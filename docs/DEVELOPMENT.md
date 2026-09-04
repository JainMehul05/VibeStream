# VibeStream Development Guide

## Prerequisites

- **Node.js** 18+ (for frontend)
- **Python** 3.11+ (for backend)
- **MongoDB Atlas** account (or local MongoDB)
- **Modal** account (for ML inference)
- **Vercel** account (for deployment)
- **Git**

---

## Quick Start (Local Development)

### 1. Clone & Install

```bash
git clone https://github.com/JainMehul05/VibeStream.git
cd VibeStream-Emotion-Music-App

# Install frontend
cd frontend
npm ci

# Install backend
cd ../backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Backend
cd backend
cp .env.example .env
# Edit .env with your values:
# - MONGO_DB_URI (MongoDB Atlas connection string)
# - JWT_SIGNING_KEY (shared with Modal)
# - MODAL_INFERENCE_URL (from modal serve)
# - MODAL_SERVICE_TOKEN (shared with Modal)
# - WEBAUTHN_RP_ID=localhost
# - WEBAUTHN_EXPECTED_ORIGINS=http://localhost:3000,http://localhost:3001

# Frontend
cd ../frontend
cp .env.example .env
# Edit .env:
# REACT_APP_API_URL=http://localhost:8000
# REACT_APP_MODAL_API_URL=<your modal serve URL>
```

### 3. Run Services

```bash
# Terminal 1: Backend
cd backend
source .venv/bin/activate
python manage.py runserver

# Terminal 2: Frontend
cd frontend
npm start

# Terminal 3: Modal Inference (in modal_inference/)
cd modal_inference
source .venv/bin/activate
modal serve modal_app.py
```

### 4. Verify

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/swagger/
- Modal Health: (URL from `modal serve`)

---

## Running Tests

### Frontend
```bash
cd frontend
npm test -- --watchAll=false --passWithNoTests
```

### Backend (requires MongoDB - uses mongomock)
```bash
cd backend
source .venv/bin/activate
pytest -q
```

### Modal Inference
```bash
cd modal_inference
source .venv/bin/activate
# Fast tests (no ML stack)
pip install -r requirements-dev.txt
pytest tests/ -q -k "not functional"

# Full tests (requires ML deps)
pip install -r requirements.txt
pytest tests/ -q
```

---

## Project Structure

```
VibeStream-Emotion-Music-App/
├── backend/                 # Django REST API
│   ├── api/                 # Emotion proxy, recommendations, feedback
│   ├── users/               # Auth, profiles, passkeys, history
│   ├── integrations/        # External API clients (Modal)
│   ├── common/              # Shared utilities
│   ├── observability/       # SRE metrics
│   └── backend/             # Django settings, urls, wsgi
├── frontend/                # React SPA (CRA)
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # Route-level pages
│   │   ├── services/        # API clients (auth, feedback, etc.)
│   │   ├── context/         # React Context providers
│   │   └── config.js        # API URLs
│   └── public/
├── modal_inference/         # ML Inference on Modal
│   ├── service.py           # FastAPI app
│   ├── modal_app.py         # Modal deployment config
│   ├── inference/           # Text/Speech/Face models
│   ├── recommendation/      # Deezer + personalization
│   └── tests/
├── ai_ml/                   # Legacy training code (reference)
├── docker-compose.yml       # Local dev stack
├── Makefile                 # Common tasks
└── docs/                    # Documentation
```

---

## Key Development Patterns

### Authentication
- All API calls use `Authorization: Bearer <access_token>`
- `frontend/src/services/auth.js` handles token storage, 401→refresh, and claims
- `installAuthInterceptor()` sets up axios interceptors at app start

### API Calls
- Use `API_V1_URL` from `frontend/src/config.js` for all Django endpoints
- Speech/Facial uploads go directly to Modal (`MODAL_API_URL`)
- Text emotion + music recommendation proxy through Django (`/api/v1/`)

### State Management
- **Tokens**: localStorage (`token`, `refresh_token`)
- **Theme**: `DarkModeContext` + `localStorage.darkMode` + `body.classList`
- **Auth events**: Custom `vibestream:auth-change` event

### Adding New API Endpoints

1. **Backend**: Add view in appropriate app (`api/`, `users/`, etc.)
2. **URLs**: Register in app's `urls.py` (mounted at `/api/v1/`)
3. **Frontend**: Add service function in `frontend/src/services/`
4. **Tests**: Add test cases in respective test directories

---

## Environment Variables

### Backend (`.env`)
| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Django secret |
| `DEBUG` | No | Default `False` |
| `ALLOWED_HOSTS` | No | Comma-separated hosts |
| `MONGO_DB_URI` | Yes | MongoDB Atlas connection string |
| `MONGO_DB_NAME` | No | Default `emotion_based_music_db` |
| `JWT_SIGNING_KEY` | Yes | **Must match Modal** |
| `JWT_ACCESS_TOKEN_DAYS` | No | Default `7` |
| `JWT_REFRESH_TOKEN_DAYS` | No | Default `14` |
| `WEBAUTHN_RP_ID` | No | Frontend bare domain (e.g., `vibestream-app.vercel.app`) |
| `WEBAUTHN_RP_NAME` | No | Default `VibeStream` |
| `WEBAUTHN_EXPECTED_ORIGINS` | No | Comma-separated frontend origins |
| `MODAL_INFERENCE_URL` | Yes | Modal service URL |
| `MODAL_SERVICE_TOKEN` | Yes | **Must match Modal** |
| `CORS_ALLOW_ALL_ORIGINS` | No | Default `True` |
| `CORS_ALLOWED_ORIGINS` | No | When above is `False` |
| `CACHE_REDIS_URL` | No | Redis URL for shared cache |
| `SENTRY_DSN` | No | Enable Sentry |
| `METRICS_ENABLED` | No | Default `True` |

### Frontend (`.env`)
| Variable | Required | Description |
|----------|----------|-------------|
| `REACT_APP_API_URL` | Yes | Django API URL |
| `REACT_APP_MODAL_API_URL` | Yes | Modal inference URL |
| `REACT_APP_SENTRY_DSN` | No | Sentry DSN |

### Modal Inference
| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TEXT_MODEL_REPO` | Yes | Hugging Face repo for text model |
| `JWT_SIGNING_KEY` | Yes | **Must match Django** |
| `MODAL_SERVICE_TOKEN` | Yes | **Must match Django** |
| `ALLOWED_ORIGINS` | No | CORS origins |
| `RATE_LIMIT_ENABLED` | No | Default `1` |

---

## Deployment

### Production (Vercel + Modal)

```bash
# Deploy Modal inference
cd modal_inference
modal run modal_app.py::download_models  # First time only
modal deploy modal_app.py

# Deploy Frontend & Backend to Vercel
vercel link  # in frontend/ and backend/
# Set env vars in Vercel dashboard
vercel deploy --prod  # in both directories

# Or use Makefile
make deploy-prod
```

### Docker Compose (Local Full Stack)

```bash
MODAL_INFERENCE_URL=<modal-serve-url> docker compose up -d
# Frontend: localhost:3000
# Backend: localhost:8000
# MongoDB: localhost:27017
```

---

## Code Quality

### Linting
```bash
# Frontend
cd frontend && npx eslint --max-warnings=0 src

# Backend
cd backend && source .venv/bin/activate && ruff check .

# Modal
cd modal_inference && source .venv/bin/activate && ruff check .
```

### Formatting
```bash
# Frontend
cd frontend && npx prettier -w "src/**/*.{js,jsx,json,css}"

# Backend
cd backend && source .venv/bin/activate && ruff format .

# Modal
cd modal_inference && source .venv/bin/activate && ruff format .
```

### Makefile Commands
```bash
make help              # Show all targets
make install           # Install all workspaces
make dev               # Run frontend + backend
make test              # Run all test suites
make lint              # Run all linters
make fmt               # Format all code
make compose-up        # Docker compose up
make deploy-prod       # Full production deploy
```

---

## Debugging Tips

### Backend Cold Start (503)
- First request after idle may return 503 "Service is waking up"
- Frontend auth interceptor auto-retries
- Check MongoDB Atlas connection pooling

### Passkey Ceremonies Failing
- Verify `WEBAUTHN_RP_ID` matches frontend domain exactly (no scheme/port)
- Verify `WEBAUTHN_EXPECTED_ORIGINS` includes full frontend origin
- Check browser console for WebAuthn errors

### Modal Inference Issues
- Check `/health` endpoint for model loading status
- Cold start ~1-2s with memory snapshots
- `degraded: true` = model fallback, check logs

### CORS Issues
- Backend: `CORS_ALLOWED_ORIGINS` must include frontend origin
- Modal: `ALLOWED_ORIGINS` must include frontend origin
- Credentials: `False` (header-based auth)

---

## Useful Commands

```bash
# Check Django migrations (no SQL DB in prod)
cd backend && python manage.py makemigrations --dry-run --verbosity=3

# Open Django shell
cd backend && python manage.py shell

# View MongoDB collections (requires Atlas connection)
# Use MongoDB Compass or mongosh

# Modal logs
modal app logs vibestream-inference -f

# Frontend build
cd frontend && npm run build
```
