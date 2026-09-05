"""GenAI Assistant API endpoint."""

from __future__ import annotations

import logging
import os

from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .assistant import GenAIAssistant, GenAIAssistantFactory
from .intent import IntentValidationError

logger = logging.getLogger(__name__)

# Lazy singleton for assistant
_assistant_instance = None


def get_assistant(request) -> GenAIAssistant:
    """Get or create assistant instance for request."""
    global _assistant_instance

    # Use service token for API calls from Django
    service_token = getattr(settings, "MODAL_SERVICE_TOKEN", None)
    api_base_url = getattr(settings, "API_V1_URL", "http://localhost:8000")

    # For authenticated users, use their JWT for tool calls
    auth_token = None
    if hasattr(request, "user") and request.user.is_authenticated:
        # Get user's access token from request
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]

    if _assistant_instance is None:
        # Check if we have real LLM credentials
        openai_key = os.environ.get("OPENAI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        if openai_key:
            _assistant_instance = GenAIAssistantFactory.create_openai(
                api_base_url=api_base_url,
                auth_token=service_token,  # Use service token for backend API calls
                openai_api_key=openai_key,
            )
        elif anthropic_key:
            _assistant_instance = GenAIAssistantFactory.create_anthropic(
                api_base_url=api_base_url,
                auth_token=service_token,
                anthropic_api_key=anthropic_key,
            )
        else:
            # Fallback to mock for testing
            _assistant_instance = GenAIAssistantFactory.create_mock(api_base_url)

    return _assistant_instance


# Swagger schemas
_GENAI_REQUEST_BODY = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "message": openapi.Schema(
            type=openapi.TYPE_STRING,
            minLength=1,
            maxLength=2000,
            example="Give me something happy for studying",
            description="Natural language request",
        ),
    },
    required=["message"],
)

_GENAI_RESPONSE = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
        "message": openapi.Schema(type=openapi.TYPE_STRING),
        "intent": openapi.Schema(type=openapi.TYPE_OBJECT),
        "tool_results": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_OBJECT)),
        "error": openapi.Schema(type=openapi.TYPE_STRING),
    },
)


@swagger_auto_schema(
    method="post",
    tags=["GenAI"],
    operation_summary="Chat with VibeStream GenAI Assistant",
    operation_description=(
        "Natural language interface for music recommendations and profile queries.\n\n"
        "**Examples:**\n"
        "- \"Give me something happy for working out\"\n"
        "- \"Play sad songs for studying\"\n"
        "- \"I want romantic jazz music\"\n"
        "- \"Why did you recommend this song?\"\n"
        "- \"I like this track\"\n"
        "- \"Show my preferences\"\n"
        "- \"Show my profile\"\n\n"
        "Requires authentication (JWT). The assistant uses structured intent "
        "extraction and validated tool calling to interact with VibeStream APIs."
    ),
    request_body=_GENAI_REQUEST_BODY,
    responses={
        200: openapi.Response("Assistant response", _GENAI_RESPONSE),
        400: "Invalid request",
        401: "Authentication required",
        503: "GenAI service unavailable",
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def genai_chat(request):
    """Chat with the GenAI assistant."""
    message = (request.data.get("message") or "").strip()
    if not message:
        return Response(
            {"error": "Message is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(message) > 2000:
        return Response(
            {"error": "Message too long (max 2000 characters)"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        assistant = get_assistant(request)
        response = assistant.process_message(message)

        return Response({
            "success": response.success,
            "message": response.message,
            "intent": response.intent.model_dump() if response.intent else None,
            "tool_results": [
                {"success": r.success, "data": r.data, "error": r.error}
                for r in response.tool_results
            ],
            "error": response.error,
        }, status=status.HTTP_200_OK)

    except IntentValidationError as e:
        logger.warning("GenAI intent validation failed: %s", e)
        return Response(
            {"success": False, "message": str(e), "error": "intent_validation"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.exception("GenAI chat error")
        return Response(
            {"success": False, "message": "GenAI service temporarily unavailable", "error": "service_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@swagger_auto_schema(
    method="post",
    tags=["GenAI"],
    operation_summary="Clear GenAI conversation history",
    operation_description="Clears the conversation context for the GenAI assistant.",
    responses={
        200: "History cleared",
        401: "Authentication required",
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def genai_clear_history(request):
    """Clear conversation history."""
    try:
        assistant = get_assistant(request)
        assistant.clear_history()
        return Response({"message": "Conversation history cleared"}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.exception("GenAI clear history error")
        return Response(
            {"error": "Failed to clear history"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@swagger_auto_schema(
    method="get",
    tags=["GenAI"],
    operation_summary="Get available GenAI tools",
    operation_description="Returns list of available tools the assistant can use.",
    responses={
        200: "List of available tools",
        401: "Authentication required",
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def genai_tools(request):
    """Get available tools."""
    try:
        assistant = get_assistant(request)
        tools = assistant.get_available_tools()
        return Response({"tools": tools}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.exception("GenAI tools error")
        return Response(
            {"error": "Failed to get tools"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


__all__ = [
    "genai_chat",
    "genai_clear_history",
    "genai_tools",
]