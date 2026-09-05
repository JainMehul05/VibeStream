// k6 Stress Test for VibeStream API
// Tests application behavior under extreme load

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

const errorRate = new Rate('errors');
const recommendDuration = new Trend('recommend_duration');
const apiCalls = new Counter('api_calls');

export const options = {
  stages: [
    { duration: '2m', target: 50 },
    { duration: '5m', target: 100 },
    { duration: '2m', target: 200 },
    { duration: '5m', target: 300 },
    { duration: '2m', target: 400 },
    { duration: '5m', target: 500 },
    { duration: '10m', target: 500 },  // Sustained peak
    { duration: '5m', target: 0 },
  ],

  thresholds: {
    'errors': ['rate<0.05'],  // Allow 5% errors under stress
    'http_req_duration': ['p(95)<5000'],  // 95% under 5s
    'http_req_failed': ['rate<0.05'],
  },
};

const BASE_URL = __ENV.API_URL || 'https://api.vibestream.example.com';

export default function () {
  // Simplified stress test - just hammer the recommendation endpoint
  const emotions = ['joy', 'sadness', 'love', 'anger', 'fear', 'neutral'];
  const emotion = emotions[Math.floor(Math.random() * emotions.length)];

  group('Stress Recommendation', function () {
    const payload = JSON.stringify({
      emotion: emotion,
      history: [],
    });

    const res = http.post(
      `${BASE_URL}/api/v1/music_recommendation/`,
      payload,
      {
        headers: { 'Content-Type': 'application/json' },
        tags: { endpoint: 'recommend' },
      }
    );

    const success = check(res, {
      'status is 200 or 429 or 503': (r) => [200, 429, 503].includes(r.status),
    });

    errorRate.add(!success);
    recommendDuration.add(res.timings.duration);
    apiCalls.add(1);
  });

  sleep(0.1);  // Minimal sleep for max throughput
}