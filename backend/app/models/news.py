"""Ingestion domain: sources, raw news, normalized events, run bookkeeping."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

SOURCE_KINDS = ("exchange_announcement", "regulator", "gov_stats", "media_rss", "manual")
RUN_STATUSES = ("running", "succeeded", "partial", "failed")
DEAD_LETTER_ERRORS = ("http_429", "http_5xx", "parse_error", "schema_drift", "timeout")
NEWS_VERIFICATION = ("unverified", "partially_verified", "verified", "disputed")


class Source(UUIDPrimaryKeyMixin, Base):
    """Per-source fetch watermark. Without last_fetched_at incremental pulls are impossible."""

    __tablename__ = "source"

    source_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    fetch_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("900")
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"kind IN {SOURCE_KINDS}", name="kind_valid"),
        CheckConstraint("fetch_interval_seconds > 0", name="interval_positive"),
    )


class NewsRaw(UUIDPrimaryKeyMixin, Base):
    """Original payload, kept verbatim. Immutable in spirit: never rewrite content."""

    __tablename__ = "news_raw"

    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_raw.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Uniqueness is per (source, url): the same article republished by five
        # outlets must still be storable five times (that is how repost counting works).
        Index("ux_news_raw_source_url", "source_id", "url", unique=True),
        Index("ix_news_raw_hash", "raw_hash"),
        Index("ix_news_raw_published_at", "published_at"),
    )


class NewsEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "news_event"

    primary_raw_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_raw.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_importance: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'unverified'")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "event_importance >= 1 AND event_importance <= 5", name="importance_range"
        ),
        CheckConstraint(
            f"verification_status IN {NEWS_VERIFICATION}", name="verification_status_valid"
        ),
        Index("ix_news_event_type", "event_type"),
        Index("ix_news_event_published_at", "published_at"),
    )


class NewsRawEvent(Base):
    """Maps N raw reposts to 1 normalized event. Repost counting depends on this."""

    __tablename__ = "news_raw_event"

    raw_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_raw.id"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_event.id"), nullable=False, index=True
    )


class CollectRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "collect_run"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    dup_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (CheckConstraint(f"status IN {RUN_STATUSES}", name="status_valid"),)


class CollectRunSource(Base):
    """Per-source stats. One row per (run, source) — a single rolled-up row hides which source broke."""

    __tablename__ = "collect_run_source"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("collect_run.id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("source.id"), primary_key=True
    )
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    dup_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )


class DeadLetter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dead_letter"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("collect_run.id")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("source.id"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    error_type: Mapped[str] = mapped_column(String(32), nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"error_type IN {DEAD_LETTER_ERRORS}", name="error_type_valid"),
        Index("ix_dead_letter_unresolved", "next_retry_at", postgresql_where=text("resolved_at IS NULL")),
    )


__all__ = [
    "CollectRun",
    "CollectRunSource",
    "DeadLetter",
    "NewsEvent",
    "NewsRaw",
    "NewsRawEvent",
    "Source",
]
