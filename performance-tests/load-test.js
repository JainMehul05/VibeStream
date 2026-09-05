// k6 Load Testing Script for VibeStream API
// Tests application performance under various load conditions

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const loginDuration = new Trend('login_duration');
const recommendDuration = new Trend('recommend_duration');
const feedbackDuration = new Trend('feedback_duration');
const textEmotionDuration = new Trend('text_emotion_duration');
const apiCalls = new Counter('api_calls');

// Test configuration
export const options = {
  stages: [
    // Warm-up
    { duration: '1m', target: 10 },

    // Ramp up to normal load
    { duration: '2m', target: 50 },

    // Stay at normal load
    { duration: '5m', target: 50 },

    // Ramp up to peak load
    { duration: '2m', target: 100 },

    // Stay at peak load
    { duration: '5m', target: 100 },

    // Spike test
    { duration: '1m', target: 200 },
    { duration: '2m', target: 200 },

    // Ramp down
    { duration: '2m', target: 0 },
  ],

  thresholds: {
    // HTTP errors should be less than 1%
    'errors': ['rate<0.01'],

    // 95% of requests should be below 2s
    'http_req_duration': ['p(95)<2000'],

    // Specific endpoint thresholds
    'http_req_duration{endpoint:login}': ['p(95)<1000'],
    'http_req_duration{endpoint:recommend}': ['p(95)<1500'],
    'http_req_duration{endpoint:text_emotion}': ['p(95)<3000'],
    'http_req_duration{endpoint:feedback}': ['p(95)<500'],

    // Success rate should be above 99%
    'http_req_failed': ['rate<0.01'],
  },
};

// Base URL (can be overridden via environment variable)
const BASE_URL = __ENV.API_URL || 'http://localhost:8000';
const MODAL_URL = __ENV.MODAL_URL || 'https://your-modal-url.modal.run';

// Test user credentials (create these in your test database)
const testUsers = [
  { username: 'loadtest1', password: 'loadtest123' },
  { username: 'loadtest2', password: 'loadtest123' },
  { username: 'loadtest3', password: 'loadtest123' },
  { username: 'loadtest4', password: 'loadtest123' },
  { username: 'loadtest5', password: 'loadtest123' },
];

const emotions = ['joy', 'sadness', 'love', 'anger', 'fear', 'neutral'];
const genres = ['pop', 'rock', 'hip-hop', 'electronic', 'r&b', 'country', 'jazz', 'classical'];

// Setup function - runs once before test
export function setup() {
  console.log(`Starting load test against ${BASE_URL}`);

  // Health check
  const healthRes = http.get(`${BASE_URL}/api/v1/health/`);
  check(healthRes, {
    'health check passed': (r) => r.status === 200,
  });

  return { startTime: new Date().toISOString() };
}

// Helper to login and get token
function login(user) {
  const loginPayload = JSON.stringify({
    username: user.username,
    password: user.password,
  });

  const loginParams = {
    headers: {
      'Content-Type': 'application/json',
    },
    tags: { endpoint: 'login' },
  };

  const loginRes = http.post(
    `${BASE_URL}/api/v1/users/login/`,
    loginPayload,
    loginParams
  );

  const loginSuccess = check(loginRes, {
    'login status is 200': (r) => r.status === 200,
    'login returns access token': (r) => r.json('access') !== '',
  });

  errorRate.add(!loginSuccess);
  loginDuration.add(loginRes.timings.duration);
  apiCalls.add(1);

  if (loginSuccess) {
    return loginRes.json('access');
  }
  return null;
}

// Main test scenario
export default function (data) {
  const user = testUsers[Math.floor(Math.random() * testUsers.length)];
  const authToken = login(user);

  if (!authToken) {
    console.error(`Login failed for ${user.username}`);
    return;
  }

  sleep(1);

  // Authenticated API calls
  const authHeaders = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`,
    },
  };

  // 1. Text Emotion Detection (20% of requests)
  if (Math.random() < 0.2) {
    group('Text Emotion', function () {
      const texts = [
        "I'm feeling great today!",
        "This is the worst day ever.",
        "I love this song so much.",
        "I'm really angry right now.",
        "I'm scared of what's coming.",
        "Just another normal day.",
      ];
      const text = texts[Math.floor(Math.random() * texts.length)];

      const analyzeRes = http.post(
        `${BASE_URL}/api/v1/text_emotion/`,
        JSON.stringify({ text }),
        {
          ...authHeaders,
          tags: { endpoint: 'text_emotion' },
        }
      );

      const success = check(analyzeRes, {
        'text_emotion status is 200': (r) => r.status === 200,
        'text_emotion returns emotion': (r) => r.json('emotion') !== '',
      });

      errorRate.add(!success);
      textEmotionDuration.add(analyzeRes.timings.duration);
      apiCalls.add(1);
    });
    sleep(1);
  }

  // 2. Music Recommendation (50% of requests)
  if (Math.random() < 0.5) {
    group('Music Recommendation', function () {
      const emotion = emotions[Math.floor(Math.random() * emotions.length)];
      const history = [];
      // Add some history for 30% of requests
      if (Math.random() < 0.3) {
        for (let i = 0; i < Math.floor(Math.random() * 5) + 1; i++) {
          history.push(emotions[Math.floor(Math.random() * emotions.length)]);
        }
      }
      const genre = Math.random() < 0.2 ? genres[Math.floor(Math.random() * genres.length)] : null;

      const payload = { emotion, history };
      if (genre) payload.genre = genre;

      const recsRes = http.post(
        `${BASE_URL}/api/v1/music_recommendation/`,
        JSON.stringify(payload),
        {
          ...authHeaders,
          tags: { endpoint: 'recommend' },
        }
      );

      const success = check(recsRes, {
        'recommendations status is 200': (r) => r.status === 200,
        'recommendations returns tracks': (r) => r.json('recommendations').length > 0,
      });

      errorRate.add(!success);
      recommendDuration.add(recsRes.timings.duration);
      apiCalls.add(1);

      // Store track IDs for feedback
      if (success && recsRes.json('recommendations').length > 0) {
        const tracks = recsRes.json('recommendations');
        const trackId = tracks[0].external_url || tracks[0].name; // Use external_url or name as track_id
        const contextEmotion = recsRes.json('emotion');

        sleep(1);

        // 3. Submit Feedback (30% of recommendation requests)
        if (Math.random() < 0.3) {
          group('Submit Feedback', function () {
            const signals = ['like', 'unlike', 'open_deezer'];
            const signal = signals[Math.floor(Math.random() * signals.length)];

            const feedbackPayload = {
              kind: 'track',
              track_id: trackId,
              signal: signal,
              context_emotion: contextEmotion,
            };

            const feedbackRes = http.post(
              `${BASE_URL}/api/v1/feedback/`,
              JSON.stringify(feedbackPayload),
              {
                ...authHeaders,
                tags: { endpoint: 'feedback' },
              }
            );

            const fbSuccess = check(feedbackRes, {
              'feedback status is 202': (r) => r.status === 202,
            });

            errorRate.add(!fbSuccess);
            feedbackDuration.add(feedbackRes.timings.duration);
            apiCalls.add(1);
          });
        }
      }
    });
    sleep(2);
  }

  // 4. Mood Feedback (10% of requests)
  if (Math.random() < 0.1) {
    group('Mood Feedback', function () {
      const predicted = emotions[Math.floor(Math.random() * emotions.length)];
      const actual = emotions[Math.floor(Math.random() * emotions.length)];
      const inputTypes = ['text', 'speech', 'facial'];
      const inputType = inputTypes[Math.floor(Math.random() * inputTypes.length)];

      const feedbackPayload = {
        kind: 'mood',
        predicted: predicted,
        actual: actual,
        input_type: inputType,
        confidence: Math.random(),
      };

      const feedbackRes = http.post(
        `${BASE_URL}/api/v1/feedback/`,
        JSON.stringify(feedbackPayload),
        {
          ...authHeaders,
          tags: { endpoint: 'feedback' },
        }
      );

      const success = check(feedbackRes, {
        'mood feedback status is 202': (r) => r.status === 202,
      });

      errorRate.add(!success);
      feedbackDuration.add(feedbackRes.timings.duration);
      apiCalls.add(1);
    });
    sleep(1);
  }

  // 5. Profile / History (10% of requests)
  if (Math.random() < 0.1) {
    group('Get Profile', function () {
      const profileRes = http.get(
        `${BASE_URL}/api/v1/users/user/profile/`,
        {
          ...authHeaders,
          tags: { endpoint: 'profile' },
        }
      );

      const success = check(profileRes, {
        'profile status is 200': (r) => r.status === 200,
      });

      errorRate.add(!success);
      recommendDuration.add(profileRes.timings.duration); // reuse metric
      apiCalls.add(1);
    });
    sleep(1);
  }

  sleep(Math.random() * 3 + 1);  // Random sleep 1-4 seconds
}

// Teardown function - runs once after test
export function teardown(data) {
  console.log(`Load test completed. Started at ${data.startTime}`);
}