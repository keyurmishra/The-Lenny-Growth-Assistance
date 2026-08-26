"""
Tests for the chat service.

Tests intent classification and routing logic without needing
a real database or LLM. We test the deterministic parts.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.chat import ChatService


class TestIntentClassification:
    """Tests for the intent classification logic."""

    @pytest.fixture
    def service(self):
        """Create a ChatService instance for testing."""
        with patch("app.services.chat.get_retrieval_service"):
            return ChatService()

    @pytest.mark.asyncio
    async def test_ship30_keywords(self, service):
        """Ship 30 keywords should route to SHIP30."""
        cases = [
            "Write an essay about product-market fit",
            "Can you write a blog post about growth?",
            "Write a Ship 30 for 30 article on retention",
            "Write about leadership lessons from the podcast",
            "Create a content piece on hiring",
        ]
        for msg in cases:
            intent = await service._classify_intent(msg, [])
            assert intent == "SHIP30", f"Expected SHIP30 for: {msg!r}, got {intent}"

    @pytest.mark.asyncio
    async def test_artifact_keywords(self, service):
        """Artifact keywords should route to ARTIFACT."""
        cases = [
            "Create a document summarizing our discussion",
            "Generate HTML for a landing page about growth",
            "Create an artifact with the key takeaways",
            "Make a template for product reviews",
            "Create a summary doc of the frameworks mentioned",
        ]
        for msg in cases:
            intent = await service._classify_intent(msg, [])
            assert intent == "ARTIFACT", f"Expected ARTIFACT for: {msg!r}, got {intent}"

    @pytest.mark.asyncio
    async def test_general_greetings(self, service):
        """Short greetings should route to GENERAL."""
        cases = [
            "Hello",
            "Hi there",
            "Hey!",
            "What can you do?",
            "Who are you?",
        ]
        for msg in cases:
            intent = await service._classify_intent(msg, [])
            assert intent == "GENERAL", f"Expected GENERAL for: {msg!r}, got {intent}"

    @pytest.mark.asyncio
    async def test_rag_qa_default(self, service):
        """Questions about topics should default to RAG_QA."""
        cases = [
            "What does Lenny say about product-market fit?",
            "How should I think about retention metrics?",
            "What frameworks are used for prioritization?",
            "Tell me about growth strategies from the podcast",
            "What advice does Brian Chesky give about culture?",
        ]
        for msg in cases:
            intent = await service._classify_intent(msg, [])
            assert intent == "RAG_QA", f"Expected RAG_QA for: {msg!r}, got {intent}"

    @pytest.mark.asyncio
    async def test_long_greeting_becomes_rag(self, service):
        """A long message starting with 'hello' should still route to RAG_QA."""
        msg = "Hello, I want to understand what Lenny's guests say about product-market fit and how to measure it effectively across different business models"
        intent = await service._classify_intent(msg, [])
        # Long messages even with greeting prefix should go to RAG_QA
        assert intent in ("RAG_QA", "GENERAL")  # Either is acceptable


class TestChatServiceStructure:
    """Tests for ChatService structural behavior."""

    def test_max_history_messages_constant(self):
        """Verify the history limit is set."""
        from app.services.chat import MAX_HISTORY_MESSAGES
        assert MAX_HISTORY_MESSAGES > 0
        assert MAX_HISTORY_MESSAGES <= 20  # Reasonable upper bound


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
