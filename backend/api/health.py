"""Health check endpoints for liveness and readiness probes."""

import logging
from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from api.cache import get_cache_stats
from api.retry import MONGODB_RETRY_POLICY, REDIS_RETRY_POLICY

import structlog

logger = structlog.get_logger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class LivenessView(View):
    """Liveness probe - indicates if the process is alive.

    Does NOT check dependencies. Used by orchestration to detect
    if the process needs to be restarted.
    """

    def get(self, request):
        return JsonResponse({"status": "ok", "service": "django"})


@method_decorator(csrf_exempt, name="dispatch")
class ReadinessView(View):
    """Readiness probe - indicates if the service can serve traffic.

    Checks critical dependencies:
    - MongoDB connectivity
    - Redis connectivity (if configured)
    - Modal inference service (optional, for graceful degradation)
    """

    def get(self, request):
        checks = {}
        overall_ready = True

        # Check MongoDB
        try:
            from mongoengine.connection import get_connection
            client = get_connection()
            client.admin.command("ping")
            checks["mongodb"] = {"status": "ok"}
        except Exception as e:  # noqa: BLE001
            checks["mongodb"] = {"status": "failed", "error": str(e)}
            overall_ready = False

        # Check Redis (if configured)
        redis_url = getattr(settings, "CACHE_REDIS_URL", "")
        if redis_url:
            try:
                from django.core.cache import cache
                redis_client = cache._cache.get_client(write=True)
                redis_client.ping()
                checks["redis"] = {"status": "ok"}
            except Exception as e:  # noqa: BLE001
                checks["redis"] = {"status": "failed", "error": str(e)}
                overall_ready = False
        else:
            checks["redis"] = {"status": "not_configured"}

        # Check Modal inference (optional - degraded mode allowed)
        modal_url = getattr(settings, "MODAL_INFERENCE_URL", "")
        if modal_url:
            try:
                import requests
                resp = requests.get(f"{modal_url.rstrip('/')}/health", timeout=5)
                if resp.status_code == 200:
                    checks["modal"] = {"status": "ok"}
                else:
                    checks["modal"] = {"status": "degraded", "http_status": resp.status_code}
            except Exception as e:  # noqa: BLE001
                checks["modal"] = {"status": "degraded", "error": str(e)}
        else:
            checks["modal"] = {"status": "not_configured"}

        status_code = 200 if overall_ready else 503
        return JsonResponse(
            {
                "status": "ready" if overall_ready else "not_ready",
                "service": "django",
                "checks": checks,
            },
            status=status_code,
        )


@method_decorator(csrf_exempt, name="dispatch")
class HealthDetailView(View):
    """Detailed health information for debugging."""

    def get(self, request):
        # Only allow in DEBUG or with service token
        if not settings.DEBUG:
            auth_header = request.META.get("HTTP_AUTHORIZATION", "")
            expected = getattr(settings, "ADMIN_METRICS_TOKEN", "") or getattr(settings, "MODAL_SERVICE_TOKEN", "")
            if not auth_header.startswith("Bearer ") or auth_header[7:] != expected:
                return JsonResponse({"error": "Unauthorized"}, status=401)

        # Collect detailed info
        from api.observability.recorder import get_recorder
        from api.observability.store import _get_collection

        recorder = get_recorder()
        live_stats = recorder.snapshot()

        cache_stats = get_cache_stats()

        # MongoDB info
        mongo_info = {}
        try:
            from mongoengine.connection import get_connection
            client = get_connection()
            db_name = getattr(settings, "MONGO_DB_NAME", "emotion_based_music_db")
            db = client[db_name]
            collections = db.list_collection_names()
            mongo_info = {
                "collections": len(collections),
                "collection_names": collections,
            }
        except Exception as e:  # noqa: BLE001
            mongo_info = {"error": str(e)}

        return JsonResponse({
            "service": "django",
            "version": getattr(settings, "PIPELINE_VERSION", "1"),
            "debug": settings.DEBUG,
            "cache": cache_stats,
            "mongodb": mongo_info,
            "live_metrics": live_stats,
            "recorder": {
                "container_id": recorder.container_id,
                "uptime_seconds": recorder.uptime_seconds(),
            },
        })


# Function-based views for URL routing
def health_live(request):
    return LivenessView.as_view()(request)


def health_ready(request):
    return ReadinessView.as_view()(request)


def health_detail(request):
    return HealthDetailView.as_view()(request)