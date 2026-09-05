"""GenAI Assistant package for VibeStream.

Provides natural language interface to the recommendation system via
structured intent extraction and validated tool calling.
"""

from .intent import IntentExtractor, IntentSchema, IntentValidationError
from .tools import ToolRegistry, ToolCall, ToolResult, ToolError
from .assistant import GenAIAssistant, AssistantResponse
from .schemas import (
    RecommendMusicIntent,
    GetPreferencesIntent,
    GetExplanationIntent,
    SubmitFeedbackIntent,
    GetProfileIntent,
    IntentType,
)

__all__ = [
    "IntentExtractor",
    "IntentSchema",
    "IntentValidationError",
    "ToolRegistry",
    "ToolCall",
    "ToolResult",
    "ToolError",
    "GenAIAssistant",
    "AssistantResponse",
    "RecommendMusicIntent",
    "GetPreferencesIntent",
    "GetExplanationIntent",
    "SubmitFeedbackIntent",
    "GetProfileIntent",
    "IntentType",
]