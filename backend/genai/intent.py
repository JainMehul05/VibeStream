"""Intent extraction from natural language using LLM."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from .schemas import (
    AnyIntent,
    IntentType,
    RecommendMusicIntent,
    GetPreferencesIntent,
    GetExplanationIntent,
    SubmitFeedbackIntent,
    GetProfileIntent,
    build_prompt,
)

logger = logging.getLogger(__name__)


class IntentValidationError(Exception):
    """Raised when intent validation fails."""

    def __init__(self, message: str, raw_output: str = None):
        super().__init__(message)
        self.raw_output = raw_output


class IntentSchema:
    """Schema validator for intent types."""

    SCHEMAS = {
        IntentType.RECOMMEND_MUSIC: RecommendMusicIntent,
        IntentType.GET_PREFERENCES: GetPreferencesIntent,
        IntentType.GET_EXPLANATION: GetExplanationIntent,
        IntentType.SUBMIT_FEEDBACK: SubmitFeedbackIntent,
        IntentType.GET_PROFILE: GetProfileIntent,
    }

    # Dangerous keys that should never be in intent payloads
    DANGEROUS_KEYS = frozenset({
        "__proto__", "constructor", "prototype", "eval", "Function",
        "__defineGetter__", "__defineSetter__", "__lookupGetter__",
        "__lookupSetter__", "__proto__", "hasOwnProperty", "isPrototypeOf",
        "propertyIsEnumerable", "toString", "valueOf", "toLocaleString",
    })

    @classmethod
    def validate(cls, intent_dict: dict) -> AnyIntent:
        """Validate and parse intent dictionary."""
        intent_type = intent_dict.get("intent")
        if not intent_type:
            raise IntentValidationError("Missing 'intent' field")

        # Reject dangerous keys that could lead to prototype pollution or code injection
        dangerous_found = cls.DANGEROUS_KEYS.intersection(intent_dict.keys())
        if dangerous_found:
            raise IntentValidationError(f"Intent contains dangerous keys: {sorted(dangerous_found)}")

        try:
            intent_enum = IntentType(intent_type)
        except ValueError:
            raise IntentValidationError(f"Unknown intent type: {intent_type}")

        if intent_enum == IntentType.UNKNOWN:
            raise IntentValidationError("Intent is unknown/ambiguous")

        schema_cls = cls.SCHEMAS.get(intent_enum)
        if not schema_cls:
            raise IntentValidationError(f"No schema for intent: {intent_enum}")

        try:
            # Only pass allowed fields to the schema
            allowed_fields = set(schema_cls.model_fields.keys()) if hasattr(schema_cls, 'model_fields') else set()
            filtered_dict = {k: v for k, v in intent_dict.items() if k in allowed_fields}
            return schema_cls(**filtered_dict)
        except Exception as e:
            raise IntentValidationError(f"Validation failed: {e}")


class LLMClient:
    """Abstract LLM client. Implement for your provider (OpenAI, Anthropic, etc.)."""

    def __init__(self, model: str = "gpt-4o-mini", timeout: float = 30.0):
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        """Call LLM and return raw text response."""
        raise NotImplementedError

    def complete_json(self, prompt: str) -> dict:
        """Call LLM and parse JSON response."""
        raw = self.complete(prompt)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON: %s", raw[:200])
            raise IntentValidationError(f"Invalid JSON from LLM: {e}", raw_output=raw)


class OpenAIClient(LLMClient):
    """OpenAI API client."""

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini", timeout: float = 30.0):
        super().__init__(model, timeout)
        try:
            import openai
        except ImportError:
            raise ImportError("openai package required: pip install openai")
        self.client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        if not self.client.api_key:
            raise ValueError("OPENAI_API_KEY not set")

    def complete(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )
        return response.choices[0].message.content


class AnthropicClient(LLMClient):
    """Anthropic API client."""

    def __init__(self, api_key: str = None, model: str = "claude-3-haiku-20240307", timeout: float = 30.0):
        super().__init__(model, timeout)
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required: pip install anthropic")
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        if not self.client.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def complete(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0.1,
            system="You are a helpful assistant that outputs only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
            timeout=self.timeout,
        )
        return response.content[0].text


class MockLLMClient(LLMClient):
    """Mock client for testing without API keys."""

    def __init__(self, model: str = "mock", timeout: float = 1.0):
        super().__init__(model, timeout)

    def complete(self, prompt: str) -> str:
        # Extract the actual user message (last "User:" line)
        lines = prompt.strip().split("\n")
        user_msg = ""
        for line in reversed(lines):
            if line.startswith("User: "):
                user_msg = line[6:].strip().lower()
                break
        
        # Simple keyword-based mock for testing
        if "preference" in user_msg or "taste" in user_msg:
            return json.dumps({"intent": "get_preferences", "detail_level": "summary"})
        if "why" in user_msg or "explain" in user_msg:
            return json.dumps({"intent": "get_explanation", "track_id": "current", "context_emotion": None})
        if "like" in user_msg and ("track" in user_msg or "song" in user_msg or "this" in user_msg):
            return json.dumps({"intent": "submit_feedback", "track_id": "current", "signal": "like", "context_emotion": None})
        if "dislike" in user_msg or "don't like" in user_msg:
            return json.dumps({"intent": "submit_feedback", "track_id": "current", "signal": "unlike", "context_emotion": None})
        if "profile" in user_msg or "dashboard" in user_msg:
            return json.dumps({"intent": "get_profile", "include_history": True})
        if "happy" in user_msg or "joy" in user_msg or "workout" in user_msg or "energetic" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "joy", "limit": 10, "use_history": True})
        if "sad" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "sadness", "limit": 10, "use_history": True})
        if "romantic" in user_msg or "love" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "love", "limit": 10, "use_history": True})
        if "angry" in user_msg or "anger" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "anger", "limit": 10, "use_history": True})
        if "scary" in user_msg or "fear" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "fear", "limit": 10, "use_history": True})
        if "chill" in user_msg or "relax" in user_msg or "study" in user_msg:
            return json.dumps({"intent": "recommend_music", "emotion": "neutral", "limit": 10, "use_history": True})
        return json.dumps({"intent": "unknown", "clarification": "Could you clarify what you'd like?"})


class IntentExtractor:
    """Extracts structured intents from natural language."""

    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or MockLLMClient()

    def extract(self, user_message: str, conversation_history: list = None) -> AnyIntent:
        """Extract intent from user message."""
        prompt = build_prompt(user_message, conversation_history)
        logger.debug("Intent extraction prompt: %s", prompt[:500])

        try:
            raw_intent = self.llm.complete_json(prompt)
        except IntentValidationError:
            raise
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            raise IntentValidationError(f"LLM error: {e}")

        logger.debug("Raw intent: %s", raw_intent)

        # Validate and parse
        try:
            intent = IntentSchema.validate(raw_intent)
        except IntentValidationError as e:
            # Try to provide helpful fallback
            if raw_intent.get("intent") == "unknown":
                raise IntentValidationError(
                    raw_intent.get("clarification", "I didn't understand. Could you rephrase?"),
                    raw_output=str(raw_intent)
                )
            raise

        return intent

    def extract_with_fallback(self, user_message: str, conversation_history: list = None) -> tuple[Optional[AnyIntent], Optional[str]]:
        """Extract intent, returning (intent, error_message)."""
        try:
            intent = self.extract(user_message, conversation_history)
            return intent, None
        except IntentValidationError as e:
            return None, str(e)