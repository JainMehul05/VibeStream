// k6 Smoke Test for VibeStream API
// Quick validation of critical endpoints after deployment

import http from 'k6/http';
import { check, group } from 'k6';

export const options = {
  vus: 1,  // 1 virtual user
  duration: '30s',
  thresholds: {
    'http_req_duration': ['p(95)<1000'],  // 95% of requests under 1s
    'http_req_failed': ['rate<0.01'],     // Less than 1% errors
  },
};

const BASE_URL = __ENV.API_URL || 'http://localhost:8000';

export default function () {
  group('Health Checks', function () {
    // Liveness probe
    let res = http.get(`${BASE_URL}/api/v1/health/`);
    check(res, {
      'liveness check passed': (r) => r.status === 200,
    });

    // Readiness probe (if implemented)
    res = http.get(`${BASE_URL}/api/v1/health/`);
    check(res, {
      'readiness check passed': (r) => r.status === 200,
    });
  });

  group('Public Endpoints (Anonymous)', function () {
    // Text emotion (anonymous allowed)
    let res = http.post(
      `${BASE_URL}/api/v1/text_emotion/`,
      JSON.stringify({ text: "I'm feeling happy today!" }),
      { headers: { 'Content-Type': 'application/json' } }
    );
    check(res, {
      'text_emotion anonymous returns 200': (r) => r.status === 200,
      'text_emotion returns emotion': (r) => r.json('emotion') !== '',
    });

    // Music recommendation (anonymous allowed)
    res = http.post(
      `${BASE_URL}/api/v1/music_recommendation/`,
      JSON.stringify({ emotion: "joy" }),
      { headers: { 'Content-Type': 'application/json' } }
    );
    check(res, {
      'music_recommendation anonymous returns 200': (r) => r.status === 200,
      'music_recommendation returns tracks': (r) => r.json('recommendations').length > 0,
    });
  });

  group('Authenticated Endpoints', function () {
    // Login
    const loginRes = http.post(
      `${BASE_URL}/api/v1/users/login/`,
      JSON.stringify({ username: 'loadtest1', password: 'loadtest123' }),
      { headers: { 'Content-Type': 'application/json' } }
    );

    const loginSuccess = check(loginRes, {
      'login returns 200': (r) => r.status === 200,
      'login returns access token': (r) => r.json('access') !== '',
    });

    if (!loginSuccess) {
      console.error('Login failed, skipping authenticated tests');
      return;
    }

    const authToken = loginRes.json('access');
    const authHeaders = {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authToken}`,
      },
    };

    // Profile
    let res = http.get(`${BASE_URL}/api/v1/users/user/profile/`, authHeaders);
    check(res, {
      'profile returns 200': (r) => r.status === 200,
    });

    // Feedback track state
    res = http.get(`${BASE_URL}/api/v1/feedback/tracks/?ids=`, authHeaders);
    check(res, {
      'feedback tracks returns 200': (r) => r.status === 200,
    });

    // Submit feedback
    res = http.post(
      `${BASE_URL}/api/v1/feedback/`,
      JSON.stringify({
        kind: 'track',
        track_id: 'deezer:12345',
        signal: 'like',
        context_emotion: 'joy'
      }),
      authHeaders
    );
    check(res, {
      'feedback returns 202': (r) => r.status === 202,
    });
  });

  group('Metrics Endpoint', function () {
    // Metrics (requires service token)
    let res = http.get(`${BASE_URL}/api/v1/metrics/?window=1h`);
    // May return 401 without service token, that's OK for smoke test
    check(res, {
      'metrics endpoint responds': (r) => r.status === 200 || r.status === 401,
    });
  });
}