"""Locust load testing script for VibeStream API.

Run with: locust -f locustfile.py --host=http://localhost:8000
Web UI at http://localhost:8089
"""

import random
import json
from locust import HttpUser, task, between, tag


class VibeStreamUser(HttpUser):
    """Simulated VibeStream user performing typical workflows."""

    wait_time = between(1, 4)  # Wait 1-4 seconds between tasks
    network_timeout = 30.0

    def on_start(self):
        """Called when a user starts - login and store token."""
        self.token = None
        self.user_id = random.randint(1, 1000)
        self.username = f"loadtest{self.user_id}"
        self.password = "loadtest123"

        # Try to login
        self._login()

    def _login(self):
        """Authenticate and store access token."""
        response = self.client.post(
            "/api/v1/users/login/",
            json={"username": self.username, "password": self.password},
            name="Login",
        )
        if response.status_code == 200:
            self.token = response.json().get("access")
            self.auth_headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        else:
            self.token = None
            self.auth_headers = {"Content-Type": "application/json"}

    @task(3)
    @tag("recommendation")
    def get_recommendations(self):
        """Get music recommendations - most common user action."""
        emotions = ["joy", "sadness", "love", "anger", "fear", "neutral"]
        emotion = random.choice(emotions)

        payload = {"emotion": emotion}

        # Add history 30% of the time
        if random.random() < 0.3:
            history = [random.choice(emotions) for _ in range(random.randint(1, 5))]
            payload["history"] = history

        # Add genre 20% of the time
        genres = ["pop", "rock", "hip-hop", "electronic", "r&b", "country", "jazz", "classical"]
        if random.random() < 0.2:
            payload["genre"] = random.choice(genres)

        headers = {**self.auth_headers, "Content-Type": "application/json"}
        with self.client.post(
            "/api/v1/music_recommendation/",
            json=payload,
            headers=headers,
            name="Music Recommendation",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not data.get("recommendations"):
                    response.failure("Empty recommendations")
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("text_emotion")
    def text_emotion(self):
        """Detect emotion from text."""
        texts = [
            "I'm feeling great today!",
            "This is the worst day ever.",
            "I love this song so much.",
            "I'm really angry right now.",
            "I'm scared of what's coming.",
            "Just another normal day.",
        ]
        text = random.choice(texts)

        headers = {**self.auth_headers, "Content-Type": "application/json"}
        with self.client.post(
            "/api/v1/text_emotion/",
            json={"text": text},
            headers=headers,
            name="Text Emotion",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not data.get("emotion"):
                    response.failure("Empty emotion")
            else:
                response.failure(f"Status {response.status_code}")

    @task(2)
    @tag("feedback")
    def submit_feedback(self):
        """Submit track feedback (like/unlike/open_deezer)."""
        signals = ["like", "unlike", "open_deezer"]
        emotions = ["joy", "sadness", "love", "anger", "fear", "neutral"]

        payload = {
            "kind": "track",
            "track_id": f"deezer:{random.randint(100000, 999999)}",
            "signal": random.choice(signals),
            "context_emotion": random.choice(emotions),
        }

        headers = {**self.auth_headers, "Content-Type": "application/json"}
        with self.client.post(
            "/api/v1/feedback/",
            json=payload,
            headers=headers,
            name="Submit Feedback",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 202):
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("mood_feedback")
    def submit_mood_feedback(self):
        """Submit mood correction feedback."""
        emotions = ["joy", "sadness", "love", "anger", "fear", "neutral"]
        input_types = ["text", "speech", "facial"]

        payload = {
            "kind": "mood",
            "predicted": random.choice(emotions),
            "actual": random.choice(emotions),
            "input_type": random.choice(input_types),
            "confidence": random.random(),
        }

        headers = {**self.auth_headers, "Content-Type": "application/json"}
        with self.client.post(
            "/api/v1/feedback/",
            json=payload,
            headers=headers,
            name="Mood Feedback",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 202):
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("profile")
    def get_profile(self):
        """Get user profile."""
        headers = self.auth_headers
        with self.client.get(
            "/api/v1/users/user/profile/",
            headers=headers,
            name="Get Profile",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("feedback_state")
    def get_feedback_state(self):
        """Get track feedback state."""
        headers = self.auth_headers
        with self.client.get(
            "/api/v1/feedback/tracks/?ids=",
            headers=headers,
            name="Feedback State",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("health")
    def health_check(self):
        """Health check endpoint."""
        with self.client.get(
            "/api/v1/health/",
            name="Health Check",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")


class AnonymousUser(HttpUser):
    """Anonymous user performing public API calls."""

    wait_time = between(2, 5)

    @task(3)
    @tag("recommendation")
    def anonymous_recommendations(self):
        """Anonymous music recommendations."""
        emotions = ["joy", "sadness", "love", "anger", "fear", "neutral"]
        emotion = random.choice(emotions)

        with self.client.post(
            "/api/v1/music_recommendation/",
            json={"emotion": emotion},
            name="Anonymous Recommendation",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not data.get("recommendations"):
                    response.failure("Empty recommendations")
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("text_emotion")
    def anonymous_text_emotion(self):
        """Anonymous text emotion detection."""
        texts = [
            "I'm feeling great today!",
            "This is the worst day ever.",
            "I love this song so much.",
        ]
        text = random.choice(texts)

        with self.client.post(
            "/api/v1/text_emotion/",
            json={"text": text},
            name="Anonymous Text Emotion",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")

    @task(1)
    @tag("health")
    def health_check(self):
        """Anonymous health check."""
        with self.client.get(
            "/api/v1/health/",
            name="Anonymous Health Check",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status {response.status_code}")