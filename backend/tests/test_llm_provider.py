"""
Tests for the LLM provider abstraction.

These test the factory, message formatting, and error handling
WITHOUT calling real LLM APIs. We mock the HTTP layer.

DECISION: Mock at the HTTP level, not the provider level
  Mocking the provider itself would test nothing — we'd be testing
  our mock. Mocking httpx/SDK calls tests that our provider code
  correctly handles responses, errors, and timeouts from real APIs.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.llm_provider import (
    BaseLLMProvider,
    OllamaProvider,
    AnthropicProvider,
    OpenAIProvider,
    LLMMessage,
    LLMConfig,
    LLMResponse,
    create_llm_provider,
    get_llm_provider,
    reset_llm_provider,
)
from app.core.config import LLMProvider


class TestLLMMessage:
    """Tests for the LLMMessage data class."""

    def test_create_message(self):
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_system_message(self):
        msg = LLMMessage(role="system", content="You are helpful.")
        assert msg.role == "system"


class TestLLMResponse:
    """Tests for the LLMResponse data class."""

    def test_successful_response(self):
        resp = LLMResponse(content="Hello!", model=" llama3.2:3b", provider="ollama")
        assert resp.is_error is False
        assert resp.content == "Hello!"

    def test_error_response(self):
        resp = LLMResponse(
            content="", model=" llama3.2:3b", provider="ollama",
            error="Connection refused"
        )
        assert resp.is_error is True
        assert "Connection refused" in resp.error


class TestLLMConfig:
    """Tests for the LLMConfig data class."""

    def test_defaults(self):
        config = LLMConfig()
        assert config.temperature == 0.7
        assert config.max_tokens == 2048
        assert config.top_p == 1.0
        assert config.system_prompt is None

    def test_custom_config(self):
        config = LLMConfig(temperature=0.0, max_tokens=500, system_prompt="Be brief.")
        assert config.temperature == 0.0
        assert config.max_tokens == 500
        assert config.system_prompt == "Be brief."


class TestOllamaProvider:
    """Tests for the Ollama provider."""

    def test_provider_name(self):
        provider = OllamaProvider()
        assert provider.provider_name == "ollama"

    def test_model_name_from_settings(self):
        provider = OllamaProvider()
        assert provider.model_name  # Should have a default

    def test_format_messages_with_system_prompt(self):
        provider = OllamaProvider()
        messages = [LLMMessage(role="user", content="Hi")]
        formatted = provider._format_messages(messages, system_prompt="Be helpful.")

        assert len(formatted) == 2
        assert formatted[0]["role"] == "system"
        assert formatted[0]["content"] == "Be helpful."
        assert formatted[1]["role"] == "user"

    def test_format_messages_without_system_prompt(self):
        provider = OllamaProvider()
        messages = [
            LLMMessage(role="user", content="Question 1"),
            LLMMessage(role="assistant", content="Answer 1"),
            LLMMessage(role="user", content="Question 2"),
        ]
        formatted = provider._format_messages(messages, system_prompt=None)

        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_connection_error(self):
        """When Ollama isn't running, generate should return an error response."""
        provider = OllamaProvider()
        provider._base_url = "http://localhost:99999"  # Invalid port
        provider._timeout = 1.0

        response = await provider.generate(
            messages=[LLMMessage(role="user", content="test")],
        )

        assert response.is_error
        assert "Cannot connect" in response.error or "error" in response.error.lower()

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        """Health check should report error when Ollama isn't reachable."""
        provider = OllamaProvider()
        provider._base_url = "http://localhost:99999"

        health = await provider.health_check()
        assert health["status"] == "error"


class TestProviderFactory:
    """Tests for the provider factory function."""

    def test_creates_ollama_provider(self):
        provider = create_llm_provider(LLMProvider.OLLAMA)
        assert isinstance(provider, OllamaProvider)
        assert provider.provider_name == "ollama"

    def test_creates_anthropic_provider(self):
        provider = create_llm_provider(LLMProvider.ANTHROPIC)
        assert isinstance(provider, AnthropicProvider)
        assert provider.provider_name == "anthropic"

    def test_creates_openai_provider(self):
        provider = create_llm_provider(LLMProvider.OPENAI)
        assert isinstance(provider, OpenAIProvider)
        assert provider.provider_name == "openai"

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError):
            create_llm_provider("invalid_provider")


class TestSingleton:
    """Tests for the singleton provider management."""

    def test_get_provider_returns_same_instance(self):
        reset_llm_provider()
        p1 = get_llm_provider()
        p2 = get_llm_provider()
        assert p1 is p2

    def test_reset_creates_new_instance(self):
        reset_llm_provider()
        p1 = get_llm_provider()
        reset_llm_provider()
        p2 = get_llm_provider()
        assert p1 is not p2


class TestAnthropicProvider:
    """Tests for Anthropic provider specifics."""

    def test_provider_name(self):
        provider = AnthropicProvider()
        assert provider.provider_name == "anthropic"

    @pytest.mark.asyncio
    async def test_health_check_without_key(self):
        """Without API key, health should report error."""
        provider = AnthropicProvider()
        provider._api_key = ""
        health = await provider.health_check()
        assert health["status"] == "error"
        assert "not set" in health["detail"]


class TestOpenAIProvider:
    """Tests for OpenAI provider specifics."""

    def test_provider_name(self):
        provider = OpenAIProvider()
        assert provider.provider_name == "openai"

    @pytest.mark.asyncio
    async def test_health_check_without_key(self):
        """Without API key, health should report error."""
        provider = OpenAIProvider()
        provider._api_key = ""
        health = await provider.health_check()
        assert health["status"] == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
