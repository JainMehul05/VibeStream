from django.urls import include, path

from observability.views import metrics

from .feedback_views import feedback, track_feedback_state
from .views import health, music_recommendation, text_emotion
from .health import health_live, health_ready, health_detail

# Speech and facial emotion are served directly by the Modal inference
# service (browser -> Modal); they are intentionally not proxied here.
urlpatterns = [
    # Health checks
    path("health/", health, name="health"),              # Legacy liveness
    path("health/live/", health_live, name="health_live"),    # Liveness probe
    path("health/ready/", health_ready, name="health_ready"), # Readiness probe
    path("health/detail/", health_detail, name="health_detail"), # Detailed health (admin)
    path("text_emotion/", text_emotion, name="text_emotion"),
    path("music_recommendation/", music_recommendation, name="music_recommendation"),
    # Unified RL feedback intake -- see api/feedback_views.py for the contract.
    path("feedback/", feedback, name="feedback"),
    # Read-back of the caller's like/dislike state for a set of track ids.
    path("feedback/tracks/", track_feedback_state, name="track_feedback_state"),
    # SRE telemetry -- admin-only (service token); see observability/views.py.
    path("metrics/", metrics, name="metrics"),
    # GenAI Assistant
    path("genai/", include("genai.urls")),
]
