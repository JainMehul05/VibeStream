"""Structured intent schemas for GenAI tool calling.

Uses Pydantic for validation. All LLM output must conform to these schemas
before being executed as tool calls.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


class IntentType(str, Enum):
    """Supported intent types."""
    RECOMMEND_MUSIC = "recommend_music"
    GET_PREFERENCES = "get_preferences"
    GET_EXPLANATION = "get_explanation"
    SUBMIT_FEEDBACK = "submit_feedback"
    GET_PROFILE = "get_profile"
    UNKNOWN = "unknown"


class RecommendMusicIntent(BaseModel):
    """Intent to get music recommendations."""
    intent: Literal[IntentType.RECOMMEND_MUSIC] = IntentType.RECOMMEND_MUSIC
    emotion: str = Field(description="Target emotion (joy, sadness, love, anger, fear, neutral)")
    genre: Optional[str] = Field(default=None, description="Optional genre filter")
    limit: int = Field(default=10, ge=1, le=50, description="Number of recommendations")
    use_history: bool = Field(default=True, description="Whether to use mood history")

    @field_validator("emotion")
    @classmethod
    def validate_emotion(cls, v: str) -> str:
        valid = {"joy", "sadness", "love", "anger", "fear", "neutral"}
        v_lower = v.lower().strip()
        if v_lower not in valid:
            raise ValueError(f"Emotion must be one of {valid}")
        return v_lower


class GetPreferencesIntent(BaseModel):
    """Intent to get user's learned preferences."""
    intent: Literal[IntentType.GET_PREFERENCES] = IntentType.GET_PREFERENCES
    detail_level: Literal["summary", "full"] = Field(default="summary")


class GetExplanationIntent(BaseModel):
    """Intent to get explanation for a recommendation."""
    intent: Literal[IntentType.GET_EXPLANATION] = IntentType.GET_EXPLANATION
    track_id: str = Field(description="Track ID to explain")
    context_emotion: Optional[str] = Field(default=None)


class SubmitFeedbackIntent(BaseModel):
    """Intent to submit feedback on a recommendation."""
    intent: Literal[IntentType.SUBMIT_FEEDBACK] = IntentType.SUBMIT_FEEDBACK
    track_id: str = Field(description="Track ID")
    signal: Literal["like", "unlike", "open_deezer"] = Field(description="Feedback signal")
    context_emotion: Optional[str] = Field(default=None)


class GetProfileIntent(BaseModel):
    """Intent to get user profile/dashboard."""
    intent: Literal[IntentType.GET_PROFILE] = IntentType.GET_PROFILE
    include_history: bool = Field(default=True)


# Union of all intent types
AnyIntent = (
    RecommendMusicIntent
    | GetPreferencesIntent
    | GetExplanationIntent
    | SubmitFeedbackIntent
    | GetProfileIntent
)


# System prompt for the LLM
SYSTEM_PROMPT = """You are VibeStream's music assistant. Convert user requests into structured tool calls.

Available tools:
1. recommend_music(emotion, genre?, limit?, use_history?) - Get music recommendations for an emotion
2. get_preferences(detail_level?) - Get user's learned music preferences
3. get_explanation(track_id, context_emotion?) - Get why a track was recommended
4. submit_feedback(track_id, signal, context_emotion?) - Submit like/unlike/open_deezer feedback
5. get_profile(include_history?) - Get user profile dashboard

Rules:
- ALWAYS use the exact tool names and parameter names above
- Emotion must be one of: joy, sadness, love, anger, fear, neutral
- Signal must be one of: like, unlike, open_deezer
- If user doesn't specify emotion, ask for clarification
- If user says "something happy" -> emotion="joy"
- If user says "sad music" -> emotion="sadness"
- If user says "romantic" -> emotion="love"
- If user says "angry" -> emotion="anger"
- If user says "scary" or "fear" -> emotion="fear"
- If user says "chill" or "relax" -> emotion="neutral" or "sadness" (ask)
- Return ONLY the tool call JSON, no extra text
- If request is ambiguous, return {"intent": "unknown", "clarification": "..."}"""


# Few-shot examples for better intent extraction
FEW_SHOT_EXAMPLES = [
    {
        "user": "Give me something happy for working out",
        "intent": {
            "intent": "recommend_music",
            "emotion": "joy",
            "genre": None,
            "limit": 10,
            "use_history": True
        }
    },
    {
        "user": "Play some sad songs",
        "intent": {
            "intent": "recommend_music",
            "emotion": "sadness",
            "genre": None,
            "limit": 10,
            "use_history": True
        }
    },
    {
        "user": "I want romantic music for dinner",
        "intent": {
            "intent": "recommend_music",
            "emotion": "love",
            "genre": None,
            "limit": 10,
            "use_history": True
        }
    },
    {
        "user": "Recommend angry metal music",
        "intent": {
            "intent": "recommend_music",
            "emotion": "anger",
            "genre": "metal",
            "limit": 10,
            "use_history": True
        }
    },
    {
        "user": "What do you know about my taste?",
        "intent": {
            "intent": "get_preferences",
            "detail_level": "summary"
        }
    },
    {
        "user": "Why did you recommend this song?",
        "intent": {
            "intent": "get_explanation",
            "track_id": "current_track",
            "context_emotion": None
        }
    },
    {
        "user": "I like this track",
        "intent": {
            "intent": "submit_feedback",
            "track_id": "current_track",
            "signal": "like",
            "context_emotion": None
        }
    },
    {
        "user": "Show my profile",
        "intent": {
            "intent": "get_profile",
            "include_history": True
        }
    },
]


def build_prompt(user_message: str, conversation_history: list = None) -> str:
    """Build the full prompt for the LLM."""
    parts = [SYSTEM_PROMPT]
    parts.append("\nExamples:")
    for ex in FEW_SHOT_EXAMPLES:
        parts.append(f"User: {ex['user']}")
        parts.append(f"Assistant: {ex['intent']}")
    if conversation_history:
        parts.append("\nConversation history:")
        for msg in conversation_history[-5:]:  # Last 5 turns
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
    parts.append(f"\nUser: {user_message}")
    parts.append("Assistant:")
    return "\n".join(parts)


__all__ = [
    "IntentType",
    "RecommendMusicIntent",
    "GetPreferencesIntent",
    "GetExplanationIntent",
    "SubmitFeedbackIntent",
    "GetProfileIntent",
    "AnyIntent",
    "SYSTEM_PROMPT",
    "FEW_SHOT_EXAMPLES",
    "build_prompt",
]