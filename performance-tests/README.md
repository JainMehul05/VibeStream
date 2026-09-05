# Performance Tests for VibeStream

This directory contains load testing scripts for the VibeStream API.

## Available Test Suites

### 1. k6 Tests (Recommended for Production)

Requires [k6](https://k6.io/docs/getting-started/installation/) installed.

```bash
# Smoke test (quick validation)
k6 run smoke-test.js -e API_URL=http://localhost:8000

# Full load test
k6 run load-test.js -e API_URL=http://localhost:8000

# Stress test (extreme load)
k6 run stress-test.js -e API_URL=https://api.vibestream.example.com
```

#### Test Scenarios

| Test | Duration | Max VUs | Purpose |
|------|----------|---------|---------|
| smoke-test.js | 30s | 1 | Quick CI/CD validation |
| load-test.js | ~18m | 200 | Realistic load pattern |
| stress-test.js | ~31m | 500 | Breaking point analysis |

#### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://localhost:8000` | Base URL of the Django API |
| `MODAL_URL` | `https://your-modal-url.modal.run` | Modal inference service URL |

### 2. Locust Tests (Python-based, No External Dependencies)

```bash
# Install dependencies
pip install locust

# Run with web UI
locust -f locustfile.py --host=http://localhost:8000

# Run headless (CI/CD)
locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 10 -t 5m --csv=results
```

#### User Types

| Class | Weight | Description |
|-------|--------|-------------|
| `VibeStreamUser` | 1 | Authenticated user (full workflow) |
| `AnonymousUser` | 1 | Public API access only |

#### Tags for Filtering

```bash
# Run only recommendation tests
locust -f locustfile.py --tags=recommendation

# Run only authenticated tests
locust -f locustfile.py --tags=feedback,profile

# Exclude stress tests
locust -f locustfile.py --exclude-tags=stress
```

### 3. Running in CI/CD

```yaml
# GitHub Actions example
- name: Run Performance Tests
  run: |
    # Start services
    docker-compose up -d
    
    # Wait for readiness
    sleep 30
    
    # Run smoke test
    k6 run performance-tests/smoke-test.js -e API_URL=http://localhost:8000
    
    # Run load test (optional, for release branches)
    if [ "${{ github.ref }}" == "refs/heads/main" ]; then
      k6 run performance-tests/load-test.js -e API_URL=http://localhost:8000
    fi
```

### Test Endpoints Covered

| Endpoint | Authenticated | Anonymous | Weight |
|----------|---------------|-----------|--------|
| `GET /api/v1/health/` | ✓ | ✓ | High |
| `POST /api/v1/text_emotion/` | ✓ | ✓ | Medium |
| `POST /api/v1/music_recommendation/` | ✓ | ✓ | High |
| `POST /api/v1/feedback/` | ✓ | ✗ | Medium |
| `GET /api/v1/feedback/tracks/` | ✓ | ✗ | Low |
| `GET /api/v1/users/user/profile/` | ✓ | ✗ | Low |
| `GET /api/v1/metrics/` | Service token | ✗ | Very Low |

### Test Data Requirements

For authenticated tests, create test users in your database:

```bash
# Using Django shell
python manage.py shell -c "
from users.documents import User
from users.tokens import issue_tokens
for i in range(1, 6):
    User.objects.create_user(f'loadtest{i}', 'loadtest{i}@test.com', 'loadtest123')
"
```

### Interpreting Results

| Metric | Target | Action if Exceeded |
|--------|--------|-------------------|
| `http_req_duration p95` | < 2s (load), < 5s (stress) | Optimize DB queries, add caching |
| `http_req_failed rate` | < 1% (load), < 5% (stress) | Check error logs, scale workers |
| `errors rate` | < 1% (load), < 5% (stress) | Investigate application errors |
| `login_duration p95` | < 1s | Optimize auth/DB |
| `recommend_duration p95` | < 1.5s | Check Modal/Redis/Mongo |

### Local Development Testing

```bash
# 1. Start local services
docker-compose up -d

# 2. Run Django
cd backend && python manage.py runserver

# 3. Run Modal (in separate terminal)
cd modal_inference && modal serve modal_app.py

# 4. Run smoke test
k6 run performance-tests/smoke-test.js -e API_URL=http://localhost:8000
```

### Performance Baselines (Target)

| Metric | p50 | p95 | p99 |
|--------|-----|-----|-----|
| `GET /health` | < 10ms | < 50ms | < 100ms |
| `POST /text_emotion` | < 200ms | < 800ms | < 2s |
| `POST /music_recommendation` | < 300ms | < 1s | < 2s |
| `POST /feedback` | < 50ms | < 200ms | < 500ms |
| `GET /profile` | < 50ms | < 200ms | < 500ms |

### Continuous Performance Monitoring

Track these metrics over time in your observability platform:

1. **API Latency** - p50, p95, p99 per endpoint
2. **Error Rates** - 4xx/5xx by endpoint
3. **Throughput** - requests/second
4. **Cache Hit Rate** - Redis recommendation cache
5. **Queue Depth** - Feedback event queue length
6. **Worker Processing Time** - Feedback event processing duration
7. **Database Query Time** - MongoDB slow query log
8. **Modal Inference Latency** - Model inference time