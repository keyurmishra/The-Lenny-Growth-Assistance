"""
LLM Provider abstraction layer.

This module provides a unified interface for interacting with different
LLM providers (Ollama, Anthropic, OpenAI). The rest of the application
calls `llm_provider.generate()` and doesn't know or care which model
is running behind it.

DESIGN PATTERN: Strategy Pattern
  Each provider (Ollama, Anthropic, OpenAI) implements the same interface
  (BaseLLMProvider). A factory function reads the config and returns the
  right provider. The agent layer calls generate() — it never imports
  openai or anthropic directly.

  Why this matters:
  - Switching providers is a config change, not a code change
  - Testing with a mock provider requires no conditional logic
  - Adding a new provider (e.g., Google Gemini) means writing one class,
    not touching 15 files

DECISION: Abstract base class over Protocol (structural typing)
  ABC enforces that subclasses implement required methods at class
  definition time. A Protocol would only catch missing methods at call
  time. For 3 providers that must all work, fail-fast is better.

DECISION: Async-only interface
  FastAPI is async. Making the LLM interface async means no blocking
  the event loop. Even Ollama (which runs locally) benefits — while
  waiting for Ollama to generate tokens, the server can handle other
  requests (health checks, session listing, etc.).
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
import structlog

from app.core.config import settings, LLMProvider

logger = structlog.get_logger(__name__)


# =============================================================================
# Data classes for request/response
# =============================================================================

@dataclass
class LLMMessage:
    """
    A message in the conversation.
    
    DECISION: Custom dataclass over provider-specific message types
      anthropic.types.Message and openai.ChatCompletionMessage have
      different shapes. Our own LLMMessage is the common language.
      The provider translates to/from its native format internally.
    """
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """
    Response from an LLM provider.
    
    Captures not just the text but operational metadata (model used,
    latency, token counts). This metadata is critical for:
    - Debugging: "why was this response slow?" → check latency_ms
    - Cost tracking: token counts → estimated cost
    - Logging: which model actually generated this response
    """
    content: str
    model: str
    provider: str
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = ""
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class LLMConfig:
    """
    Configuration for a single LLM generation call.
    
    DECISION: Per-call config over global config
      Different skills need different settings. RAG Q&A needs low
      temperature (factual). Ship 30 essay writing needs higher
      temperature (creative). Per-call config allows this without
      changing global settings.
    
    DECISION: Conservative defaults
      temperature=0.7: balanced between creative and factual.
      max_tokens=2048: enough for a detailed answer, not enough to
        blow up the context window or cost budget.
      top_p=1.0: no nucleus sampling restriction by default.
    """
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    system_prompt: str | None = None
    # The system prompt is per-call because different skills use
    # different system prompts. The RAG skill says "only answer from
    # the provided context." The Ship 30 skill says "write in this
    # specific format."


# =============================================================================
# Base provider interface
# =============================================================================

class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Every provider must implement:
    - generate(): send messages, get a response
    - health_check(): verify the provider is reachable
    - model_name: which model is active
    - provider_name: "ollama", "anthropic", or "openai"
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """
        Check if the provider is reachable and the model is available.
        
        Returns:
            Dict with "status" ("healthy" or "error") and "detail" keys.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The active model name (e.g., ' llama3.2:3b', 'claude-sonnet-4-20250514')."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The provider identifier (e.g., 'ollama', 'anthropic')."""
        ...


# =============================================================================
# Ollama Provider
# =============================================================================

class OllamaProvider(BaseLLMProvider):
    """
    Ollama provider — local LLM inference.
    
    DECISION: Use OpenAI-compatible API (/v1/chat/completions) over
    Ollama's native API (/api/chat)
      Ollama intentionally mirrors the OpenAI chat completions API.
      Using it means our Ollama and OpenAI providers share 90% of
      their code. If we later add Azure OpenAI or any other
      OpenAI-compatible service (Together, Groq, etc.), it works
      with minimal changes.
    
    TRADE-OFF: Ollama's native /api/chat has a few extra features
      (model loading status, context window info) that we don't get
      through the OpenAI-compatible endpoint. We don't need them.
    """

    def __init__(self):
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        # Timeout is generous because local models on CPU can be slow.
        # 120s handles a worst-case 7B model on a laptop CPU.
        self._timeout = 120.0

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        config = config or LLMConfig()

        # Build the request payload (OpenAI-compatible format)
        payload = {
            "model": self._model,
            "messages": self._format_messages(messages, config.system_prompt),
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "top_p": config.top_p,
            "stream": False,
            # DECISION: Non-streaming for now
            #   Streaming (SSE) requires frontend support. For Phase 3,
            #   we get the full response and return it. Streaming is a
            #   Phase 7 enhancement if time permits.
        }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                )

            elapsed_ms = (time.time() - start) * 1000

            if response.status_code != 200:
                error_text = response.text[:500]
                logger.error(
                    "ollama_generation_failed",
                    status=response.status_code,
                    error=error_text,
                    model=self._model,
                )
                return LLMResponse(
                    content="",
                    model=self._model,
                    provider="ollama",
                    latency_ms=elapsed_ms,
                    error=f"Ollama returned status {response.status_code}: {error_text}",
                )

            data = response.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})

            usage = data.get("usage", {})

            result = LLMResponse(
                content=message.get("content", ""),
                model=data.get("model", self._model),
                provider="ollama",
                latency_ms=elapsed_ms,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason", ""),
            )

            logger.info(
                "ollama_generation_complete",
                model=self._model,
                latency_ms=round(elapsed_ms),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            return result

        except httpx.ConnectError:
            elapsed_ms = (time.time() - start) * 1000
            error = f"Cannot connect to Ollama at {self._base_url}. Is it running?"
            logger.error("ollama_connection_failed", url=self._base_url)
            return LLMResponse(
                content="", model=self._model, provider="ollama",
                latency_ms=elapsed_ms, error=error,
            )
        except httpx.TimeoutException:
            elapsed_ms = (time.time() - start) * 1000
            error = f"Ollama timed out after {self._timeout}s. The model may be too large for your hardware."
            logger.error("ollama_timeout", model=self._model, timeout=self._timeout)
            return LLMResponse(
                content="", model=self._model, provider="ollama",
                latency_ms=elapsed_ms, error=error,
            )
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            logger.error("ollama_unexpected_error", error=str(e), exc_info=True)
            return LLMResponse(
                content="", model=self._model, provider="ollama",
                latency_ms=elapsed_ms, error=f"Unexpected error: {str(e)}",
            )

    async def health_check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                has_model = any(self._model in m for m in models)
                return {
                    "status": "healthy" if has_model else "model_missing",
                    "detail": f"Available models: {models}" if not has_model
                              else f"Model {self._model} available",
                    "available_models": models,
                }
            return {"status": "error", "detail": f"Status {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    def _format_messages(
        self, messages: list[LLMMessage], system_prompt: str | None
    ) -> list[dict]:
        """Convert LLMMessages to OpenAI-format dicts, prepending system prompt."""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for msg in messages:
            formatted.append({"role": msg.role, "content": msg.content})
        return formatted


# =============================================================================
# Anthropic Provider
# =============================================================================

class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude provider — cloud LLM inference.
    
    DECISION: Official anthropic SDK over raw HTTP
      The SDK handles auth, retries, rate limits, and response parsing.
      Raw HTTP would require reimplementing all of that.
    
    DECISION: System prompt via the `system` parameter (not as a message)
      Anthropic's API has a dedicated `system` parameter, separate from
      the messages array. This is different from OpenAI where system is
      a message with role="system". Using the dedicated parameter gives
      Anthropic's models better instruction-following.
    """

    def __init__(self):
        self._model = settings.anthropic_model
        self._api_key = settings.anthropic_api_key
        self._client = None

    def _get_client(self):
        """Lazy-init the Anthropic client."""
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic. "
                    "Set it in your .env file."
                )
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def generate(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        config = config or LLMConfig()

        start = time.time()
        try:
            client = self._get_client()

            # Anthropic separates system prompt from messages
            api_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
                if msg.role != "system"
            ]

            kwargs = {
                "model": self._model,
                "messages": api_messages,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "top_p": config.top_p,
            }

            # Add system prompt if provided
            if config.system_prompt:
                kwargs["system"] = config.system_prompt

            response = await client.messages.create(**kwargs)

            elapsed_ms = (time.time() - start) * 1000

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            result = LLMResponse(
                content=content,
                model=response.model,
                provider="anthropic",
                latency_ms=elapsed_ms,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason or "",
            )

            logger.info(
                "anthropic_generation_complete",
                model=self._model,
                latency_ms=round(elapsed_ms),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            return result

        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            error_msg = str(e)
            logger.error("anthropic_generation_failed", error=error_msg, exc_info=True)
            return LLMResponse(
                content="", model=self._model, provider="anthropic",
                latency_ms=elapsed_ms, error=error_msg,
            )

    async def health_check(self) -> dict:
        if not self._api_key:
            return {"status": "error", "detail": "ANTHROPIC_API_KEY not set"}
        return {"status": "healthy", "detail": f"API key configured, model: {self._model}"}


# =============================================================================
# OpenAI Provider
# =============================================================================

class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI provider — cloud LLM inference.
    
    DECISION: Official openai SDK
      Same reasoning as Anthropic — handles auth, retries, rate limits.
    
    NOTE: This provider also works with any OpenAI-compatible API
      (Together AI, Groq, Anyscale, etc.) by changing the base_url
      in the client initialization.
    """

    def __init__(self):
        self._model = settings.openai_model
        self._api_key = settings.openai_api_key
        self._client = None

    def _get_client(self):
        """Lazy-init the OpenAI client."""
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "OPENAI_API_KEY is required when LLM_PROVIDER=openai. "
                    "Set it in your .env file."
                )
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        config = config or LLMConfig()

        start = time.time()
        try:
            client = self._get_client()

            api_messages = []
            if config.system_prompt:
                api_messages.append({"role": "system", "content": config.system_prompt})
            for msg in messages:
                api_messages.append({"role": msg.role, "content": msg.content})

            response = await client.chat.completions.create(
                model=self._model,
                messages=api_messages,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                top_p=config.top_p,
            )

            elapsed_ms = (time.time() - start) * 1000
            choice = response.choices[0]

            result = LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                provider="openai",
                latency_ms=elapsed_ms,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                finish_reason=choice.finish_reason or "",
            )

            logger.info(
                "openai_generation_complete",
                model=self._model,
                latency_ms=round(elapsed_ms),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            return result

        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            error_msg = str(e)
            logger.error("openai_generation_failed", error=error_msg, exc_info=True)
            return LLMResponse(
                content="", model=self._model, provider="openai",
                latency_ms=elapsed_ms, error=error_msg,
            )

    async def health_check(self) -> dict:
        if not self._api_key:
            return {"status": "error", "detail": "OPENAI_API_KEY not set"}
        return {"status": "healthy", "detail": f"API key configured, model: {self._model}"}


# =============================================================================
# Provider Factory
# =============================================================================

def create_llm_provider(provider: LLMProvider | None = None) -> BaseLLMProvider:
    """
    Factory function — returns the right provider based on config.
    
    DECISION: Factory function over dependency injection container
      DI containers (like python-inject or dependency-injector) add a
      framework for something a 10-line function handles perfectly.
      The mapping is simple: enum value → class instance.
    
    DECISION: Default to settings.llm_provider
      Most callers don't pass a provider — they want whatever's configured.
      Passing an explicit provider is for testing or runtime switching.
    """
    provider = provider or settings.llm_provider

    providers = {
        LLMProvider.OLLAMA: OllamaProvider,
        LLMProvider.ANTHROPIC: AnthropicProvider,
        LLMProvider.OPENAI: OpenAIProvider,
    }

    provider_class = providers.get(provider)
    if not provider_class:
        raise ValueError(f"Unknown LLM provider: {provider}")

    instance = provider_class()
    logger.info(
        "llm_provider_created",
        provider=instance.provider_name,
        model=instance.model_name,
    )
    return instance


# =============================================================================
# Singleton provider instance
# =============================================================================

_active_provider: BaseLLMProvider | None = None


def get_llm_provider() -> BaseLLMProvider:
    """
    Get the active LLM provider (singleton).

    DECISION: Singleton over per-request instantiation
      Creating a new provider per request would re-initialize the HTTP
      client, re-validate the API key, and re-log the creation event
      on every single chat message. Wasteful.

    Hot-swapping is supported via switch_llm_provider() which replaces the
    singleton without restarting the process.
    """
    global _active_provider
    if _active_provider is None:
        _active_provider = create_llm_provider()
    return _active_provider


def reset_llm_provider():
    """
    Reset the singleton provider.
    Used for testing or runtime provider switching.
    """
    global _active_provider
    _active_provider = None


def switch_llm_provider(provider: str, model: str | None = None) -> BaseLLMProvider:
    """
    Hot-swap the active LLM provider at runtime — no restart required.

    Args:
        provider: Provider name — "ollama", "anthropic", or "openai".
        model: Optional model name override (e.g. "llama3.1:8b").
               If omitted, uses the model from settings.

    Returns:
        The newly activated provider instance.

    DECISION: Mutate settings in-place before re-creating provider
      pydantic-settings Settings is not frozen, so we can assign to
      llm_provider at runtime. The provider class reads the model name
      from settings in __init__, so overriding settings.xxx_model before
      instantiation achieves the desired model switch cleanly.
    """
    global _active_provider

    try:
        provider_enum = LLMProvider(provider)
    except ValueError:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Valid options: {[p.value for p in LLMProvider]}"
        )

    # Override the model in settings if a specific model was requested
    if model:
        if provider_enum == LLMProvider.OLLAMA:
            settings.ollama_model = model
        elif provider_enum == LLMProvider.ANTHROPIC:
            settings.anthropic_model = model
        elif provider_enum == LLMProvider.OPENAI:
            settings.openai_model = model

    # Update the active provider setting
    settings.llm_provider = provider_enum

    # Destroy the current singleton and create a fresh one
    _active_provider = create_llm_provider(provider_enum)

    logger.info(
        "llm_provider_switched",
        provider=_active_provider.provider_name,
        model=_active_provider.model_name,
    )
    return _active_provider


def list_available_providers() -> list[dict]:
    """
    Return a list of all configured providers with their models and
    whether they are ready to use (API key set, Ollama reachable etc.).
    """
    return [
        {
            "id": "ollama",
            "label": "Ollama (Local)",
            "model": settings.ollama_model,
            "requires_key": False,
            "configured": True,  # Always try — health check will tell truth
        },
        {
            "id": "anthropic",
            "label": "Anthropic Claude",
            "model": settings.anthropic_model,
            "requires_key": True,
            "configured": bool(settings.anthropic_api_key),
        },
        {
            "id": "openai",
            "label": "OpenAI",
            "model": settings.openai_model,
            "requires_key": True,
            "configured": bool(settings.openai_api_key),
        },
    ]
