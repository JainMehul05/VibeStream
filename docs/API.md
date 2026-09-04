# VibeStream API Reference

**Base URL**: `https://vibestream-backend-api.vercel.app/api/v1`

**Version**: v1

**Authentication**: Bearer JWT (HS256) - obtain via `/users/login/` or `/users/passkeys/login/complete/`

---

## Auth Endpoints

### Register User
```
POST /users/register/
```
**Body**: `{username, email, password}`
**Response**: `201 {message: "User created successfully."}`

### Login (username or email)
```
POST /users/login/
```
**Body**: `{username, password}` - username field accepts either username or email
**Response**: `200 {access, refresh}`

### Refresh Access Token
```
POST /users/token/refresh/
```
**Body**: `{refresh}`
**Response**: `200 {access, refresh}`

### Validate Token
```
GET /users/validate_token/
```
**Auth**: Required
**Response**: `200 {message: "Token is valid.", username}`

### Forgot Password - Step 1
```
POST /users/verify-username-email/
```
**Body**: `{username, email}`
**Response**: `200 {message: "Username and email combination verified."}`

### Forgot Password - Step 2
```
POST /users/reset-password/
```
**Body**: `{username, new_password}`
**Response**: `200 {message: "Password reset successfully."}`

---

## Passkeys / WebAuthn

### Register Begin
```
POST /users/passkeys/register/begin/
```
**Auth**: Required
**Response**: `200 {options, flowId}`

### Register Complete
```
POST /users/passkeys/register/complete/
```
**Auth**: Required
**Body**: `{flowId, credential, name?}`
**Response**: `201 {passkey}`

### Login Begin (usernameless supported)
```
POST /users/passkeys/login/begin/
```
**Body**: `{username?}` - omit for usernameless
**Response**: `200 {options, flowId}`

### Login Complete
```
POST /users/passkeys/login/complete/
```
**Body**: `{flowId, credential}`
**Response**: `200 {access, refresh, username}`

### List Passkeys
```
GET /users/passkeys/
```
**Auth**: Required
**Response**: `200 [{passkey_id, name, transports, backed_up, last_used_at, ...}]`

### Rename Passkey
```
PATCH /users/passkeys/<passkey_id>/
```
**Auth**: Required
**Body**: `{name}`

### Delete Passkey
```
DELETE /users/passkeys/<passkey_id>/
```
**Auth**: Required

---

## Profile Endpoints

### Get Profile
```
GET /users/user/profile/
```
**Auth**: Required
**Response**: `200 {id, username, email, listening_history[], mood_history[], recommendations[]}`

### Update Profile
```
PUT /users/user/profile/update/
```
**Auth**: Required
**Body**: `{email?, username?}`
**Response**: `200 {message, username, access?, refresh?}`

### Delete Account
```
DELETE /users/user/profile/delete/
```
**Auth**: Required
**Response**: `200 {message: "Profile deleted successfully."}`

---

## History Endpoints

### Mood History
```
GET /users/mood_history/<user_id>/
POST /users/mood_history/<user_id>/  {mood}
DELETE /users/mood_history/<user_id>/  {mood}
```
**Auth**: Required (user_id must match authenticated user)

### Listening History
```
GET /users/listening_history/<user_id>/
POST /users/listening_history/<user_id>/  {track}
DELETE /users/listening_history/<user_id>/  {track}
```
**Auth**: Required

### Saved Recommendations
```
GET /users/recommendations/<user_id>/
POST /users/recommendations/<user_id>/  {recommendations: [...]}
DELETE /users/recommendations/<user_id>/
```
**Auth**: Required

---

## Inference & Recommendation Endpoints

### Health Check
```
GET /api/health/
```
**Auth**: None
**Response**: `200 {status: "ok"}`

### Text Emotion Detection
```
POST /api/text_emotion/
```
**Auth**: Optional (if authenticated, applies mood calibration)
**Body**: `{text: string (1-5000 chars)}`
**Response**: `200 {emotion, recommendations[], degraded, market, calibrated_from?}`

### Music Recommendations
```
POST /api/music_recommendation/
```
**Auth**: Optional (if authenticated and warm, applies bandit re-rank)
**Body**: `{emotion, market?, history?, genre?}`
**Response**: `200 {emotion, recommendations[], degraded, market}`

---

## Feedback / RL Endpoints

### Submit Feedback
```
POST /api/feedback/
```
**Auth**: Required
**Body (mood)**: `{kind: "mood", predicted, actual, input_type, confidence?, session_id?}`
**Body (track)**: `{kind: "track", track_id, signal, context_emotion?, track?}`
**Signal values**: `like`, `unlike`, `open_deezer`, `clear`
**Response**: `202 {message: "Feedback recorded."}`

### Get Track Feedback State
```
GET /api/feedback/tracks/?ids=<id1,id2,...>
```
**Auth**: Required
**Response**: `200 {feedback: {track_id: "like"|"unlike"}}`

---

## Metrics (Admin)

### Get Metrics
```
GET /api/metrics/?window=1h&endpoint=
```
**Auth**: Service token (ADMIN_METRICS_TOKEN)
**Windows**: `5m`, `15m`, `1h`, `6h`, `24h`, `7d`, `30d`
**Response**: Aggregated error rates, latency percentiles, throughput per endpoint

---

## Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Bad Request - validation failed |
| 401 | Unauthorized - invalid/expired token |
| 403 | Forbidden - resource belongs to another user |
| 404 | Not Found |
| 409 | Conflict - username/email taken |
| 422 | Unprocessable Entity - validation error |
| 502 | Bad Gateway - inference service unavailable |
| 503 | Service Unavailable - database warming up |

---

## Rate Limits

- **Anonymous**: 60 requests/minute
- **Authenticated**: 240 requests/minute
- **Passkey endpoints**: Included in above limits

Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
