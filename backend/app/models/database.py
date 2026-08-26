"""
SQLAlchemy ORM models.

These mirror the tables created by init_db.sql. We define them here so
the application can use ORM queries instead of raw SQL.

DECISION: ORM models over raw SQL
  Raw SQL is faster to write initially but becomes a maintenance burden.
  ORM models give us:
  - Type safety: IDE knows session.id is a UUID, not a mystery string
  - Relationship loading: session.messages loads related messages automatically
  - Query building: filter(), join(), etc. compose without string concatenation
  - Migration support: Alembic can diff models vs DB and generate migrations

TRADE-OFF: ORM adds ~15% overhead per query vs raw SQL. Negligible for a
  chat app doing single-digit queries per request.
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base


class Session(Base):
    """A chat session (conversation thread)."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict
        # Column named "metadata" in DB; Python attribute is "metadata_"
        # because "metadata" conflicts with SQLAlchemy's Base.metadata
    )

    # Relationship: session.messages loads all messages in this session
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        # DECISION: order_by on relationship
        #   Messages are always displayed chronologically. Sorting at the ORM
        #   level means we never forget to add ORDER BY in a query.
    )

    def __repr__(self) -> str:
        return f"<Session {self.id} title={self.title!r}>"


class Message(Base):
    """A single message within a chat session."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("role IN ('user', 'assistant', 'system')"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[dict] = mapped_column(JSONB, default=list)
    artifact_type: Mapped[str | None] = mapped_column(
        String(20),
        CheckConstraint("artifact_type IN ('markdown', 'html')"),
        nullable=True,
    )
    artifact_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationship back to session
    session: Mapped["Session"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message {self.id} role={self.role} session={self.session_id}>"


class TranscriptChunk(Base):
    """A chunk of text from a Lenny's Podcast transcript, with its embedding."""

    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transcript_name: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(
        Vector(settings.embedding_dimension), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("transcript_name", "chunk_index", name="uq_transcript_chunk"),
        Index("idx_chunks_transcript_index", "transcript_name", "chunk_index"),
    )

    def __repr__(self) -> str:
        return f"<TranscriptChunk {self.transcript_name}[{self.chunk_index}]>"
