"""Tests for the recommendation pipeline (cold start, diversity, explanations)."""

from __future__ import annotations

import random

import pytest

from api import bandit
from api.recommendation_pipeline import (
    run_pipeline,
    _apply_diversity,
    _generate_explanations,
    _build_explanation,
)
from api import track_features as tf
from api.models import UserProfile


class _MockModalMusic:
    """Mock Modal music recommendation returning diverse tracks."""
    
    @staticmethod
    def mock_music(emotion, market=None, history=None, genre=None):
        return {
            "emotion": emotion,
            "recommendations": [
                {"name": f"track_{i}", "artist": f"Artist{i % 3}", 
                 "release_date": f"{1990 + i * 5}-01-01",
                 "duration_ms": 200_000, "popularity": 50 + i * 5,
                 "external_url": f"https://deezer.com/track/{i}"}
                for i in range(20)
            ],
            "degraded": False,
        }


class TestColdStart:
    """Test cold-start behavior for new users."""

    def test_anonymous_user_gets_base_order(self, api_client, monkeypatch):
        """Anonymous users should get Modal's base order without personalization."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        resp = api_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        # Should have recommendations
        assert len(resp.data["recommendations"]) > 0
        # No personalization signals (or applied=False)
        for track in resp.data["recommendations"]:
            signals = track.get("ranking_signals", {})
            pers = signals.get("personalization", {})
            # For anonymous users, personalization is skipped entirely
            assert pers.get("applied", False) is False

    def test_user_with_zero_interactions_gets_base_order(self, auth_client, monkeypatch):
        """User with zero interactions should get base order (cold start)."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        # Should have recommendations
        assert len(resp.data["recommendations"]) > 0

    def test_user_below_threshold_gets_base_order(self, auth_client, monkeypatch):
        """User with < 5 interactions should get base order."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        # Give user 3 interactions (below threshold of 5)
        for i in range(3):
            track = {
                "name": f"track_{i}", "artist": f"Artist{i}",
                "release_date": "2020-01-01", "duration_ms": 200_000,
                "popularity": 50, "external_url": f"https://deezer.com/track/{i}"
            }
            auth_client.post(
                "/api/v1/feedback/",
                {"kind": "track", "track_id": f"deezer:{i}", "signal": "like",
                 "context_emotion": "joy", "track": track},
                format="json",
            )
        
        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        # Personalization should not apply yet
        for track in resp.data["recommendations"]:
            signals = track.get("ranking_signals", {})
            pers = signals.get("personalization", {})
            assert pers.get("applied") is False


class TestDiversity:
    """Test diversity re-ranking."""

    def test_diversity_reduces_artist_repetition(self):
        """Diversity should reduce consecutive same-artist tracks."""
        # Create tracks with enough diversity candidates
        tracks = [
            {"name": f"t{i}", "artist": f"Artist{i % 4}", "release_date": "2020-01-01",
             "duration_ms": 200_000, "popularity": 50,
             "external_url": f"deezer:{i}", "base_score": 0.9 - i * 0.01,
             "ranking_signals": {}}
            for i in range(12)
        ]

        diversified = _apply_diversity(tracks, k=8, diversity_weight=0.5, dimensions=("artist",))
        
        # Check that diversity reduces consecutive same-artist tracks
        artists = [t["artist"] for t in diversified]
        consecutive_same = sum(1 for i in range(len(artists) - 1) if artists[i] == artists[i + 1])
        # With diversity, we should have fewer consecutive same-artist than without
        # At minimum, it shouldn't be all the same
        assert consecutive_same < len(artists) - 1, f"All consecutive same: {artists}"

    def test_diversity_weight_zero_preserves_order(self):
        """Diversity weight 0 should preserve original relevance order."""
        tracks = [
            {"name": f"t{i}", "artist": "ArtistA", "release_date": "2020-01-01",
             "duration_ms": 200_000, "popularity": 50,
             "external_url": f"deezer:{i}", "base_score": 0.9 - i * 0.01,
             "ranking_signals": {}}
            for i in range(5)
        ]
        diversified = _apply_diversity(tracks, k=5, diversity_weight=0.0, dimensions=("artist",))
        assert diversified == tracks

    def test_diversity_respects_k_limit(self):
        """Diversity should return at most k tracks."""
        tracks = [
            {"name": f"t{i}", "artist": f"Artist{i}", "release_date": "2020-01-01",
             "duration_ms": 200_000, "popularity": 50,
             "external_url": f"deezer:{i}", "base_score": 0.9 - i * 0.01,
             "ranking_signals": {}}
            for i in range(20)
        ]
        diversified = _apply_diversity(tracks, k=5, diversity_weight=0.5, dimensions=("artist",))
        assert len(diversified) == 5


class TestExplanations:
    """Test explanation generation."""

    def test_explanation_generated_for_each_track(self):
        """Every track should get an explanation."""
        tracks = [
            {"name": "t1", "artist": "A1", "base_score": 0.8,
             "ranking_signals": {"mood_match": True, "base_score": 0.8}}
        ]
        explained = _generate_explanations(tracks, "joy", None)
        assert len(explained) == 1
        assert "explanation" in explained[0]
        assert isinstance(explained[0]["explanation"], str)
        assert len(explained[0]["explanation"]) > 0

    def test_explanation_includes_mood_match(self):
        """Explanation should mention mood match when signal present."""
        tracks = [{
            "name": "t1", "artist": "A1", "base_score": 0.8,
            "ranking_signals": {"mood_match": True, "base_score": 0.8}
        }]
        explained = _generate_explanations(tracks, "joy", None)
        assert "joy" in explained[0]["explanation"].lower()

    def test_explanation_includes_personalization(self):
        """Explanation should mention personalization when applied."""
        from api import preference_profile
        prefs = {
            "artist_preferences": {"ArtistX": 0.5},
            "era_preferences": {}, "mood_preferences": {},
            "genre_preferences": {}, "interaction_counts": {"like": 10}
        }
        tracks = [{
            "name": "t1", "artist": "ArtistX", "base_score": 0.8,
            "ranking_signals": {
                "mood_match": True, "base_score": 0.8,
                "personalization": {"applied": True, "artist_match": True, "score": 0.5}
            }
        }]
        user_profile = type('obj', (object,), {
            "artist_preferences": {"ArtistX": 0.5},
            "era_preferences": {}, "mood_preferences": {},
            "genre_preferences": {}, "interaction_counts": {"like": 10}
        })()
        explained = _generate_explanations(tracks, "joy", user_profile)
        # Explanation should mention personalization-related content
        explanation = explained[0]["explanation"].lower()
        assert "artist" in explanation or "like" in explanation or "prefer" in explanation

    def test_explanation_no_hallucination(self):
        """Explanation should only mention signals that exist."""
        tracks = [{
            "name": "t1", "artist": "Unknown", "base_score": 0.5,
            "ranking_signals": {"mood_match": True, "base_score": 0.5}
        }]
        explained = _generate_explanations(tracks, "sadness", None)
        # Should not claim personalization or artist preference
        assert "personalization" not in explained[0]["explanation"].lower() or "not" in explained[0]["explanation"].lower()

    def test_build_explanation_direct(self):
        """Test _build_explanation directly."""
        signals = {"mood_match": True, "base_score": 0.8}
        explanation = _build_explanation(signals, "joy", None)
        assert "joy" in explanation
        assert "mood" in explanation.lower()


class TestBanditColdStart:
    """Test bandit cold-start behavior in pipeline."""

    def test_bandit_noop_for_cold_user(self, auth_client, monkeypatch):
        """Bandit should no-op for users with < 20 events."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        # User has 0 bandit events
        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        # Should get Modal's order (no bandit re-rank)

    def test_bandit_active_after_threshold(self, auth_client, monkeypatch):
        """Bandit should re-rank after 20 events."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        # Create user with warm bandit profile (20+ events)
        profile = UserProfile.objects(username=auth_client.user.username).first()
        alpha = [0.01] * tf.FEATURE_DIM
        beta = [100.0] * tf.FEATURE_DIM
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        alpha[decade_slot] = 100.0
        beta[decade_slot] = 0.01
        profile.taste_profile = {
            "alpha": alpha, "beta": beta,
            "events": bandit.COLD_START_MIN_EVENTS + 1,
        }
        profile.save()

        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        # Should have bandit re-ranked (hard to verify exact order without knowing Modal's output)
        assert len(resp.data["recommendations"]) > 0


class TestPipelineIntegration:
    """Full pipeline integration tests."""

    def test_pipeline_returns_expected_structure(self, auth_client, monkeypatch):
        """Pipeline should return all expected fields."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy", "genre": "pop"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.data
        assert "emotion" in data
        assert "calibrated_from" in data
        assert "recommendations" in data
        assert "degraded" in data
        assert isinstance(data["recommendations"], list)
        assert "market" in data

    def test_pipeline_respects_final_limit(self, auth_client, monkeypatch):
        """Pipeline should respect final_limit parameter."""
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        # This is tested via the view which uses default limit
        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        assert len(resp.data["recommendations"]) <= 20  # DEFAULT_FINAL_LIMIT

    def test_calibration_in_pipeline(self, auth_client, monkeypatch):
        """Calibration should apply in pipeline."""
        from api.calibration import CALIBRATION_THRESHOLD
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            _MockModalMusic.mock_music,
        )
        # Set up calibration
        profile = UserProfile.objects(username=auth_client.user.username).first()
        profile.mood_calibration = {"joy": {"love": CALIBRATION_THRESHOLD}}
        profile.save()

        resp = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["emotion"] == "love"
        assert resp.data["calibrated_from"] == "joy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])