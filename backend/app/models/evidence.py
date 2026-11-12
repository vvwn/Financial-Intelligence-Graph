"""Evidence domain. Evidence is immutable: corrections are new rows via supersedes_id."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

EVIDENCE_SOURCE_TYPES = (
    "announcement",
    "annual_report",
    "exchange_disclosure",
    "gov_doc",
    "company_release",
    "media",
    "industry_association",
    "research_report",
    "social_media",
    "ai_inference",
)

EVIDENCE_VERIFICATION = ("unverified", "verified", "disputed", "rejected")


class Evidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evidence"

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    original_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unverified'")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("evidence.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"source_type IN {EVIDENCE_SOURCE_TYPES}", name="source_type_valid"
        ),
        CheckConstraint("evidence_grade IN ('A','B','C','D')", name="grade_valid"),
        CheckConstraint(
            f"verification_status IN {EVIDENCE_VERIFICATION}", name="verification_valid"
        ),
        Index("ix_evidence_content_hash", "content_hash"),
        Index("ix_evidence_grade", "evidence_grade"),
    )


__all__ = ["EVIDENCE_SOURCE_TYPES", "Evidence"]
