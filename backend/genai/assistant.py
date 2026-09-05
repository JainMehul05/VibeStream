"""GenAI Assistant - Main entry point for natural language interaction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .intent import IntentExtractor, IntentValidationError, MockLLMClient
from .tools import ToolRegistry, ToolCall, ToolResult
from .schemas import AnyIntent, IntentType, build_prompt

logger = logging.getLogger(__name__)


@dataclass
class AssistantResponse:
    """Response from the GenAI assistant."""
    success: bool
    message: str
    intent: Optional[AnyIntent] = None
    tool_results: list[ToolResult] = field(default_factory=list)
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class GenAIAssistant:
    """Main GenAI assistant for VibeStream.

    Flow:
    1. User sends natural language message
    2. IntentExtractor converts to structured intent
    3. Intent validated against schema
    4. ToolRegistry executes corresponding tool
    5. Results formatted into natural language response
    """

    def __init__(
        self,
        api_base_url: str,
        auth_token: str = None,
        llm_client: IntentExtractor = None,
        tool_registry: ToolRegistry = None,
    ):
        self.api_base_url = api_base_url
        self.auth_token = auth_token
        self.llm_client = llm_client or MockLLMClient()
        self.intent_extractor = IntentExtractor(self.llm_client)
        self.tool_registry = tool_registry or ToolRegistry(api_base_url, auth_token)
        self.conversation_history: list[dict] = []

    def process_message(self, user_message: str, user_context: dict = None) -> AssistantResponse:
        """Process a user message and return assistant response."""
        logger.info("Processing message: %s", user_message[:100])

        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_message})

        # Extract intent
        intent, error = self.intent_extractor.extract_with_fallback(
            user_message, self.conversation_history
        )

        if error:
            # Clarification needed or invalid intent
            response = AssistantResponse(
                success=False,
                message=error,
                error=error,
            )
            self.conversation_history.append({"role": "assistant", "content": error})
            return response

        # Validate intent type is supported
        if intent.intent == IntentType.UNKNOWN:
            response = AssistantResponse(
                success=False,
                message="I didn't understand that. Could you rephrase?",
                error="unknown_intent",
            )
            self.conversation_history.append({"role": "assistant", "content": response.message})
            return response

        # Execute tool
        tool_call = ToolCall(
            name=intent.intent.value,
            arguments=intent.model_dump(exclude={"intent"}),
            intent=intent,
        )

        tool_result = self.tool_registry.execute_tool(tool_call, user_context)

        # Format response
        response_message = self._format_response(intent, tool_result)

        response = AssistantResponse(
            success=tool_result.success,
            message=response_message,
            intent=intent,
            tool_results=[tool_result],
            error=tool_result.error if not tool_result.success else None,
        )

        self.conversation_history.append({"role": "assistant", "content": response_message})
        return response

    def _format_response(self, intent: AnyIntent, result: ToolResult) -> str:
        """Format tool result into natural language response."""
        if not result.success:
            return f"I couldn't complete that request: {result.error}"

        if intent.intent == IntentType.RECOMMEND_MUSIC:
            return self._format_recommendations(result.data)
        elif intent.intent == IntentType.GET_PREFERENCES:
            return self._format_preferences(result.data)
        elif intent.intent == IntentType.GET_EXPLANATION:
            return self._format_explanation(result.data)
        elif intent.intent == IntentType.SUBMIT_FEEDBACK:
            return self._format_feedback(result.data)
        elif intent.intent == IntentType.GET_PROFILE:
            return self._format_profile(result.data)
        return "Done!"

    def _format_recommendations(self, data: dict) -> str:
        """Format recommendation results."""
        emotion = data.get("emotion", "unknown")
        tracks = data.get("recommendations", [])
        degraded = data.get("degraded", False)

        if not tracks:
            return f"I couldn't find any recommendations for {emotion} mood right now."

        lines = [f"Here are some {emotion} tracks for you:"]
        for i, track in enumerate(tracks[:10], 1):
            name = track.get("name", "Unknown")
            artist = track.get("artist", "Unknown")
            explanation = track.get("explanation", "")
            lines.append(f"{i}. **{name}** by {artist}")
            if explanation:
                lines.append(f"   *{explanation}*")

        if degraded:
            lines.append("\n_Note: Using fallback recommendations due to service limitations._")

        return "\n".join(lines)

    def _format_preferences(self, data: dict) -> str:
        """Format preferences results."""
        if not data:
            return "You don't have any learned preferences yet. Start liking tracks to build your profile!"

        lines = ["Here's what I've learned about your taste:"]

        if data.get("genre_preferences"):
            top_genres = list(data["genre_preferences"].items())[:5]
            lines.append("\n**Favorite Genres:**")
            for genre, weight in top_genres:
                lines.append(f"  • {genre.title()} ({weight:.2f})")

        if data.get("artist_preferences"):
            top_artists = list(data["artist_preferences"].items())[:5]
            lines.append("\n**Favorite Artists:**")
            for artist, weight in top_artists:
                lines.append(f"  • {artist} ({weight:.2f})")

        if data.get("era_preferences"):
            top_eras = list(data["era_preferences"].items())[:5]
            lines.append("\n**Favorite Eras:**")
            for era, weight in top_eras:
                lines.append(f"  • {era} ({weight:.2f})")

        if data.get("exploration_preference") is not None:
            explore = data["exploration_preference"]
            lines.append(f"\n**Exploration Level:** {explore:.0%} (lower = more familiar, higher = more discovery)")

        total_interactions = sum(data.get("interaction_counts", {}).values())
        if total_interactions:
            lines.append(f"\n**Total Interactions:** {total_interactions}")

        return "\n".join(lines)

    def _format_explanation(self, data: dict) -> str:
        """Format explanation results."""
        track = data.get("track", "this track")
        artist = data.get("artist", "")
        explanation = data.get("explanation", "Recommended for you")
        signals = data.get("ranking_signals", {})

        lines = [f"**{track}** by {artist} was recommended because:"]
        lines.append(f"  • {explanation}")

        if signals.get("personalization", {}).get("applied"):
            pers = signals["personalization"]
            if pers.get("artist_match"):
                lines.append(f"  • Matches your preference for {pers['artist_match']}")
            if pers.get("genre_match"):
                lines.append(f"  • Matches your preference for {pers['genre_match']}")
            if pers.get("era_match"):
                lines.append(f"  • Matches your preference for {pers['era_match']} era")

        if signals.get("bandit"):
            bandit = signals["bandit"]
            if bandit.get("exploration"):
                lines.append("  • Exploration pick based on your taste profile")
            elif bandit.get("exploitation"):
                lines.append("  • Recommended based on your listening history")

        if signals.get("diversity"):
            lines.append("  • Added for variety")

        return "\n".join(lines)

    def _format_feedback(self, data: dict) -> str:
        """Format feedback confirmation."""
        message = data.get("message", "Feedback recorded")
        event_id = data.get("event_id")
        if event_id:
            return f"Thanks! Your feedback has been recorded (event: {event_id}). Your recommendations will adapt."
        return "Thanks! Your feedback has been recorded. Your recommendations will adapt."

    def _format_profile(self, data: dict) -> str:
        """Format profile results."""
        lines = ["**Your VibeStream Profile**"]

        mood_history = data.get("mood_history", [])
        if mood_history:
            lines.append(f"\n**Recent Moods:** {', '.join(mood_history[-10:])}")

        listening = data.get("listening_history", [])
        if listening:
            lines.append(f"\n**Recent Listens:** {len(listening)} tracks")
            for track in listening[-5:]:
                if isinstance(track, dict):
                    lines.append(f"  • {track.get('name', 'Unknown')} by {track.get('artist', 'Unknown')}")

        recs = data.get("recommendations", [])
        if recs:
            lines.append(f"\n**Saved Recommendations:** {len(recs)}")

        return "\n".join(lines)

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history.clear()

    def get_available_tools(self) -> list[str]:
        """Get list of available tool names."""
        return list(self.tool_registry.tools.keys())


class GenAIAssistantFactory:
    """Factory for creating GenAI assistant with different configurations."""

    @staticmethod
    def create_mock(api_base_url: str = "http://localhost:8000") -> GenAIAssistant:
        """Create assistant with mock LLM for testing."""
        return GenAIAssistant(
            api_base_url=api_base_url,
            auth_token=None,
            llm_client=MockLLMClient(),
        )

    @staticmethod
    def create_openai(
        api_base_url: str,
        auth_token: str,
        openai_api_key: str = None,
        model: str = "gpt-4o-mini",
    ) -> GenAIAssistant:
        """Create assistant with OpenAI LLM."""
        from .intent import OpenAIClient
        llm = OpenAIClient(api_key=openai_api_key, model=model)
        return GenAIAssistant(
            api_base_url=api_base_url,
            auth_token=auth_token,
            llm_client=IntentExtractor(llm),
        )

    @staticmethod
    def create_anthropic(
        api_base_url: str,
        auth_token: str,
        anthropic_api_key: str = None,
        model: str = "claude-3-haiku-20240307",
    ) -> GenAIAssistant:
        """Create assistant with Anthropic LLM."""
        from .intent import AnthropicClient
        llm = AnthropicClient(api_key=anthropic_api_key, model=model)
        return GenAIAssistant(
            api_base_url=api_base_url,
            auth_token=auth_token,
            llm_client=IntentExtractor(llm),
        )


__all__ = [
    "AssistantResponse",
    "GenAIAssistant",
    "GenAIAssistantFactory",
]