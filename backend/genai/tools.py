"""Tool registry and execution framework for GenAI assistant.

Tools are the bridge between structured intents and the actual VibeStream API.
Each tool validates authorization, executes the API call, and returns results.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

from .schemas import AnyIntent, IntentType

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """A validated tool call ready for execution."""
    name: str
    arguments: dict
    intent: AnyIntent


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    data: Any = None
    error: str = None
    metadata: dict = None


class ToolError(Exception):
    """Tool execution error."""

    def __init__(self, message: str, tool_name: str = None):
        super().__init__(message)
        self.tool_name = tool_name


class BaseTool(ABC):
    """Base class for all tools."""

    def __init__(self, api_base_url: str, auth_token: str = None):
        self.api_base_url = api_base_url.rstrip("/")
        self.auth_token = auth_token
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if auth_token:
            self.session.headers.update({"Authorization": f"Bearer {auth_token}"})

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (must match intent type)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""
        pass

    @abstractmethod
    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def _check_auth(self, user_context: dict = None) -> bool:
        """Check if user is authenticated for this tool."""
        # Most tools require authentication
        if not self.auth_token:
            return False
        return True

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make HTTP request to VibeStream API."""
        url = f"{self.api_base_url}{endpoint}"
        return self.session.request(method, url, timeout=30, **kwargs)


class RecommendMusicTool(BaseTool):
    """Get music recommendations for an emotion."""

    @property
    def name(self) -> str:
        return "recommend_music"

    @property
    def description(self) -> str:
        return "Get music recommendations for a given emotion"

    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        if not self._check_auth(user_context):
            return ToolResult(success=False, error="Authentication required")

        payload = {
            "emotion": arguments["emotion"],
            "history": [] if not arguments.get("use_history") else None,  # API will use user's history
        }
        if arguments.get("genre"):
            payload["genre"] = arguments["genre"]
        if arguments.get("limit"):
            # Note: API has fixed limit, but we can note the request
            pass

        try:
            response = self._make_request("POST", "/api/v1/music_recommendation/", json=payload)
            if response.status_code == 200:
                data = response.json()
                return ToolResult(
                    success=True,
                    data={
                        "emotion": data.get("emotion"),
                        "recommendations": data.get("recommendations", []),
                        "degraded": data.get("degraded", False),
                    },
                )
            return ToolResult(success=False, error=f"API error: {response.status_code}")
        except requests.exceptions.Timeout:
            return ToolResult(success=False, error="Request timeout: API did not respond in time")
        except requests.exceptions.RequestException as e:
            return ToolResult(success=False, error=f"Request failed: {e}")
        except Exception as e:
            logger.error("Recommend music tool failed: %s", e)
            return ToolResult(success=False, error=str(e))


class GetPreferencesTool(BaseTool):
    """Get user's learned preferences."""

    @property
    def name(self) -> str:
        return "get_preferences"

    @property
    def description(self) -> str:
        return "Get the user's learned music preferences and taste profile"

    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        if not self._check_auth(user_context):
            return ToolResult(success=False, error="Authentication required")

        try:
            response = self._make_request("GET", "/api/v1/users/user/profile/")
            if response.status_code == 200:
                data = response.json()
                profile = data.get("profile", {})
                prefs = {
                    "genre_preferences": profile.get("genre_preferences", {}),
                    "artist_preferences": profile.get("artist_preferences", {}),
                    "era_preferences": profile.get("era_preferences", {}),
                    "mood_preferences": profile.get("mood_preferences", {}),
                    "exploration_preference": profile.get("exploration_preference", 0.3),
                    "interaction_counts": profile.get("interaction_counts", {}),
                }
                detail = arguments.get("detail_level", "summary")
                if detail == "summary":
                    # Return top 3 for each category
                    summary = {}
                    for key, val in prefs.items():
                        if isinstance(val, dict):
                            sorted_items = sorted(val.items(), key=lambda x: x[1], reverse=True)
                            summary[key] = dict(sorted_items[:3])
                        else:
                            summary[key] = val
                    return ToolResult(success=True, data=summary)
                return ToolResult(success=True, data=prefs)
            return ToolResult(success=False, error=f"API error: {response.status_code}")
        except Exception as e:
            logger.error("Get preferences tool failed: %s", e)
            return ToolResult(success=False, error=str(e))


class GetExplanationTool(BaseTool):
    """Get explanation for a recommendation."""

    @property
    def name(self) -> str:
        return "get_explanation"

    @property
    def description(self) -> str:
        return "Get the explanation for why a specific track was recommended"

    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        if not self._check_auth(user_context):
            return ToolResult(success=False, error="Authentication required")

        track_id = arguments["track_id"]
        # The explanation is embedded in the recommendation response
        # We need to fetch recommendations and find the track
        context_emotion = arguments.get("context_emotion")

        try:
            # Get fresh recommendations to find the track
            payload = {"emotion": context_emotion or "neutral", "history": []}
            response = self._make_request("POST", "/api/v1/music_recommendation/", json=payload)
            if response.status_code == 200:
                data = response.json()
                recommendations = data.get("recommendations", [])

                # Find matching track
                track = None
                for rec in recommendations:
                    rec_id = rec.get("external_url", "").split("/")[-1]
                    if rec_id in track_id or track_id in rec_id or rec.get("name") == track_id:
                        track = rec
                        break

                if track:
                    return ToolResult(
                        success=True,
                        data={
                            "track": track.get("name"),
                            "artist": track.get("artist"),
                            "explanation": track.get("explanation", "Recommended for you"),
                            "ranking_signals": track.get("ranking_signals", {}),
                        },
                    )
                return ToolResult(success=False, error="Track not found in current recommendations")
            return ToolResult(success=False, error=f"API error: {response.status_code}")
        except Exception as e:
            logger.error("Get explanation tool failed: %s", e)
            return ToolResult(success=False, error=str(e))


class SubmitFeedbackTool(BaseTool):
    """Submit feedback on a recommendation."""

    @property
    def name(self) -> str:
        return "submit_feedback"

    @property
    def description(self) -> str:
        return "Submit like/unlike/open_deezer feedback for a track"

    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        if not self._check_auth(user_context):
            return ToolResult(success=False, error="Authentication required")

        payload = {
            "kind": "track",
            "track_id": arguments["track_id"],
            "signal": arguments["signal"],
            "context_emotion": arguments.get("context_emotion"),
        }

        try:
            response = self._make_request("POST", "/api/v1/feedback/", json=payload)
            if response.status_code in (200, 202):
                return ToolResult(success=True, data=response.json())
            return ToolResult(success=False, error=f"API error: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error("Submit feedback tool failed: %s", e)
            return ToolResult(success=False, error=str(e))


class GetProfileTool(BaseTool):
    """Get user profile/dashboard."""

    @property
    def name(self) -> str:
        return "get_profile"

    @property
    def description(self) -> str:
        return "Get the user's profile including mood history, listening history, and saved recommendations"

    def execute(self, arguments: dict, user_context: dict = None) -> ToolResult:
        if not self._check_auth(user_context):
            return ToolResult(success=False, error="Authentication required")

        try:
            response = self._make_request("GET", "/api/v1/users/user/profile/")
            if response.status_code == 200:
                data = response.json()
                profile = data.get("profile", {})
                result = {
                    "mood_history": profile.get("mood_history", []),
                    "listening_history": profile.get("listening_history", []),
                    "recommendations": profile.get("recommendations", []),
                }
                if not arguments.get("include_history", True):
                    result.pop("listening_history", None)
                    result.pop("mood_history", None)
                return ToolResult(success=True, data=result)
            return ToolResult(success=False, error=f"API error: {response.status_code}")
        except Exception as e:
            logger.error("Get profile tool failed: %s", e)
            return ToolResult(success=False, error=str(e))


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self, api_base_url: str, auth_token: str = None):
        self.tools: dict[str, BaseTool] = {}
        self._register_default_tools(api_base_url, auth_token)

    def _register_default_tools(self, api_base_url: str, auth_token: str):
        """Register all default VibeStream tools."""
        self.register(RecommendMusicTool(api_base_url, auth_token))
        self.register(GetPreferencesTool(api_base_url, auth_token))
        self.register(GetExplanationTool(api_base_url, auth_token))
        self.register(SubmitFeedbackTool(api_base_url, auth_token))
        self.register(GetProfileTool(api_base_url, auth_token))

    def register(self, tool: BaseTool):
        """Register a tool."""
        self.tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self.tools.get(name)

    def get_schema(self) -> dict:
        """Get OpenAPI-style schema for all tools (for LLM function calling)."""
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": self._get_tool_parameters(tool),
                }
                for tool in self.tools.values()
            ]
        }

    def _get_tool_parameters(self, tool: BaseTool) -> dict:
        """Get JSON schema for tool parameters."""
        # This would ideally be auto-generated from Pydantic models
        schemas = {
            "recommend_music": {
                "type": "object",
                "properties": {
                    "emotion": {"type": "string", "enum": ["joy", "sadness", "love", "anger", "fear", "neutral"]},
                    "genre": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "use_history": {"type": "boolean"},
                },
                "required": ["emotion"],
            },
            "get_preferences": {
                "type": "object",
                "properties": {
                    "detail_level": {"type": "string", "enum": ["summary", "full"]},
                },
            },
            "get_explanation": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "string"},
                    "context_emotion": {"type": "string"},
                },
                "required": ["track_id"],
            },
            "submit_feedback": {
                "type": "object",
                "properties": {
                    "track_id": {"type": "string"},
                    "signal": {"type": "string", "enum": ["like", "unlike", "open_deezer"]},
                    "context_emotion": {"type": "string"},
                },
                "required": ["track_id", "signal"],
            },
            "get_profile": {
                "type": "object",
                "properties": {
                    "include_history": {"type": "boolean"},
                },
            },
        }
        return schemas.get(tool.name, {"type": "object", "properties": {}})

    def execute_tool(self, tool_call: ToolCall, user_context: dict = None) -> ToolResult:
        """Execute a tool call."""
        tool = self.get(tool_call.name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {tool_call.name}")

        logger.info("Executing tool: %s with args: %s", tool_call.name, tool_call.arguments)
        try:
            result = tool.execute(tool_call.arguments, user_context)
            logger.info("Tool %s result: success=%s", tool_call.name, result.success)
            return result
        except Exception as e:
            logger.error("Tool %s execution failed: %s", tool_call.name, e)
            return ToolResult(success=False, error=str(e))


__all__ = [
    "ToolCall",
    "ToolResult",
    "ToolError",
    "BaseTool",
    "RecommendMusicTool",
    "GetPreferencesTool",
    "GetExplanationTool",
    "SubmitFeedbackTool",
    "GetProfileTool",
    "ToolRegistry",
]