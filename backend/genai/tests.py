"""Tests for GenAI Assistant - Standalone (no Django test runner)."""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure minimal Django settings before any Django imports
import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="test-secret-key-for-genai-tests",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
            "drf_yasg",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework.authentication.SessionAuthentication",
            ],
        },
        MODAL_SERVICE_TOKEN="test-service-token",
        API_V1_URL="http://localhost:8000",
    )

django.setup()

# Now import GenAI modules
from genai.intent import (
    IntentExtractor,
    IntentSchema,
    IntentValidationError,
    MockLLMClient,
    RecommendMusicIntent,
)
from genai.schemas import IntentType
from genai.tools import ToolRegistry, ToolCall, RecommendMusicTool
from genai.assistant import GenAIAssistant, GenAIAssistantFactory


def run_tests():
    """Run all tests manually."""
    passed = 0
    failed = 0

    def assert_test(name, condition, msg=""):
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {name}")
            passed += 1
        else:
            print(f"  FAIL: {name}: {msg}")
            failed += 1

    print("\n=== TestMockLLMClient ===")
    client = MockLLMClient()

    # Test with proper prompt format
    prompt = "User: Give me happy music\nAssistant:"
    response = client.complete(prompt)
    data = json.loads(response)
    assert_test("happy_recommendation", data["intent"] == "recommend_music" and data["emotion"] == "joy")

    prompt = "User: Play sad songs\nAssistant:"
    response = client.complete(prompt)
    data = json.loads(response)
    assert_test("sad_recommendation", data["intent"] == "recommend_music" and data["emotion"] == "sadness")

    prompt = "User: What are my preferences?\nAssistant:"
    response = client.complete(prompt)
    data = json.loads(response)
    assert_test("preferences_query", data["intent"] == "get_preferences")

    print("\n=== TestIntentSchema ===")
    data = {"intent": "recommend_music", "emotion": "joy", "limit": 10, "use_history": True}
    intent = IntentSchema.validate(data)
    assert_test("valid_recommend_intent", isinstance(intent, RecommendMusicIntent) and intent.emotion == "joy")

    data = {"intent": "recommend_music", "emotion": "happiness"}
    try:
        IntentSchema.validate(data)
        assert_test("invalid_emotion", False, "Should have raised IntentValidationError")
    except IntentValidationError:
        assert_test("invalid_emotion", True)

    data = {"intent": "unknown", "clarification": "Please clarify"}
    try:
        IntentSchema.validate(data)
        assert_test("unknown_intent", False, "Should have raised IntentValidationError")
    except IntentValidationError:
        assert_test("unknown_intent", True)

    print("\n=== TestIntentExtractor ===")
    extractor = IntentExtractor(MockLLMClient())

    intent, error = extractor.extract_with_fallback("Give me happy music for working out")
    assert_test("extract_recommend_music", error is None and intent.intent == IntentType.RECOMMEND_MUSIC and intent.emotion == "joy")

    # Test with conversation history
    intent1, _ = extractor.extract_with_fallback("Play happy music")
    intent2, _ = extractor.extract_with_fallback("Actually, make it sad", [{"role": "user", "content": "Play happy music"}])
    assert_test("extract_with_context", intent1.emotion == "joy" and intent2.emotion == "sadness")

    print("\n=== TestToolRegistry ===")
    registry = ToolRegistry("http://localhost:8000", "test-token")
    tools = registry.get_schema()["tools"]
    tool_names = [t["name"] for t in tools]
    assert_test("tools_registered", all(t in tool_names for t in ["recommend_music", "get_preferences", "get_explanation", "submit_feedback", "get_profile"]))

    call = ToolCall(name="unknown_tool", arguments={}, intent=None)
    result = registry.execute_tool(call)
    assert_test("execute_unknown_tool", not result.success and "Unknown tool" in result.error)

    print("\n=== TestRecommendMusicTool ===")
    tool = RecommendMusicTool("http://localhost:8000", "test-token")

    with patch("requests.Session.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "emotion": "joy",
            "recommendations": [{"name": "Happy Song", "artist": "Artist", "explanation": "Matches your joy mood"}],
            "degraded": False,
        }
        mock_request.return_value = mock_response

        result = tool.execute({"emotion": "joy", "limit": 10, "use_history": True})
        assert_test("execute_success", result.success and result.data["emotion"] == "joy")

    # Test unauthorized
    tool_no_auth = RecommendMusicTool("http://localhost:8000", None)
    result = tool_no_auth.execute({"emotion": "joy"})
    assert_test("execute_unauthorized", not result.success and result.error == "Authentication required")

    print("\n=== TestGenAIAssistant ===")
    assistant = GenAIAssistantFactory.create_mock("http://localhost:8000")

    # Mock the tool registry to return success for recommend_music
    with patch.object(assistant.tool_registry, "execute_tool") as mock_execute:
        mock_execute.return_value = MagicMock(success=True, data={"emotion": "joy", "recommendations": []})
        response = assistant.process_message("Give me happy music")
        assert_test("process_message_mock", response.intent is not None and response.intent.intent == IntentType.RECOMMEND_MUSIC and response.intent.emotion == "joy")

    # Mock for preferences query
    with patch.object(assistant.tool_registry, "execute_tool") as mock_execute:
        mock_execute.return_value = MagicMock(success=True, data={})
        response = assistant.process_message("What are my preferences?")
        assert_test("process_preferences_query", response.intent is not None and response.intent.intent == IntentType.GET_PREFERENCES)

    # Test conversation history
    assistant.clear_history()
    with patch.object(assistant.tool_registry, "execute_tool") as mock_execute:
        mock_execute.return_value = MagicMock(success=True, data={"emotion": "joy", "recommendations": []})
        response = assistant.process_message("Give me happy music")
        assert_test("conversation_history", len(assistant.conversation_history) == 2)  # user + assistant

    assistant.clear_history()
    assert_test("clear_history", len(assistant.conversation_history) == 0)

    print("\n=== Summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)