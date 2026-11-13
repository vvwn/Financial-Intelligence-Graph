"""Claim domain: what the model asserts, plus the mentions it saw.

Claim is NOT a relationship. A claim must pass state_guard to become one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.schemas.enums import RelationshipType

CLAIM_TYPES = ("fact_reported", "inferred", "hypothesis", "disputed")
CLAIM_STATUSES = ("candidate", "supported", "rejected", "disputed")
MENTION_TYPES = ("company", "product", "technology", "industry", "person", "other")

#: predicate reuses the relationship-type enum (contract decision D-14).
PREDICATES = tuple(t.value for t in RelationshipType)


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim"

    subject_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id")
    )
    predicate: Mapped[str] = mapped_column(String(48), nullable=False)
    object_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id")
    )
    # Object may be a literal ("HBM3", "3nm") that never becomes an entity.
    object_text: Mapped[str | None] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'candidate'")
    )
    source_news_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_event.id")
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    unknowns: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    needs_human_review: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(f"claim_type IN {CLAIM_TYPES}", name="claim_type_valid"),
        CheckConstraint(f"status IN {CLAIM_STATUSES}", name="status_valid"),
        CheckConstraint(f"predicate IN {PREDICATES}", name="predicate_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        # Inference must not look certain, and hypothesis even less so.
        CheckConstraint(
            "claim_type <> 'hypothesis' OR confidence <= 0.3", name="hypothesis_conf_cap"
        ),
        CheckConstraint(
            "claim_type <> 'inferred' OR confidence <= 0.6", name="inferred_conf_cap"
        ),
        # A claim without subject or object is not a claim.
        CheckConstraint(
            "subject_entity_id IS NOT NULL AND (object_entity_id IS NOT NULL OR object_text IS NOT NULL)",
            name="subject_object_present",
        ),
        Index("ix_claim_status", "status"),
        Index("ix_claim_subject", "subject_entity_id"),
        Index("ix_claim_event", "source_news_event_id"),
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("claim.id"), primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(String(16), primary_key=True)

    __table_args__ = (
        CheckConstraint("relation IN ('supporting','contradicting')", name="relation_valid"),
    )


class EntityMention(UUIDPrimaryKeyMixin, Base):
    """Where an entity was mentioned. Needed to re-check a link after entity merges."""

    __tablename__ = "entity_mention"

    news_event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_event.id"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id")
    )
    surface_form: Mapped[str] = mapped_column(Text, nullable=False)
    mention_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'other'")
    )
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    link_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"mention_type IN {MENTION_TYPES}", name="mention_type_valid"),
        CheckConstraint(
            "link_confidence IS NULL OR (link_confidence >= 0 AND link_confidence <= 1)",
            name="link_conf_range",
        ),
        Index("ix_entity_mention_event", "news_event_id"),
        Index("ix_entity_mention_entity", "entity_id"),
    )


class ClaimRelationship(Base):
    """Which claim produced which relationship. Replaces an unfk'd uuid[] column."""

    __tablename__ = "claim_relationship"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("claim.id"), primary_key=True
    )
    relationship_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("relationship.id"), primary_key=True, index=True
    )


__all__ = ["Claim", "ClaimEvidence", "ClaimRelationship", "EntityMention"]
