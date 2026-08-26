"""
API route handlers.

DECISION: Thin routes, fat services
  Route handlers do three things: parse input, call a service, return output.
  No business logic lives here. This means:
  - Services are testable without HTTP (just call the function)
  - Routes are trivially readable (each is 5-10 lines)
  - Swapping from REST to GraphQL or WebSockets means rewriting routes,
    not reimplementing business logic.

TRADE-OFF: One extra layer of indirection. Worth it for testability.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.database import Session, Message
from app.models.schemas import (
    ArtifactData,
    ChatMessageCreate,
    ChatResponse,
    ChatMessageResponse,
    ErrorResponse,
    SessionCreate,
    SessionResponse,
    SessionListResponse,
)

logger = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Session Endpoints
# =============================================================================

@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
    tags=["sessions"],
    summary="Create a new chat session",
    responses={500: {"model": ErrorResponse}},
)
async def create_session(
    body: SessionCreate = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a new conversation thread.
    
    Each session maintains independent context — messages in one session
    don't affect another.
    """
    session = Session(
        title=body.title if body else None,
        metadata_=body.metadata if body else {},
    )
    db.add(session)
    await db.flush()
    # flush() sends the INSERT but doesn't commit — commit happens in get_db()

    logger.info("session_created", session_id=str(session.id))

    return SessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        metadata=session.metadata_,
        message_count=0,
    )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    tags=["sessions"],
    summary="List all chat sessions",
)
async def list_sessions(
    limit: int = Query(20, ge=1, le=100, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
):
    """
    List sessions ordered by most recently updated.
    
    DECISION: Offset pagination over cursor pagination
      Offset is simpler to implement and sufficient for a chat app where
      users have tens of sessions, not millions. Cursor pagination matters
      when you have high-volume, high-concurrency reads (social media feeds).
    """
    # Count total sessions
    count_q = select(func.count()).select_from(Session)
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch sessions with message counts
    query = (
        select(Session)
        .order_by(Session.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    sessions = result.scalars().all()

    # Get message counts for each session
    session_responses = []
    for s in sessions:
        msg_count_q = (
            select(func.count())
            .select_from(Message)
            .where(Message.session_id == s.id)
        )
        msg_count = (await db.execute(msg_count_q)).scalar() or 0
        session_responses.append(
            SessionResponse(
                id=s.id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                metadata=s.metadata_,
                message_count=msg_count,
            )
        )

    return SessionListResponse(sessions=session_responses, total=total)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    tags=["sessions"],
    summary="Get a specific session",
    responses={404: {"model": ErrorResponse}},
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get session details by ID."""
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="session_not_found",
                detail=f"No session with ID {session_id}",
                status_code=404,
            ).model_dump(),
        )

    msg_count_q = (
        select(func.count())
        .select_from(Message)
        .where(Message.session_id == session.id)
    )
    msg_count = (await db.execute(msg_count_q)).scalar() or 0

    return SessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        metadata=session.metadata_,
        message_count=msg_count,
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    tags=["sessions"],
    summary="Delete a session and all its messages",
    responses={404: {"model": ErrorResponse}},
)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a session.
    CASCADE on the FK means all messages are deleted automatically.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    logger.info("session_deleted", session_id=str(session_id))


# =============================================================================
# Message / Chat Endpoints
# =============================================================================

@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
    tags=["chat"],
    summary="Get all messages in a session",
    responses={404: {"model": ErrorResponse}},
)
async def get_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the full conversation history for a session.
    
    Messages are returned in chronological order.
    """
    # Verify session exists
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    query = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    result = await db.execute(query)
    messages = result.scalars().all()

    return [
        ChatMessageResponse(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            sources=m.sources or [],
            artifact=ArtifactData(
                type=m.artifact_type,
                content=m.artifact_content,
                title=None,
            ) if m.artifact_type and m.artifact_content else None,
            model_used=m.model_used,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post(
    "/sessions/{session_id}/chat",
    response_model=ChatResponse,
    tags=["chat"],
    summary="Send a message and get an AI response",
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def chat(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a user message and receive an AI-generated response.

    Flow:
      1. Validate session exists
      2. Store the user message
      3. Route to the appropriate skill (RAG Q&A, Ship 30, artifact, general)
      4. Generate AI response with citations and optional artifact
      5. Store the assistant message
      6. Return the response with sources

    DECISION: Store user message BEFORE generation, not after
      If the LLM call fails, the user's message is still persisted.
      They can see what they asked and retry. If we stored after generation,
      a timeout would lose both the question and the answer.
    """
    from app.services.chat import get_chat_service
    from app.models.schemas import ArtifactData

    # Verify session exists
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Store user message FIRST
    user_message = Message(
        session_id=session_id,
        role="user",
        content=body.content,
    )
    db.add(user_message)
    await db.flush()

    # Process through the agent pipeline
    chat_service = get_chat_service()
    result = await chat_service.process_message(session_id, body.content, db)

    # Store assistant message
    assistant_message = Message(
        session_id=session_id,
        role="assistant",
        content=result["content"],
        sources=result.get("sources", []),
        artifact_type=result.get("artifact_type"),
        artifact_content=result.get("artifact_content"),
        model_used=result.get("model_used"),
    )
    db.add(assistant_message)
    await db.flush()

    # Update session title from first user message if not set
    if not session.title:
        session.title = body.content[:100]

    logger.info(
        "chat_response_generated",
        session_id=str(session_id),
        model=result.get("model_used", "unknown"),
        user_message_length=len(body.content),
        response_length=len(result["content"]),
        sources_count=len(result.get("sources", [])),
        has_artifact=result.get("artifact_type") is not None,
        latency_ms=round(result.get("latency_ms", 0)),
    )

    # Build artifact data if present
    artifact = None
    if result.get("artifact_type") and result.get("artifact_content"):
        artifact = ArtifactData(
            type=result["artifact_type"],
            content=result["artifact_content"],
            title=None,
        )

    return ChatResponse(
        message=ChatMessageResponse(
            id=assistant_message.id,
            session_id=session_id,
            role="assistant",
            content=result["content"],
            sources=result.get("sources", []),
            artifact=artifact,
            model_used=assistant_message.model_used,
            created_at=assistant_message.created_at,
        ),
        session_id=session_id,
        model=result.get("model_used", "unknown"),
    )


# =============================================================================
# Knowledge Base Endpoints
# =============================================================================

@router.get(
    "/knowledge/stats",
    tags=["knowledge"],
    summary="Knowledge base statistics",
)
async def knowledge_stats(db: AsyncSession = Depends(get_db)):
    """
    Return stats about the ingested knowledge base.
    Useful for the evaluator to verify ingestion was successful.
    """
    from sqlalchemy import text

    chunk_count = (await db.execute(text("SELECT COUNT(*) FROM transcript_chunks"))).scalar() or 0
    transcript_count = (await db.execute(
        text("SELECT COUNT(DISTINCT transcript_name) FROM transcript_chunks")
    )).scalar() or 0

    # Get a sample of transcript names
    sample = (await db.execute(
        text("SELECT DISTINCT transcript_name FROM transcript_chunks ORDER BY transcript_name LIMIT 10")
    )).fetchall()

    return {
        "total_chunks": chunk_count,
        "total_transcripts": transcript_count,
        "sample_transcripts": [row[0] for row in sample],
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }


@router.get(
    "/knowledge/search",
    tags=["knowledge"],
    summary="Search the transcript knowledge base",
)
async def search_knowledge(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    top_k: int = Query(5, ge=1, le=20, description="Number of results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search the knowledge base directly (bypasses the LLM).
    
    DECISION: Expose retrieval as a standalone endpoint
      This lets the evaluator test retrieval quality independently from
      LLM generation quality. If answers are bad, they can check:
      is the retrieval finding the right chunks? Or is the LLM misusing
      good chunks? This separation is critical for debugging RAG systems.
    """
    from app.services.retrieval import get_retrieval_service

    retrieval = get_retrieval_service()
    chunks = await retrieval.retrieve(q, db, top_k=top_k)

    return {
        "query": q,
        "results": [
            {
                "transcript": c.transcript_name,
                "chunk_index": c.chunk_index,
                "similarity": round(c.similarity_score, 4),
                "content": c.content,
                "metadata": c.metadata,
            }
            for c in chunks
        ],
        "total_results": len(chunks),
    }
