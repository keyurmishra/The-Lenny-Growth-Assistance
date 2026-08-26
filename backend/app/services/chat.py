"""
Chat service — the core orchestration layer.

This is where retrieval, LLM generation, and session management come
together. The chat service:

1. Loads conversation history for the session (context continuity)
2. Classifies user intent (Q&A, Ship 30, artifact, general)
3. Routes to the appropriate skill
4. Returns a structured response with sources

DECISION: Service layer over putting logic in route handlers
  Route handlers should be 5-10 lines: parse input, call service, return
  output. The chat service contains the actual business logic, making it
  testable without HTTP and reusable across different entry points
  (REST API, WebSocket, CLI, etc.).

DECISION: Conversation history in the prompt over stateful agents
  We reload the last N messages from the DB and inject them into the
  prompt as conversation history. This is simpler and more debuggable
  than maintaining an in-memory agent state. Trade-off: we pay token
  cost for re-sending history, but for sessions with <50 messages
  this is negligible.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.llm_provider import (
    get_llm_provider,
    LLMMessage,
    LLMConfig,
    LLMResponse,
)
from app.models.database import Session, Message
from app.services.retrieval import get_retrieval_service, RetrievedChunk
from app.agents.prompts import (
    RAG_SYSTEM_PROMPT,
    RAG_CONTEXT_TEMPLATE,
    ARTIFACT_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from app.skills.ship30 import get_ship30_skill

logger = get_logger(__name__)

# Max messages to include as conversation history in the prompt
MAX_HISTORY_MESSAGES = 10
# DECISION: 10 messages of history
#   Enough for multi-turn follow-ups without blowing the context window.
#   10 messages ≈ 2-4k tokens of history. With 5 retrieved chunks
#   (≈ 2.5k tokens) and the system prompt (≈ 500 tokens), we stay
#   well under even a 4k context window ( llama3.2:3b 7B).
#   For cloud models with 100k+ context, this is ultra-conservative.


class ChatService:
    """Orchestrates the full chat pipeline."""

    def __init__(self):
        self.retrieval = get_retrieval_service()

    async def process_message(
        self,
        session_id: uuid.UUID,
        user_content: str,
        db: AsyncSession,
    ) -> dict:
        """
        Process a user message and generate an AI response.

        Flow:
          1. Load conversation history
          2. Classify intent
          3. Route to skill (RAG Q&A, Ship 30, artifact, general)
          4. Return response dict with content, sources, and artifact

        Args:
            session_id: The chat session ID.
            user_content: The user's message text.
            db: Async database session.

        Returns:
            Dict with keys: content, sources, artifact_type, artifact_content,
            model_used, latency_ms
        """
        # Step 1: Load conversation history
        history = await self._load_history(session_id, db)

        # Step 2: Classify intent
        intent = await self._classify_intent(user_content, history)
        logger.info("intent_classified", intent=intent, session_id=str(session_id))

        # Step 3: Route to the appropriate skill
        if intent == "SHIP30":
            return await self._handle_ship30(user_content, history, db)
        elif intent == "ARTIFACT":
            return await self._handle_artifact(user_content, history, db)
        elif intent == "GENERAL":
            return await self._handle_general(user_content, history)
        else:
            # Default: RAG Q&A
            return await self._handle_rag_qa(user_content, history, db)

    async def _load_history(
        self, session_id: uuid.UUID, db: AsyncSession
    ) -> list[LLMMessage]:
        """
        Load the recent conversation history for a session.

        DECISION: Load from DB over in-memory cache
          The DB is the source of truth. Loading from DB means:
          - History survives server restarts
          - Multiple server instances see the same history
          - No cache invalidation bugs
          Trade-off: one extra DB query per chat message (~2ms).
        """
        query = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
        result = await db.execute(query)
        messages = result.scalars().all()

        # Reverse to chronological order (we fetched desc for LIMIT efficiency)
        messages = list(reversed(messages))

        return [
            LLMMessage(role=msg.role, content=msg.content)
            for msg in messages
        ]

    async def _classify_intent(
        self, user_content: str, history: list[LLMMessage]
    ) -> str:
        """
        Classify the user's intent to route to the right skill.

        DECISION: Keyword-first classification with LLM fallback
          Simple keyword matching handles 80% of cases instantly (0ms)
          without burning LLM tokens. The LLM fallback handles ambiguous
          cases. This is a common pattern in production agent systems —
          don't call the LLM when a regex will do.

        TRADE-OFF: Keyword matching can misclassify. "Write me an essay"
          is clear, but "Can you put together something about growth?"
          is ambiguous. The LLM handles these edge cases.
        """
        content_lower = user_content.lower()

        # Fast keyword matching for obvious intents
        ship30_keywords = [
            "ship 30", "ship30", "write an essay", "write a blog",
            "write a post", "write an article", "write about",
            "content piece", "write a piece",
        ]
        artifact_keywords = [
            "create a document", "create an artifact", "generate html",
            "make a template", "build a summary", "create a summary doc",
            "render as html", "make an html", "create markdown",
        ]

        for kw in ship30_keywords:
            if kw in content_lower:
                return "SHIP30"

        for kw in artifact_keywords:
            if kw in content_lower:
                return "ARTIFACT"

        # Check for greetings / meta questions
        general_patterns = [
            "hello", "hi ", "hey ", "what can you do",
            "who are you", "help me", "what are you",
        ]
        if any(content_lower.strip().startswith(p) for p in general_patterns):
            if len(user_content.strip()) < 50:  # Short greeting
                return "GENERAL"

        # Default: RAG Q&A (most common intent)
        # DECISION: Default to RAG_QA over using LLM classification
        #   For a podcast assistant, 90%+ of messages are questions.
        #   Defaulting to RAG_QA and only using the LLM classifier for
        #   ambiguous cases saves tokens and latency.
        return "RAG_QA"

    async def _rewrite_query(
        self,
        user_content: str,
        history: list[LLMMessage],
    ) -> str:
        """
        Rewrite the user's query into a self-contained search query.

        DECISION: Query rewriting for context-aware follow-ups
          When a user asks "Can you give me an example?", embedding that
          literal text into a vector search retrieves near-random chunks.
          We use the LLM to rewrite it to "Give me an example of product-market
          fit from Lenny's Podcast" — embedding THAT gives useful results.

          We only rewrite when history exists (first message is always clear).
          Falls back to the original query on any error.

        TRADE-OFF: One extra LLM call per RAG query (~100-300ms).
          We use a minimal config (max_tokens=80) to keep this fast.
          For local Ollama this adds ~100ms; negligible for cloud providers.
        """
        if not history:
            return user_content

        # Only rewrite if the message looks like it relies on context
        ambiguous_signals = [
            "it", "that", "this", "those", "they", "him", "her",
            "the same", "another", "more", "else", "also", "example",
            "what about", "how about", "and", "but",
        ]
        content_lower = user_content.lower().strip()
        needs_rewrite = (
            len(user_content.split()) < 12  # Short follow-ups
            or any(content_lower.startswith(signal) for signal in ambiguous_signals)
            or any(f" {signal} " in content_lower for signal in ["it", "that", "this"])
        )

        if not needs_rewrite:
            return user_content

        try:
            provider = get_llm_provider()

            # Build a brief summary of recent conversation for context
            recent = history[-4:]  # Last 2 turns max
            history_summary = "\n".join(
                f"{msg.role.upper()}: {msg.content[:200]}"
                for msg in recent
            )

            rewrite_system = (
                "You are a search query rewriter. Given a conversation history and a "
                "follow-up question, rewrite the follow-up as a fully self-contained, "
                "specific search query for a podcast transcript database. "
                "Return ONLY the rewritten query — no explanation, no quotes."
            )
            rewrite_user = (
                f"Conversation so far:\n{history_summary}\n\n"
                f"Follow-up question: {user_content}\n\n"
                "Rewrite as a self-contained search query:"
            )

            config = LLMConfig(
                system_prompt=rewrite_system,
                temperature=0.0,
                max_tokens=80,
            )
            response = await provider.generate(
                [LLMMessage(role="user", content=rewrite_user)],
                config,
            )

            if not response.is_error and response.content.strip():
                rewritten = response.content.strip().strip('"').strip("'")
                logger.info(
                    "query_rewritten",
                    original=user_content[:80],
                    rewritten=rewritten[:80],
                )
                return rewritten

        except Exception as e:
            logger.warning("query_rewrite_failed", error=str(e))

        return user_content  # Fallback: use original

    async def _handle_rag_qa(
        self,
        user_content: str,
        history: list[LLMMessage],
        db: AsyncSession,
    ) -> dict:
        """
        Handle a RAG Q&A query — retrieve context, generate grounded answer.

        This is the primary skill. Flow:
          1. Rewrite query for context-awareness (if follow-up)
          2. Retrieve relevant transcript chunks
          3. Build the prompt with context + history
          4. Generate a response grounded in the sources
          5. Return response with source citations
        """
        provider = get_llm_provider()

        # Step 1: Rewrite query to be context-aware
        search_query = await self._rewrite_query(user_content, history)

        # Step 2: Retrieve relevant chunks using the (possibly rewritten) query
        chunks, context_string = await self.retrieval.retrieve_with_context(
            search_query, db, top_k=settings.retrieval_top_k,
        )

        # Step 2: Build the system prompt with context
        if context_string:
            full_system = RAG_SYSTEM_PROMPT + "\n\n" + RAG_CONTEXT_TEMPLATE.format(
                context=context_string
            )
        else:
            # No relevant chunks found
            full_system = RAG_SYSTEM_PROMPT + (
                "\n\n## Note\nNo relevant transcript excerpts were found for this "
                "query. Inform the user that the available Lenny's Podcast "
                "transcripts don't contain information about this topic."
            )

        # Step 3: Build message list with history
        messages = list(history)  # Previous messages for context
        messages.append(LLMMessage(role="user", content=user_content))

        # Step 4: Generate response
        config = LLMConfig(
            system_prompt=full_system,
            temperature=0.3,
            # DECISION: Low temperature (0.3) for RAG Q&A
            #   We want factual, grounded answers. High temperature
            #   introduces creative variation that risks hallucination.
            #   0.3 allows some natural phrasing variation without
            #   making things up.
            max_tokens=2048,
        )

        llm_response = await provider.generate(messages, config)

        if llm_response.is_error:
            logger.error("rag_qa_generation_failed", error=llm_response.error)
            return {
                "content": f"I encountered an error generating a response: {llm_response.error}",
                "sources": [],
                "artifact_type": None,
                "artifact_content": None,
                "model_used": provider.model_name,
                "latency_ms": llm_response.latency_ms,
            }

        # Build source references
        sources = [chunk.to_source_dict() for chunk in chunks]

        logger.info(
            "rag_qa_complete",
            chunks_used=len(chunks),
            response_length=len(llm_response.content),
            model=provider.model_name,
            latency_ms=round(llm_response.latency_ms),
        )

        return {
            "content": llm_response.content,
            "sources": sources,
            "artifact_type": None,
            "artifact_content": None,
            "model_used": llm_response.model,
            "latency_ms": llm_response.latency_ms,
        }

    async def _handle_ship30(
        self,
        user_content: str,
        history: list[LLMMessage],
        db: AsyncSession,
    ) -> dict:
        """
        Handle a Ship 30 for 30 essay request.

        DECISION: Delegate to Ship30Skill
          The skill class encodes all Ship 30 writing rules as structured
          constants, builds the prompt, and validates the output. This
          separation means the chat service only routes — it doesn't encode
          writing principles inline.

        Flow:
          1. Retrieve broad transcript context (8 chunks)
          2. Let Ship30Skill build the prompts
          3. Generate the essay
          4. Validate output and log quality metrics
          5. Return as a Markdown artifact
        """
        provider = get_llm_provider()
        skill = get_ship30_skill()

        # DECISION: 8 chunks for essays vs 5 for Q&A
        #   Essays need more source material to reach ~1,250 words
        #   with grounded claims. 8 chunks ≈ 4k tokens of context.
        chunks, context_string = await self.retrieval.retrieve_with_context(
            user_content, db, top_k=8,
        )

        if not context_string:
            return {
                "content": "I couldn't find enough relevant transcript content to write a Ship 30 essay on this topic. Try a topic related to product management, growth, metrics, hiring, or leadership.",
                "sources": [],
                "artifact_type": None,
                "artifact_content": None,
                "model_used": provider.model_name,
                "latency_ms": 0,
            }

        # Build prompts via the skill (structured rules, not inline strings)
        system_prompt = skill.build_system_prompt()
        user_prompt = skill.build_user_prompt(
            topic=user_content,
            context_string=context_string,
        )

        messages = list(history)
        messages.append(LLMMessage(role="user", content=user_prompt))

        config = LLMConfig(
            system_prompt=system_prompt,
            temperature=0.7,
            # DECISION: Higher temperature (0.7) for creative writing
            #   Essays need varied phrasing, engaging hooks, and narrative
            #   flow. 0.7 balances creativity with groundedness.
            max_tokens=4096,
        )

        llm_response = await provider.generate(messages, config)

        if llm_response.is_error:
            return {
                "content": f"Error generating essay: {llm_response.error}",
                "sources": [],
                "artifact_type": None,
                "artifact_content": None,
                "model_used": provider.model_name,
                "latency_ms": llm_response.latency_ms,
            }

        # Validate essay quality and log metrics
        validation = skill.validate(llm_response.content)
        logger.info(
            "ship30_generated",
            word_count=validation.word_count,
            heading_count=validation.heading_count,
            bold_count=validation.bold_count,
            is_valid=validation.is_valid,
            issues=validation.issues,
            model=llm_response.model,
            latency_ms=round(llm_response.latency_ms),
        )

        sources = [chunk.to_source_dict() for chunk in chunks]

        return {
            "content": "Here's your Ship 30 for 30 essay. I've opened it in the artifact viewer.",
            "sources": sources,
            "artifact_type": "markdown",
            "artifact_content": llm_response.content,
            "model_used": llm_response.model,
            "latency_ms": llm_response.latency_ms,
        }

    async def _handle_artifact(
        self,
        user_content: str,
        history: list[LLMMessage],
        db: AsyncSession,
    ) -> dict:
        """
        Handle an artifact generation request (Markdown or HTML).

        Generates a document or HTML snippet based on the conversation
        context and user's request.
        """
        provider = get_llm_provider()

        # Retrieve context if the artifact relates to transcript content
        chunks, context_string = await self.retrieval.retrieve_with_context(
            user_content, db, top_k=5,
        )

        full_system = ARTIFACT_SYSTEM_PROMPT
        if context_string:
            full_system += "\n\n" + RAG_CONTEXT_TEMPLATE.format(context=context_string)

        messages = list(history)
        messages.append(LLMMessage(role="user", content=user_content))

        # Detect if user wants HTML or Markdown
        content_lower = user_content.lower()
        is_html = any(kw in content_lower for kw in ["html", "webpage", "web page", "landing page"])
        artifact_type = "html" if is_html else "markdown"

        if is_html:
            messages[-1] = LLMMessage(
                role="user",
                content=user_content + "\n\nGenerate this as a complete HTML document with inline CSS styling.",
            )
        else:
            messages[-1] = LLMMessage(
                role="user",
                content=user_content + "\n\nGenerate this as a clean Markdown document.",
            )

        config = LLMConfig(
            system_prompt=full_system,
            temperature=0.5,
            max_tokens=4096,
        )

        llm_response = await provider.generate(messages, config)

        if llm_response.is_error:
            return {
                "content": f"Error generating artifact: {llm_response.error}",
                "sources": [],
                "artifact_type": None,
                "artifact_content": None,
                "model_used": provider.model_name,
                "latency_ms": llm_response.latency_ms,
            }

        sources = [chunk.to_source_dict() for chunk in chunks]

        return {
            "content": f"Here's your {artifact_type.upper()} artifact. I've opened it in the artifact viewer.",
            "sources": sources,
            "artifact_type": artifact_type,
            "artifact_content": llm_response.content,
            "model_used": llm_response.model,
            "latency_ms": llm_response.latency_ms,
        }

    async def _handle_general(
        self,
        user_content: str,
        history: list[LLMMessage],
    ) -> dict:
        """
        Handle general/meta questions (greetings, "what can you do?", etc.).

        DECISION: Don't waste retrieval on greetings
          "Hello" doesn't need a vector search. Return a canned-ish
          response that explains the assistant's capabilities. The LLM
          adds natural phrasing variation so it doesn't feel robotic.
        """
        provider = get_llm_provider()

        system = """You are the Lenny Growth Assistant. You help product managers and growth practitioners by answering questions grounded in Lenny's Podcast transcripts.

When greeting the user or explaining what you can do, mention these capabilities:
1. Answer product management and growth questions using insights from Lenny's Podcast transcripts
2. Write Ship 30 for 30-style essays on topics covered in the podcasts
3. Generate Markdown or HTML artifacts (summaries, documents, templates)

Keep your response warm, concise, and helpful. Suggest a question they could ask to get started."""

        messages = list(history)
        messages.append(LLMMessage(role="user", content=user_content))

        config = LLMConfig(
            system_prompt=system,
            temperature=0.7,
            max_tokens=500,
        )

        llm_response = await provider.generate(messages, config)

        if llm_response.is_error:
            # Fallback for when even the LLM is down
            return {
                "content": (
                    "👋 Hi! I'm the Lenny Growth Assistant. I can help you with:\n\n"
                    "• **Ask questions** about product management and growth, grounded in Lenny's Podcast transcripts\n"
                    "• **Write Ship 30 for 30 essays** on topics from the podcasts\n"
                    "• **Generate artifacts** (Markdown docs, HTML pages) based on our conversation\n\n"
                    "Try asking: \"What does Lenny say about product-market fit?\""
                ),
                "sources": [],
                "artifact_type": None,
                "artifact_content": None,
                "model_used": "fallback",
                "latency_ms": 0,
            }

        return {
            "content": llm_response.content,
            "sources": [],
            "artifact_type": None,
            "artifact_content": None,
            "model_used": llm_response.model,
            "latency_ms": llm_response.latency_ms,
        }


# Module singleton
_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """Get or create the singleton ChatService."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
