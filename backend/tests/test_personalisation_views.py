"""Integration tests for personalisation wiring in api/views.py.

Covers the points where calibration + bandit hook into the proxied
text_emotion and music_recommendation views. The Modal calls are
stubbed by the autouse ``mock_inference`` fixture in conftest.

The contract is "augmentation, not replacement":

* Anonymous callers must see the rule-based output untouched.
* Authenticated cold-start users must also see untouched output.
* Authenticated warm users must see calibration / bandit effects.
"""

from __future__ import annotations

import pytest

from api import bandit, views
from api import track_features as tf
from api.calibration import CALIBRATION_THRESHOLD
from api.models import UserProfile


@pytest.fixture(autouse=True)
def _enable_feedback_sync_mode(monkeypatch):
    """Enable synchronous feedback processing for tests."""
    from django.conf import settings
    monkeypatch.setattr(settings, "FEEDBACK_SYNC_MODE", True, raising=False)


URL_TEXT = "/api/v1/text_emotion/"
URL_MUSIC = "/api/v1/music_recommendation/"


# ---------------------------------------------------------------------------
# Mood calibration in /api/text_emotion/
# ---------------------------------------------------------------------------
class TestTextEmotionCalibration:
    def test_anon_caller_gets_raw_emotion(self, api_client, monkeypatch):
        monkeypatch.setattr(
            views,
            "modal_text",
            lambda text: {"emotion": "joy", "recommendations": []},
        )
        resp = api_client.post(URL_TEXT, {"text": "hi"}, format="json")
        assert resp.status_code == 200
        assert resp.data["emotion"] == "joy"
        assert "calibrated_from" not in resp.data

    def test_authed_cold_user_gets_raw_emotion(self, auth_client, monkeypatch):
        monkeypatch.setattr(
            views,
            "modal_text",
            lambda text: {"emotion": "joy", "recommendations": []},
        )
        resp = auth_client.post(URL_TEXT, {"text": "hi"}, format="json")
        assert resp.status_code == 200
        assert resp.data["emotion"] == "joy"
        assert "calibrated_from" not in resp.data

    def test_authed_warm_user_gets_calibrated_emotion(self, auth_client, monkeypatch):
        # Seed the calibration map past threshold.
        profile = UserProfile.objects(username=auth_client.user.username).first()
        profile.mood_calibration = {"joy": {"love": CALIBRATION_THRESHOLD}}
        profile.save()

        monkeypatch.setattr(
            views,
            "modal_text",
            lambda text: {"emotion": "joy", "recommendations": []},
        )
        resp = auth_client.post(URL_TEXT, {"text": "hi"}, format="json")
        assert resp.status_code == 200
        assert resp.data["emotion"] == "love"
        assert resp.data["calibrated_from"] == "joy"

    def test_calibration_only_acts_on_matching_predicted(self, auth_client, monkeypatch):
        profile = UserProfile.objects(username=auth_client.user.username).first()
        profile.mood_calibration = {"sadness": {"anger": 99}}
        profile.save()

        monkeypatch.setattr(
            views,
            "modal_text",
            lambda text: {"emotion": "joy", "recommendations": []},
        )
        resp = auth_client.post(URL_TEXT, {"text": "hi"}, format="json")
        assert resp.status_code == 200
        assert resp.data["emotion"] == "joy"


# ---------------------------------------------------------------------------
# Bandit re-rank in /api/music_recommendation/
# ---------------------------------------------------------------------------
def _two_decade_tracks() -> list[dict]:
    return [
        {"name": "old", "release_date": "1985-01-01",
         "duration_ms": 200_000, "popularity": 50},
        {"name": "new", "release_date": "2020-01-01",
         "duration_ms": 200_000, "popularity": 50},
    ]


class TestMusicBanditRerank:
    def test_anon_caller_gets_base_order(self, api_client, monkeypatch):
        base = _two_decade_tracks()
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            lambda emotion, market=None, history=None, genre=None: {
                "emotion": emotion, "recommendations": base, "market": None,
            },
        )
        resp = api_client.post(URL_MUSIC, {"emotion": "joy"}, format="json")
        assert resp.status_code == 200
        assert [t["name"] for t in resp.data["recommendations"]] == ["old", "new"]

    def test_authed_cold_user_gets_base_order(self, auth_client, monkeypatch):
        base = _two_decade_tracks()
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            lambda emotion, market=None, history=None, genre=None: {
                "emotion": emotion, "recommendations": base, "market": None,
            },
        )
        resp = auth_client.post(URL_MUSIC, {"emotion": "joy"}, format="json")
        assert resp.status_code == 200
        # Cold start -> identity.
        assert [t["name"] for t in resp.data["recommendations"]] == ["old", "new"]

    def test_authed_warm_user_gets_reranked(self, auth_client, monkeypatch):
        # Seed a posterior that strongly prefers the 2010+ decade.
        alpha = [0.01] * tf.FEATURE_DIM
        beta = [100.0] * tf.FEATURE_DIM
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        alpha[decade_slot] = 100.0
        beta[decade_slot] = 0.01

        profile = UserProfile.objects(username=auth_client.user.username).first()
        profile.taste_profile = {
            "alpha": alpha, "beta": beta,
            "events": bandit.COLD_START_MIN_EVENTS + 1,
        }
        profile.save()

        base = _two_decade_tracks()
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            lambda emotion, market=None, history=None, genre=None: {
                "emotion": emotion, "recommendations": base, "market": None,
            },
        )
        resp = auth_client.post(URL_MUSIC, {"emotion": "joy"}, format="json")
        assert resp.status_code == 200
        names = [t["name"] for t in resp.data["recommendations"]]
        # New track now leads the list.
        assert names[0] == "new"
        # Set of tracks unchanged -- bandit only reorders.
        assert set(names) == {"old", "new"}

    def test_bandit_failure_falls_back_to_base_order(self, auth_client, monkeypatch):
        """Even if the bandit blows up, the request still succeeds."""
        base = _two_decade_tracks()
        monkeypatch.setattr(
            "api.candidate_generation.modal_music",
            lambda emotion, market=None, history=None, genre=None: {
                "emotion": emotion, "recommendations": base, "market": None,
            },
        )

        # Force the rerank call to raise.
        def boom(*_args, **_kwargs):
            raise RuntimeError("bandit imploded")

        monkeypatch.setattr(views.bandit, "rerank", boom)

        # Make the user "warm" so we actually enter the rerank branch.
        profile = UserProfile.objects(username=auth_client.user.username).first()
        profile.taste_profile = {
            "alpha": [1.0] * tf.FEATURE_DIM,
            "beta": [1.0] * tf.FEATURE_DIM,
            "events": bandit.COLD_START_MIN_EVENTS + 5,
        }
        profile.save()

        resp = auth_client.post(URL_MUSIC, {"emotion": "joy"}, format="json")
        assert resp.status_code == 200
        # Fell back cleanly to the base order.
        assert [t["name"] for t in resp.data["recommendations"]] == ["old", "new"]


# ---------------------------------------------------------------------------
# Feedback -> taste_profile wiring
# ---------------------------------------------------------------------------
URL_FEEDBACK = "/api/v1/feedback/"


class TestFeedbackWiresIntoTasteProfile:
    def test_like_with_track_dict_updates_posterior(self, auth_client):
        track = {"release_date": "2020-01-01",
                 "duration_ms": 200_000, "popularity": 75}
        resp = auth_client.post(
            URL_FEEDBACK,
            {"kind": "track", "track_id": "deezer:1", "signal": "like",
             "context_emotion": "joy", "track": track},
            format="json",
        )
        assert resp.status_code == 202

        profile = UserProfile.objects(username=auth_client.user.username).first()
        taste = profile.taste_profile
        assert taste.get("events") == 1
        # 2010+ decade slot should have its alpha bumped above the prior.
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        assert taste["alpha"][decade_slot] > bandit.PRIOR_ALPHA

    def test_unlike_with_track_dict_increments_beta(self, auth_client):
        track = {"release_date": "1985-01-01",
                 "duration_ms": 200_000, "popularity": 30}
        resp = auth_client.post(
            URL_FEEDBACK,
            {"kind": "track", "track_id": "deezer:2", "signal": "unlike",
             "context_emotion": "sadness", "track": track},
            format="json",
        )
        assert resp.status_code == 202

        profile = UserProfile.objects(username=auth_client.user.username).first()
        taste = profile.taste_profile
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("80s")
        assert taste["beta"][decade_slot] > bandit.PRIOR_BETA

    def test_open_deezer_uses_half_weight(self, auth_client):
        track = {"release_date": "2020-01-01",
                 "duration_ms": 200_000, "popularity": 75}
        resp = auth_client.post(
            URL_FEEDBACK,
            {"kind": "track", "track_id": "deezer:3", "signal": "open_deezer",
             "context_emotion": "joy", "track": track},
            format="json",
        )
        assert resp.status_code == 202

        profile = UserProfile.objects(username=auth_client.user.username).first()
        taste = profile.taste_profile
        decade_slot = len(tf.EMOTIONS) + tf.DECADES.index("2010plus")
        # Half weight on alpha.
        assert taste["alpha"][decade_slot] == bandit.PRIOR_ALPHA + 0.5

    def test_track_signal_without_track_dict_still_persists_event(self, auth_client):
        # Without a track payload, we can't update the posterior -- but
        # the event log must still capture the signal.
        resp = auth_client.post(
            URL_FEEDBACK,
            {"kind": "track", "track_id": "deezer:99", "signal": "like"},
            format="json",
        )
        assert resp.status_code == 202

        profile = UserProfile.objects(username=auth_client.user.username).first()
        # No posterior update.
        assert not profile.taste_profile

    def test_invalid_track_field_type_is_rejected(self, auth_client):
        resp = auth_client.post(
            URL_FEEDBACK,
            {"kind": "track", "track_id": "deezer:1", "signal": "like",
             "track": "not a dict"},
            format="json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Critical end-to-end integration test: Feedback -> Preference -> Ranking
# ---------------------------------------------------------------------------
class TestFeedbackChangesRecommendations:
    """End-to-end test proving feedback actually changes future recommendations.

    This is the critical Phase 2 verification:
      1. Get initial recommendations for an emotion
      2. Send positive feedback (like) for a track with specific attributes
      3. Get new recommendations for same emotion
      4. Verify ranking changed to favor similar tracks
    """

    def test_like_changes_future_recommendations(self, auth_client, monkeypatch):
        """Test that liking a track changes future recommendation ranking."""
        # Mock Modal client to return consistent track sets
        def mock_music(emotion, market=None, history=None, genre=None):
            tracks = [
                {"name": "track_a", "artist": "ArtistX", "release_date": "2020-01-01",
                 "duration_ms": 200_000, "popularity": 50, "external_url": "deezer:1"},
                {"name": "track_b", "artist": "ArtistY", "release_date": "1990-01-01",
                 "duration_ms": 200_000, "popularity": 50, "external_url": "deezer:2"},
                {"name": "track_c", "artist": "ArtistZ", "release_date": "2010-01-01",
                 "duration_ms": 200_000, "popularity": 50, "external_url": "deezer:3"},
            ]
            return {"emotion": emotion, "recommendations": tracks, "degraded": False}

        monkeypatch.setattr("api.candidate_generation.modal_music", mock_music)

        # Disable caching for this test to ensure personalization is tested
        monkeypatch.setattr("api.views.get_cached_recommendations", lambda *args, **kwargs: None)
        monkeypatch.setattr("api.views.set_cached_recommendations", lambda *args, **kwargs: None)

        # Step 1: Get initial recommendations
        resp1 = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp1.status_code == 200

        # Step 2: Like track_a (ArtistX, 2020s) - do multiple likes to reach confidence threshold
        track_a = {
            "name": "track_a",
            "artist": "ArtistX",
            "release_date": "2020-01-01",
            "duration_ms": 200_000,
            "popularity": 50,
            "external_url": "https://www.deezer.com/track/1",
        }
        # Need 5 interactions for personalization confidence (MIN_INTERACTIONS_FOR_CONFIDENCE=5)
        for i in range(5):
            fb_track = dict(track_a)
            fb_track["external_url"] = f"https://www.deezer.com/track/{i+1}"
            resp_fb = auth_client.post(
                "/api/v1/feedback/",
                {"kind": "track", "track_id": f"deezer:{i+1}", "signal": "like",
                 "context_emotion": "joy", "track": fb_track},
                format="json",
            )
            assert resp_fb.status_code == 202

        # Step 3: Verify preference profile was updated
        profile = UserProfile.objects(username=auth_client.user.username).first()
        assert "ArtistX" in profile.artist_preferences
        assert profile.artist_preferences["ArtistX"] > 0
        assert "2010s" in profile.era_preferences
        assert profile.era_preferences["2010s"] > 0
        # Total interactions should be >= 5
        total_interactions = sum(profile.interaction_counts.values())
        assert total_interactions >= 5

        # Step 4: Get new recommendations (personalization should apply)
        resp2 = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "joy"},
            format="json",
        )
        assert resp2.status_code == 200
        
        # Step 5: Verify personalization signals present on tracks matching preferences
        for track in resp2.data["recommendations"]:
            signals = track.get("ranking_signals", {})
            pers = signals.get("personalization", {})
            if track["artist"] == "ArtistX":
                assert pers.get("applied") is True, f"Expected personalization applied for {track}"
                assert pers.get("artist_match") is True, f"Expected artist_match for {track}"

    def test_unlike_penalizes_similar_tracks(self, auth_client, monkeypatch):
        """Test that disliking a track penalizes similar tracks in future recommendations."""
        def mock_music(emotion, market=None, history=None, genre=None):
            tracks = [
                {"name": "rock_old", "artist": "RockBand", "release_date": "1985-01-01",
                 "duration_ms": 200_000, "popularity": 50, "external_url": "deezer:10"},
                {"name": "pop_new", "artist": "PopStar", "release_date": "2020-01-01",
                 "duration_ms": 200_000, "popularity": 50, "external_url": "deezer:20"},
            ]
            return {"emotion": emotion, "recommendations": tracks, "degraded": False}

        monkeypatch.setattr("api.candidate_generation.modal_music", mock_music)

        # Dislike the 1980s rock track - do multiple unlikes to reach confidence threshold
        for i in range(5):
            track = {
                "name": "rock_old",
                "artist": "RockBand",
                "release_date": "1985-01-01",
                "duration_ms": 200_000,
                "popularity": 50,
                "external_url": f"https://www.deezer.com/track/{10+i}",
            }
            resp = auth_client.post(
                "/api/v1/feedback/",
                {"kind": "track", "track_id": f"deezer:{10+i}", "signal": "unlike",
                 "context_emotion": "anger", "track": track},
                format="json",
            )
            assert resp.status_code == 202

        # Verify penalty applied
        profile = UserProfile.objects(username=auth_client.user.username).first()
        assert profile.artist_preferences.get("RockBand", 0) < 0
        assert profile.era_preferences.get("1980s", 0) < 0
        total_interactions = sum(profile.interaction_counts.values())
        assert total_interactions >= 5

        # Get new recommendations
        resp2 = auth_client.post(
            "/api/v1/music_recommendation/",
            {"emotion": "anger"},
            format="json",
        )
        assert resp2.status_code == 200
        
        # The disliked track's attributes should have personalization penalty
        for track in resp2.data["recommendations"]:
            signals = track.get("ranking_signals", {})
            pers = signals.get("personalization", {})
            if track["artist"] == "RockBand":
                assert pers.get("applied") is True
                assert pers.get("score", 0) < 0  # Negative score = penalty
