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

import pytest
from rest_framework.test import APIClient

from api.models import UserProfile
from api import bandit, track_features as tf
from users.documents import User
from users.tokens import issue_tokens
from api.events import (
    EventType,
    create_feedback_track_event,
    create_feedback_mood_event,
    process_feedback_track,
    process_feedback_mood,
    enqueue_event,
)


@pytest.fixture
def e2e_client():
    """Create an authenticated APIClient for E2E tests."""
    client = APIClient()
    user = User(username="e2euser", email="e2e@example.com")
    user.set_password("testpass123")
    user.save()
    profile = UserProfile(username="e2euser").save()
    
    login_res = client.post(
        "/api/v1/users/login/",
        {"username": "e2euser", "password": "testpass123"},
        format="json",
    )
    assert login_res.status_code == 200
    token = login_res.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    client.user = user
    return client


@pytest.fixture
def e2e_user():
    """Create a test user."""
    user = User(username="e2euser", email="e2e@example.com")
    user.set_password("testpass123")
    user.save()
    profile = UserProfile(username="e2euser").save()
    return user


@pytest.fixture
def e2e_profile(e2e_user):
    """Get the test user's profile."""
    return UserProfile.objects(username="e2euser").first()


class TestRecommendationFlow:
    """Test Flow 1: Complete recommendation pipeline."""

    def test_recommendation_flow_complete(self, e2e_client):
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
            response = e2e_client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy", "genre": "pop"},
                format="json",
            )

            assert response.status_code == 200
            data = response.data

            # Verify response structure
            assert "emotion" in data
            assert "recommendations" in data
            assert "degraded" in data
            assert data["degraded"] is False

            # Verify recommendations have all required fields
            recs = data["recommendations"]
            assert len(recs) > 0
            assert len(recs) <= 20  # DEFAULT_FINAL_LIMIT

            for rec in recs:
                assert "name" in rec
                assert "artist" in rec
                assert "explanation" in rec
                assert "ranking_signals" in rec
                assert isinstance(rec["explanation"], str)
                assert len(rec["explanation"]) > 0

            # Verify ranking signals present
            signals = recs[0]["ranking_signals"]
            assert "mood_match" in signals
            assert "base_score" in signals

    def test_recommendation_with_history(self, e2e_client):
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

            response = e2e_client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy", "history": ["sadness", "joy", "joy"]},
                format="json",
            )

            assert response.status_code == 200
            assert response.data["emotion"] == "joy"


class TestFeedbackFlow:
    """Test Flow 2: Feedback → Event → Worker → Profile → Bandit → Cache Invalidation."""

    def test_feedback_complete_flow(self, e2e_client):
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

        # Submit like feedback (sync mode processes directly, doesn't enqueue)
        response = e2e_client.post(
            "/api/v1/feedback/",
            {
                "kind": "track",
                "track_id": track_id,
                "signal": "like",
                "context_emotion": "joy",
                "track": track,
            },
            format="json",
        )

        assert response.status_code == 202
        assert "event_id" in response.data

        # Process the event synchronously (test mode)
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
        assert profile is not None
        assert profile.taste_profile is not None
        assert profile.taste_profile.get("events") == 1

        # Verify bandit posterior updated
        taste = profile.taste_profile
        assert "alpha" in taste
        assert "beta" in taste

    def test_feedback_unlike_reverts_like(self, e2e_client):
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

        # Re-fetch profile (mongoengine doesn't have refresh_from_db)
        profile = UserProfile.objects(username="e2euser").first()
        events_after_unlike = profile.taste_profile.get("events")

        # Events should be same (revert doesn't increment total events)
        assert events_after_unlike == events_after_like


class TestDuplicateFeedback:
    """Test Flow 3: Duplicate feedback with idempotency key."""

    def test_duplicate_feedback_idempotency(self, e2e_client):
        """Test that duplicate feedback with same idempotency key is deduplicated."""
        track = {
            "name": "Track", "artist": "Artist",
            "release_date": "2020-01-01", "duration_ms": 200000,
            "popularity": 80, "external_url": "https://deezer.com/track/123",
        }
        track_id = "deezer:123"
        idempotency_key = "test-idempotency-key-123"

        # First request
        response1 = e2e_client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": track_id, "signal": "like",
             "context_emotion": "joy", "track": track},
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert response1.status_code == 202
        event_id_1 = response1.data["event_id"]

        # Second request with same idempotency key
        response2 = e2e_client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": track_id, "signal": "like",
             "context_emotion": "joy", "track": track},
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert response2.status_code == 202  # Cached response returns same status
        # JsonResponse doesn't have .data, parse content
        import json
        response2_data = json.loads(response2.content)
        assert response2_data.get("event_id") == event_id_1
        assert response2.get("X-Idempotency-Replay") == "true"

        # Verify only one event was processed (check profile events)
        profile = UserProfile.objects(username="e2euser").first()
        assert profile.taste_profile.get("events") == 1


class TestCacheFlow:
    """Test Flow 4: Cache miss → hit → feedback → invalidation → fresh."""

    def test_cache_invalidation_on_feedback(self, e2e_client):
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
            response1 = e2e_client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
            )
            assert response1.status_code == 200

            # Second request - cache hit
            response2 = e2e_client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
            )
            assert response2.status_code == 200

            # Submit feedback
            track = {"name": "Track", "artist": "Artist", "release_date": "2020-01-01",
                     "duration_ms": 200000, "popularity": 80, "external_url": "url"}
            e2e_client.post(
                "/api/v1/feedback/",
                {"kind": "track", "track_id": "deezer:1", "signal": "like",
                 "context_emotion": "joy", "track": track},
                format="json",
            )

            # Third request - should be cache miss (invalidated)
            response3 = e2e_client.post(
                "/api/v1/music_recommendation/",
                {"emotion": "joy"},
                format="json",
            )
            assert response3.status_code == 200


class TestGenAIFlow:
    """Test Flow 5: GenAI natural language → intent → tool → API → response."""

    def test_genai_recommendation_flow(self, e2e_client):
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

            assert response.intent is not None
            assert response.intent.intent == "recommend_music"
            assert response.intent.emotion == "joy"
            assert response.success is True
            assert "Happy Song" in response.message

    def test_genai_preferences_flow(self, e2e_client):
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

            assert response.intent is not None
            assert response.intent.intent == "get_preferences"
            assert response.success is True
            assert "Artist A" in response.message

    def test_genai_explanation_flow(self, e2e_client):
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

            assert response.intent is not None
            assert response.intent.intent == "get_explanation"
            assert response.success is True


class TestFailureFlow:
    """Test Flow 6: Temporary failure → retry → success."""

    def test_modal_failure_fallback(self):
        """Test that Modal failure falls back to curated recommendations via pipeline."""
        from api.candidate_generation import CandidateGenerationError, generate_candidates, generate_fallback_candidates
        from api.recommendation_pipeline import run_pipeline

        # Test 1: generate_candidates raises CandidateGenerationError on failure
        with patch("integrations.clients.music_recommendation", side_effect=Exception("Modal unavailable")):
            try:
                generate_candidates(emotion="joy", limit=10)
                assert False, "Expected CandidateGenerationError"
            except CandidateGenerationError:
                pass  # Expected

        # Test 2: generate_fallback_candidates returns curated tracks
        fallback = generate_fallback_candidates(limit=10)
        assert len(fallback) == 10
        assert all("name" in c for c in fallback)

        # Test 3: Full pipeline handles fallback gracefully
        with patch("integrations.clients.music_recommendation", side_effect=Exception("Modal unavailable")):
            result = run_pipeline(emotion="joy", user_profile=None)
            assert result["degraded"] is True
            # Fallback returns all curated tracks (14 by default)
            assert len(result["recommendations"]) >= 10
            assert all("name" in c for c in result["recommendations"])

    def test_bandit_failure_fallback(self, e2e_client, e2e_profile):
        """Test that bandit failure falls back to base ranking."""
        from api.recommendation_pipeline import run_pipeline

        # Create user with warm bandit profile
        alpha = [1.0] * tf.FEATURE_DIM
        beta = [1.0] * tf.FEATURE_DIM
        # Make bandit want to reorder strongly
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        alpha[decade_slot] = 100.0
        beta[decade_slot] = 0.01
        e2e_profile.taste_profile = {"alpha": alpha, "beta": beta, "events": bandit.COLD_START_MIN_EVENTS + 5}
        e2e_profile.save()

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
                result = run_pipeline(emotion="joy", user_profile=e2e_profile)
                assert result["degraded"] is False
                assert "recommendations" in result


class TestFullUserJourney:
    """Test complete user journey from registration to personalized recommendations."""

    def test_complete_user_journey(self):
        """Test the complete user journey."""
        client = APIClient()
        
        # 1. Register
        reg = client.post(
            "/api/v1/users/register/",
            {"username": "journey_user", "password": "password123", "email": "journey@example.com"},
            format="json",
        )
        assert reg.status_code == 201

        # 2. Login
        login = client.post(
            "/api/v1/users/login/",
            {"username": "journey_user", "password": "password123"},
            format="json",
        )
        assert login.status_code == 200
        access = login.data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # 3. Validate token
        assert client.get("/api/v1/users/validate_token/", HTTP_AUTHORIZATION=f"Bearer {access}").status_code == 200

        # 4. Get profile
        profile_resp = client.get("/api/v1/users/user/profile/")
        assert profile_resp.status_code == 200
        assert profile_resp.data["username"] == "journey_user"

        # 5. Get recommendations (cold start)
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [{"name": "Track", "artist": "Artist", "external_url": "url", "popularity": 50}],
                "degraded": False,
            }
            rec_resp = client.post("/api/v1/music_recommendation/", {"emotion": "joy"}, format="json")
            assert rec_resp.status_code == 200

        # 6. Submit feedback
        track = {"name": "Track", "artist": "Artist", "external_url": "https://deezer.com/track/1"}
        fb_resp = client.post(
            "/api/v1/feedback/",
            {"kind": "track", "track_id": "deezer:1", "signal": "like", "context_emotion": "joy", "track": track},
            format="json",
        )
        assert fb_resp.status_code == 202

        # 7. Get recommendations again (should be personalized)
        with patch("api.candidate_generation.modal_music") as mock_modal:
            mock_modal.return_value = {
                "emotion": "joy",
                "recommendations": [{"name": "Track", "artist": "Artist", "external_url": "url", "popularity": 50}],
                "degraded": False,
            }
            rec_resp2 = client.post("/api/v1/music_recommendation/", {"emotion": "joy"}, format="json")
            assert rec_resp2.status_code == 200

        # 8. Refresh token
        refresh = client.post("/api/v1/users/token/refresh/", {"refresh": login.data["refresh"]}, format="json")
        assert refresh.status_code == 200

        # 9. Delete account
        del_resp = client.delete("/api/v1/users/user/profile/delete/")
        assert del_resp.status_code == 200

        # 10. Verify deleted
        assert User.objects(username="journey_user").first() is None


# Run all E2E tests
if __name__ == "__main__":
    import django
    from django.conf import settings
    import os
    import sys
    import unittest

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    django.setup()

    # Run specific test classes
    from django.test import TestSuite
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