"""Pytest configuration and shared fixtures for the VibeStream backend.

The whole suite runs against an in-memory mongomock database, so no real
MongoDB is required. The Modal inference proxy is mocked. Redis is mocked
with fakeredis.
"""

import os
import threading
from datetime import datetime, timezone
from typing import Optional

import django
import fakeredis
import pytest

# Set test environment variables BEFORE Django settings are loaded
# This must happen in pytest_configure which runs before Django initialization
def pytest_configure(config):
    """Set test environment variables before Django settings are loaded."""
    os.environ.setdefault("FEEDBACK_SYNC_MODE", "true")
    os.environ.setdefault("FEEDBACK_ENABLED", "false")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")


# Enable synchronous feedback processing for all tests
# These will be set again after django.setup() for safety
os.environ.setdefault("FEEDBACK_SYNC_MODE", "true")
os.environ.setdefault("FEEDBACK_ENABLED", "false")  # Disable feedback store persistence in tests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
django.setup()

import backend.settings as settings_module
settings_module.FEEDBACK_SYNC_MODE = True
settings_module.FEEDBACK_ENABLED = False

# Debug: verify settings are loaded correctly
from django.conf import settings
print(f"CONFTEST: FEEDBACK_SYNC_MODE = {getattr(settings, 'FEEDBACK_SYNC_MODE', 'NOT SET')}")
print(f"CONFTEST: FEEDBACK_ENABLED = {getattr(settings, 'FEEDBACK_ENABLED', 'NOT SET')}")

import mongomock  # noqa: E402
import mongoengine  # noqa: E402

# Swap the mongoengine connection (opened by settings.py) for an in-memory
# mongomock instance shared by the whole test session.
mongoengine.disconnect_all()
mongoengine.connect(
    "vibestream_test",
    mongo_client_class=mongomock.MongoClient,
    uuidRepresentation="standard",
)


# In-memory feedback store for tests
class _InMemoryFeedbackStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._mood_feedback = []
        self._track_feedback = []

    def insert_mood_feedback(self, *, username: str, predicted: str, actual: str, input_type: str,
                            confidence: Optional[float] = None, session_id: Optional[str] = None) -> None:
        with self._lock:
            self._mood_feedback.append({
                "ts": datetime.now(timezone.utc),
                "meta": {"username": username, "input_type": input_type, "predicted": predicted, "actual": actual},
                "confidence": float(confidence) if confidence is not None else None,
                "session_id": session_id,
            })

    def insert_track_feedback(self, *, username: str, track_id: str, signal: str,
                             context_emotion: Optional[str] = None, features: Optional[list] = None) -> None:
        import time
        with self._lock:
            self._track_feedback.append({
                "ts": datetime.now(timezone.utc),
                "seq": time.time_ns(),
                "meta": {"username": username, "signal": signal, "context_emotion": context_emotion},
                "track_id": track_id,
                "features": list(features) if features is not None else None,
            })

    def get_active_vote(self, username: str, track_id: str) -> Optional[dict]:
        with self._lock:
            votes = [v for v in self._track_feedback
                    if v["meta"]["username"] == username and v["track_id"] == str(track_id)
                    and v["meta"]["signal"] in ("like", "unlike", "clear")]
            if not votes:
                return None
            # Sort by ts then seq
            votes.sort(key=lambda v: (v["ts"], v["seq"]))
            last = votes[-1]
            if last["meta"]["signal"] not in ("like", "unlike"):
                return None
            return {"signal": last["meta"]["signal"], "features": last.get("features")}

    def query_track_feedback(self, username: str, track_ids) -> dict:
        out = {}
        with self._lock:
            ids = [str(t) for t in (track_ids or []) if t]
            if not ids:
                return out
            votes = [v for v in self._track_feedback
                    if v["meta"]["username"] == username and v["track_id"] in ids
                    and v["meta"]["signal"] in ("like", "unlike", "clear")]
            votes.sort(key=lambda v: (v["ts"], v["seq"]))
            for v in votes:
                sig = v["meta"]["signal"]
                if sig in ("like", "unlike"):
                    out[v["track_id"]] = sig
        return out


# Global in-memory feedback store instance
_test_feedback_store = _InMemoryFeedbackStore()


@pytest.fixture(autouse=True)
def mock_feedback_store(monkeypatch, request):
    """Replace feedback_store with in-memory implementation for tests.
    
    Skipped for test_feedback.py which uses its own fake store.
    """
    # Skip for test_feedback.py which has its own fake store
    if request.module.__name__ == "test_feedback":
        return
    
    import api.feedback_store as feedback_store_module
    
    monkeypatch.setattr(feedback_store_module, "insert_mood_feedback", _test_feedback_store.insert_mood_feedback)
    monkeypatch.setattr(feedback_store_module, "insert_track_feedback", _test_feedback_store.insert_track_feedback)
    monkeypatch.setattr(feedback_store_module, "get_active_vote", _test_feedback_store.get_active_vote)
    monkeypatch.setattr(feedback_store_module, "query_track_feedback", _test_feedback_store.query_track_feedback)
    monkeypatch.setattr(feedback_store_module, "reset_for_tests", lambda: None)
    
    # Clear the store before each test
    with _test_feedback_store._lock:
        _test_feedback_store._mood_feedback.clear()
        _test_feedback_store._track_feedback.clear()


@pytest.fixture(autouse=True)
def _isolation():
    """Reset the database and cache before every test."""
    from django.core.cache import cache

    db = mongoengine.connection.get_db()
    for name in db.list_collection_names():
        db.drop_collection(name)
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    """Replace Redis cache with fakeredis for all tests."""
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    
    # Create a simple mock cache object that mimics Django's cache API
    class FakeCache:
        def __init__(self):
            self._client = fake_redis
            self._cache = self  # Django Redis cache pattern: _cache is the backend
        
        def get(self, key, default=None, version=None):
            # Simple key handling without versioning
            value = self._client.get(key)
            if value is None:
                return default
            import json
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        
        def set(self, key, value, timeout=None, version=None):
            import json
            self._client.set(key, json.dumps(value, separators=(",", ":")))
            if timeout:
                self._client.expire(key, int(timeout))
        
        def delete(self, key, version=None):
            self._client.delete(key)
        
        def clear(self):
            self._client.flushdb()
        
        def has_key(self, key, version=None):
            return bool(self._client.exists(key))
        
        def get_client(self, write=True):
            return self._client
        
        def keys(self, pattern):
            return self._client.keys(pattern)
    
    fake_cache = FakeCache()
    
    # Patch django.core.cache.cache directly (the module-level instance)
    import django.core.cache as cache_module
    monkeypatch.setattr(cache_module, "cache", fake_cache)
    
    # Also patch the cache module directly
    import api.cache as api_cache_module
    monkeypatch.setattr(api_cache_module, "cache", fake_cache)


@pytest.fixture(autouse=True)
def mock_inference(monkeypatch, request):
    """Replace the Modal proxy calls with deterministic stubs.
    
    Skipped for inference_client tests which mock requests.post directly.
    Also skipped for test_modal_failure_fallback which provides its own mock.
    """
    # Skip for inference_client tests
    if request.module.__name__ == "test_inference_client":
        return
    
    # Skip for test_modal_failure_fallback which tests Modal failure fallback
    if request.node.name == "test_modal_failure_fallback":
        return
    
    # Mock at the usage sites:
    # - views.text_emotion -> uses integrations.clients.text_emotion (imported as modal_text)
    # - candidate_generation.generate_candidates -> uses integrations.clients.music_recommendation (imported as modal_music)
    
    # For views.text_emotion - patch where it's used in views module
    monkeypatch.setattr(
        "api.views.modal_text",
        lambda text: {"emotion": "neutral", "recommendations": []},
    )
    
    # Also patch at source for any other users
    monkeypatch.setattr(
        "integrations.clients.text_emotion",
        lambda text: {"emotion": "neutral", "recommendations": []},
    )
    
    # For candidate_generation.generate_candidates - patch where it's used
    # Only apply default mock if test hasn't already patched it
    default_music_mock = lambda emotion, market=None, history=None, genre=None: {
        "emotion": emotion,
        "market": market,
        "recommendations": [
            {"name": "old", "release_date": "1985-01-01", "duration_ms": 200_000, "popularity": 50},
            {"name": "new", "release_date": "2020-01-01", "duration_ms": 200_000, "popularity": 50},
        ],
    }
    
    # Only apply default mock if not already patched by test
    if not hasattr(monkeypatch, '_music_recommendation_patched'):
        monkeypatch.setattr("api.candidate_generation.modal_music", default_music_mock)
    
    # Also patch the integrations client for history-capturing tests
    def capture_music(emotion, market=None, history=None, genre=None):
        capture_music.last_call = {"emotion": emotion, "market": market, "history": history, "genre": genre}
        return {
            "emotion": emotion,
            "market": market,
            "recommendations": [
                {"name": "old", "release_date": "1985-01-01", "duration_ms": 200_000, "popularity": 50},
                {"name": "new", "release_date": "2020-01-01", "duration_ms": 200_000, "popularity": 50},
            ],
        }
    
    # Only apply capture_music if not already patched
    if not hasattr(monkeypatch, '_music_recommendation_patched'):
        monkeypatch.setattr("integrations.clients.music_recommendation", capture_music)


@pytest.fixture
def make_user():
    """Factory creating a persisted User + UserProfile pair."""
    from api.models import UserProfile
    from users.documents import User

    def _make(username="alice", password="password123", email="alice@example.com"):
        user = User(username=username, email=email)
        user.set_password(password)
        user.save()
        UserProfile(username=username).save()
        return user

    return _make


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client(api_client, make_user):
    """An APIClient already authenticated as a freshly created user."""
    from users.tokens import issue_tokens

    user = make_user()
    tokens = issue_tokens(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    api_client.user = user
    api_client.tokens = tokens
    return api_client