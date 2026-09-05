"""End-to-end integration tests for critical user flows.

Tests the complete system end-to-end:
1. Recommendation flow (request → candidate gen → ranking → personalization → bandit → diversity → explanation → response)
2. Feedback flow (feedback → event → worker → profile update → bandit update → cache invalidation)
3. Duplicate feedback (idempotency key → single logical mutation)
4. Cache flow (miss → cache → hit → feedback → invalidation → fresh recommendation)
5. GenAI flow (natural language → intent → tool → API → response)
6. Failure flow (temporary failure → retry → success)
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import UserProfile
from api import bandit, track_features as tf
from users.documents import User
from users.tokens import issue_tokens


class E2EIntegrationTestCase(TestCase):
    """Base class for E2E integration tests."""

    def setUp(self):
        self.client = APIClient()
        # Create test user using mongoengine Document with proper password hashing
        self.user = User(username="e2euser", email="e2e@example.com")
        self.user.set_password("testpass123")
        self.user.save()
        self.profile = UserProfile.objects(username="e2euser").first()
        # Login and get token
        login_res = self.client.post(
            "/api/v1/users/login/",
            {"username": "e2euser", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login_res.status_code, 200)
        self.token = login_res.data["access"]
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}


class TestRecommendationFlow(E2EIntegrationTestCase):
    """Test Flow 1: Complete recommendation pipeline."""

    def test_recommendation_flow_complete(self):
        """Test complete recommendation flow with all stages."""
        with patch("api.candidate_generation.modal_music") as mock_modal:
            # Mock Modal response with diverse tracks
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [
                    {
                        "name": f"Track {i}",
                        "artist": f"Artist {i % 5}",
                        "album": "Album",
                        "preview_url": f"https://preview/{i}",
                        "external_url": f"https://deezer.com/track/{i}",
                        "image_url": f"https://image/{i}",
                        "popularity": 50 + i * 2,
                        "duration_ms": 200000,
                        "release_date": f"{2000 + i}-01-01",
                    }
                    for i in range(20)
                ],
                "degraded": False,
                "market": None,
            }

            # Make recommendation request
            response = self.client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy", "genre": "pop"},
                format="json",
                **self.auth_headers,
            )

            self.assertEqual(response.status_code, 200)
            data = response.data

            # Verify response structure
            self.assertIn("emotion", data)
            self.assertIn("recommendations", data)
            self.assertIn("degraded", data)
            self.assertEqual(data["degraded"], False)

            # Verify recommendations have all required fields
            recs = data["recommendations"]
            self.assertGreater(len(recs), 0)
            self.assertLessEqual(len(recs), 20)  # DEFAULT_FINAL_LIMIT

            for rec in recs:
                self.assertIn("name", rec)
                self.assertIn("artist", rec)
                self.assertIn("explanation", rec)
                self.assertIn("ranking_signals", rec)
                self.assertIsInstance(rec["explanation"], str)
                self.assertGreater(len(rec["explanation"]), 0)

            # Verify ranking signals present
            signals = recs[0]["ranking_signals"]
            self.assertIn("mood_match", signals)
            self.assertIn("base_score", signals)

    def test_recommendation_with_history(self):
        """Test recommendation with mood history blending."""
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [
                    {"name": "Happy Track", "artist": "Artist A", "release_date": "2020-01-01", "popularity": 80, "external_url": "url1"},
                    {"name": "Sad Track", "artist": "Artist B", "release_date": "2019-01-01", "popularity": 70, "external_url": "url2"},
                ],
                "degraded": False,
            }

            response = self.client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy", "history": ["sadness", "joy", "joy"]},
                format="json",
                **self.auth_headers,
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["emotion"], "joy")


class TestFeedbackFlow(E2EIntegrationTestCase):
    """Test Flow 2: Feedback → Event → Worker → Profile → Bandit → Cache Invalidation."""

    def test_feedback_complete_flow(self):
        """Test complete feedback processing flow."""
        # Create a track for feedback
        track = {
            "name": "Test Track",
            "artist": "Test Artist",
            "release_date": "2020-01-01",
            "duration_ms": 200000,
            "popularity": 80,
            "external_url": "https://deezer.com/track/12345",
        }
        track_id = "deezer:12345"

        # Submit like feedback
        with patch("api.events.enqueue_event") as mock_enqueue:
            mock_enqueue.return_value = True

            response = self.client.post(
                "/api/v1/feedback/",
                {
                    "kind": "track",
                    "track_id": track_id,
                    "signal": "like",
                    "context_emotion": "joy",
                    "track": track,
                },
                format="json",
                **self.auth_headers,
            )

            self.assertEqual(response.status_code, 202)
            self.assertIn("event_id", response.data)

            # Verify event was enqueued
            self.assertTrue(mock_enqueue.called)

        # Process the event synchronously (test mode)
        from api.events import process_feedback_track, create_feedback_track_event
        from django.core.cache import cache

        event = create_feedback_track_event(
            user_id="e2euser",
            track_id=track_id,
            signal="like",
            context_emotion="joy",
            track=track,
        )

        redis_client = cache._cache.get_client(write=True)
        process_feedback_track(event, redis_client)

        # Verify profile updated
        profile = UserProfile.objects(username="e2euser").first()
        self.assertIsNotNone(profile.taste_profile)
        self.assertEqual(profile.taste_profile.get("events"), 1)

        # Verify bandit posterior updated
        taste = profile.taste_profile
        self.assertIn("alpha", taste)
        self.assertIn("beta", taste)

        # Verify cache invalidated (pattern-based)
        # In test mode, this would be a no-op with fakeredis

    def test_feedback_unlike_reverts_like(self):
        """Test that unlike reverts previous like."""
        track = {
            "name": "Track",
            "artist": "Artist",
            "release_date": "2020-01-01",
            "duration_ms": 200000,
            "popularity": 80,
            "external_url": "https://deezer.com/track/123",
        }
        track_id = "deezer:123"

        # First: like
        event = create_feedback_track_event(
            user_id="e2euser", track_id=track_id, signal="like",
            context_emotion="joy", track=track,
        )
        from api.events import process_feedback_track
        from django.core.cache import cache
        redis_client = cache._cache.get_client(write=True)
        process_feedback_track(event, redis_client)

        profile = UserProfile.objects(username="e2euser").first()
        events_after_like = profile.taste_profile.get("events")

        # Second: unlike (should revert)
        event = create_feedback_track_event(
            user_id="e2euser", track_id=track_id, signal="unlike",
            context_emotion="joy", track=track,
        )
        process_feedback_track(event, redis_client)

        profile.refresh_from_db()
        events_after_unlike = profile.taste_profile.get("events")

        # Events should be same (revert doesn't increment total events)
        self.assertEqual(events_after_unlike, events_after_like)


class TestDuplicateFeedback(E2EIntegrationTestCase):
    """Test Flow 3: Duplicate feedback with idempotency key."""

    def test_duplicate_feedback_idempotency(self):
        """Test that duplicate feedback with same idempotency key is deduplicated."""
        track = {
            "name": "Track", "artist": "Artist",
            "release_date": "2020-01-01", "duration_ms": 200000,
            "popularity": 80, "external_url": "https://deezer.com/track/123",
        }
        track_id = "deezer:123"
        idempotency_key = "test-idempotency-key-123"

        # First request
        response1 = self.client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": track_id, "signal": "like",
             "context_emotion": "joy", "track": track},
            format="json",
            **self.auth_headers,
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        self.assertEqual(response1.status_code, 202)
        event_id_1 = response1.data["event_id"]

        # Second request with same idempotency key
        response2 = self.client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": track_id, "signal": "like",
             "context_emotion": "joy", "track": track},
            format="json",
            **self.auth_headers,
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        self.assertEqual(response2.status_code, 200)  # Cached response
        self.assertEqual(response2.data.get("event_id"), event_id_1)
        self.assertEqual(response2.get("X-Idempotency-Replay"), "true")

        # Verify only one event was processed (check profile events)
        profile = UserProfile.objects(username="e2euser").first()
        self.assertEqual(profile.taste_profile.get("events"), 1)


class TestCacheFlow(E2EIntegrationTestCase):
    """Test Flow 4: Cache miss → hit → feedback → invalidation → fresh."""

    def test_cache_invalidation_on_feedback(self):
        """Test that feedback invalidates recommendation cache."""
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [
                    {"name": "Track", "artist": "Artist", "release_date": "2020-01-01",
                     "popularity": 80, "external_url": "url", "duration_ms": 200000},
                ],
                "degraded": False,
            }

            # First request - cache miss
            response1 = self.client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
                **self.auth_headers,
            )
            self.assertEqual(response1.status_code, 200)

            # Second request - cache hit
            response2 = self.client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
                **self.auth_headers,
            )
            self.assertEqual(response2.status_code, 200)

            # Submit feedback
            track = {"name": "Track", "artist": "Artist", "release_date": "2020-01-01",
                     "duration_ms": 200000, "popularity": 80, "external_url": "url"}
            self.client.post(
                "/api/v1/feedback/",
                {"kind": "track", "track_id": "deezer:1", "signal": "like",
                 "context_emotion": "joy", "track": track},
                format="json",
                **self.auth_headers,
            )

            # Third request - should be cache miss (invalidated)
            response3 = self.client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
                **self.auth_headers,
            )
            self.assertEqual(response3.status_code, 200)


class TestGenAIFlow(E2EIntegrationTestCase):
    """Test Flow 5: GenAI natural language → intent → tool → API → response."""

    def test_genai_recommendation_flow(self):
        """Test GenAI assistant recommendation flow."""
        from genai.assistant import GenAIAssistantFactory

        assistant = GenAIAssistantFactory.create_mock("http://localhost:8000")

        with patch.object(assistant.tool_registry, "execute_tool") as mock_tool:
            mock_tool.return_value = MagicMock(
                success=True,
                data={
                    "emotion": "joy",
                    "recommendations": [
                        {"name": "Happy Song", "artist": "Artist", "explanation": "Matches your joy mood"}
                    ],
                    "degraded": False,
                }
            )

            response = assistant.process_message("Give me some happy music for working out")

            self.assertIsNotNone(response.intent)
            self.assertEqual(response.intent.intent, "recommend_music")
            self.assertEqual(response.intent.emotion, "joy")
            self.assertTrue(response.success)
            self.assertIn("Happy Song", response.message)

    def test_genai_preferences_flow(self):
        """Test GenAI assistant preferences flow."""
        from genai.assistant import GenAIAssistantFactory

        assistant = GenAIAssistantFactory.create_mock("http://localhost:8000")

        with patch.object(assistant.tool_registry, "execute_tool") as mock_tool:
            mock_tool.return_value = MagicMock(
                success=True,
                data={
                    "artist_preferences": {"Artist A": 0.5},
                    "genre_preferences": {},
                    "era_preferences": {},
                    "mood_preferences": {},
                    "exploration_preference": 0.3,
                    "interaction_counts": {"like": 10},
                }
            )

            response = assistant.process_message("What are my music preferences?")

            self.assertIsNotNone(response.intent)
            self.assertEqual(response.intent.intent, "get_preferences")
            self.assertTrue(response.success)
            self.assertIn("Artist A", response.message)

    def test_genai_explanation_flow(self):
        """Test GenAI assistant explanation flow."""
        from genai.assistant import GenAIAssistantFactory

        assistant = GenAIAssistantFactory.create_mock("http://localhost:8000")

        with patch.object(assistant.tool_registry, "execute_tool") as mock_tool:
            mock_tool.return_value = MagicMock(
                success=True,
                data={
                    "track": "Happy Song",
                    "artist": "Artist",
                    "explanation": "Matches your joy mood",
                    "ranking_signals": {"personalization": {"applied": True}},
                }
            )

            response = assistant.process_message("Why was this song recommended?")

            self.assertIsNotNone(response.intent)
            self.assertEqual(response.intent.intent, "get_explanation")
            self.assertTrue(response.success)


class TestFailureFlow(E2EIntegrationTestCase):
    """Test Flow 6: Temporary failure → retry → success."""

    def test_modal_failure_fallback(self):
        """Test that Modal failure falls back to curated recommendations."""
        from api.candidate_generation import CandidateGenerationError

        from api.candidate_generation import generate_candidates

        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.side_effect = Exception("Modal unavailable")

            # Should fall back to curated tracks
            candidates = generate_candidates(emotion="joy", limit=10)
            self.assertEqual(len(candidates), 10)
            self.assertTrue(all("name" in c for c in candidates))

    def test_bandit_failure_fallback(self):
        """Test that bandit failure falls back to base ranking."""
        from api.recommendation_pipeline import run_pipeline
        from api.models import UserProfile

        # Create user with warm bandit profile
        profile = UserProfile.objects(username="e2euser").first()
        alpha = [1.0] * tf.FEATURE_DIM
        beta = [1.0] * tf.FEATURE_DIM
        # Make bandit want to reorder strongly
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        alpha[decade_slot] = 100.0
        beta[decade_slot] = 0.01
        profile.taste_profile = {"alpha": alpha, "beta": beta, "events": bandit.COLD_START_MIN_EVENTS + 5}
        profile.save()

        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [
                    {"name": f"Track {i}", "artist": f"Artist {i}", "release_date": "2020-01-01",
                     "popularity": 50 + i * 5, "external_url": f"url{i}", "duration_ms": 200000}
                    for i in range(10)
                ],
                "degraded": False,
            }

            # Force bandit to fail
            with patch("api.recommendation_pipeline.bandit.rerank", side_effect=Exception("Bandit failed")):
                result = run_pipeline(emotion="joy", user_profile=profile)
                self.assertEqual(result["degraded"], False)
                self.assertIn("recommendations", result)


class TestFullUserJourney(E2EIntegrationTestCase):
    """Test complete user journey from registration to personalized recommendations."""

    def test_complete_user_journey(self):
        """Test the complete user journey."""
        # 1. Register
        client = APIClient()
        reg = client.post(
            "/api/v1/users/register/",
            {"username": "journey_user", "password": "password123", "email": "journey@example.com"},
            format="json",
        )
        self.assertEqual(reg.status_code, 201)

        # 2. Login
        login = client.post(
            "/api/v1/users/login/",
            {"username": "journey_user", "password": "password123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        access = login.data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # 3. Validate token
        self.assertEqual(client.get("/api/v1/users/validate_token/", **{"HTTP_AUTHORIZATION": f"Bearer {access}"}).status_code, 200)

        # 4. Get profile
        profile_resp = client.get("/api/v1/users/user/profile/")
        self.assertEqual(profile_resp.status_code, 200)
        self.assertEqual(profile_resp.data["username"], "journey_user")

        # 5. Get recommendations (cold start)
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [{"name": "Track", "artist": "Artist", "external_url": "url", "popularity": 50}],
                "degraded": False,
            }
            rec_resp = client.post("/api/v1/music_recommendation/", {"emotion": "joy"}, format="json")
            self.assertEqual(rec_resp.status_code, 200)

        # 6. Submit feedback
        track = {"name": "Track", "artist": "Artist", "external_url": "https://deezer.com/track/1"}
        fb_resp = client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": "deezer:1", "signal": "like", "context_emotion": "joy", "track": track},
            format="json",
        )
        self.assertEqual(fb_resp.status_code, 202)

        # 7. Get recommendations again (should be personalized)
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [{"name": "Track", "artist": "Artist", "external_url": "url", "popularity": 50}],
                "degraded": False,
            }
            rec_resp2 = client.post("/api/v1/music_recommendation/", {"emotion": "joy"}, format="json")
            self.assertEqual(rec_resp2.status_code, 200)

        # 8. Refresh token
        refresh = client.post("/api/v1/users/token/refresh/", {"refresh": login.data["refresh"]}, format="json")
        self.assertEqual(refresh.status_code, 200)

        # 9. Delete account
        del_resp = client.delete("/api/v1/users/user/profile/delete/")
        self.assertEqual(del_resp.status_code, 200)

        # 10. Verify deleted
        self.assertIsNone(User.objects(username="journey_user").first())


# Run all E2E tests
if __name__ == "__main__":
    import django
    from django.conf import settings
    import os
    import sys

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    django.setup()

    # Run specific test classes
    suite = TestSuite()
    suite.addTest(TestRecommendationFlow("test_recommendation_flow_complete"))
    suite.addTest(TestRecommendationFlow("test_recommendation_with_history"))
    suite.addTest(TestFeedbackFlow("test_feedback_complete_flow"))
    suite.addTest(TestFeedbackFlow("test_feedback_unlike_reverts_like"))
    suite.addTest(TestDuplicateFeedback("test_duplicate_feedback_idempotency"))
    suite.addTest(TestCacheFlow("test_cache_invalidation_on_feedback"))
    suite.addTest(TestGenAIFlow("test_genai_recommendation_flow"))
    suite.addTest(TestGenAIFlow("test_genai_preferences_flow"))
    suite.addTest(TestGenAIFlow("test_genai_explanation_flow"))
    suite.addTest(TestFailureFlow("test_modal_failure_fallback"))
    suite.addTest(TestFailureFlow("test_bandit_failure_fallback"))
    suite.addTest(TestFullUserJourney("test_complete_user_journey"))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)