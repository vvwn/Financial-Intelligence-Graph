"""Relationship domain: the verified graph's source of truth.

Relationships are never deleted. They move between statuses, and every move is
appended to relationship_history with actor, reason, evidence and a full snapshot.
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

RELATIONSHIP_STATUSES = (
    "candidate",
    "pending_review",
    "verified",
    "disputed",
    "rejected",
    "expired",
    "revoked",
)

#: Statuses that occupy the "active triple" slot of the partial unique index.
ACTIVE_TRIPLE_SQL = "('pending_review','verified','disputed')"


class Relationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relationship"

    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entity.id"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'candidate'")
    )
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("0")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(f"status IN {RELATIONSHIP_STATUSES}", name="status_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("source_entity_id <> target_entity_id", name="no_self_loop"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="valid_window",
        ),
        # One active row per triple. Rejected/revoked/expired rows are allowed to
        # coexist so the audit trail survives (a retracted edge is not deleted).
        Index(
            "ux_relationship_active_triple",
            "source_entity_id",
            "relationship_type",
            "target_entity_id",
            unique=True,
            postgresql_where=text(f"status IN {ACTIVE_TRIPLE_SQL}"),
        ),
        Index("ix_relationship_status", "status"),
        Index("ix_relationship_target", "target_entity_id"),
        Index("ix_relationship_type", "relationship_type"),
    )


class RelationshipEvidence(Base):
    """Both sides of a relationship's evidence.

    `disputed` requires the original supporting evidence to survive alongside the
    new contradicting evidence. Without the relation column there is nowhere to
    record which side an item argues for.
    """

    __tablename__ = "relationship_evidence"

    relationship_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("relationship.id"), primary_key=True
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("evidence.id"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(
        String(16), primary_key=True, server_default=text("'supporting'")
    )
    weight: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("1.0")
    )

    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        CheckConstraint(
            "relation IN ('supporting','contradicting')", name="relation_valid"
        ),
    )


class RelationshipHistory(UUIDPrimaryKeyMixin, Base):
    """Append-only. UPDATE/DELETE must be blocked at the DB privilege level."""

    __tablename__ = "relationship_history"

    relationship_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("relationship.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    # What caused the move: claim_promotion / evidence_threshold / manual_approval /
    # new_evidence / rule / migration. Required for disputed (new evidence must be traceable).
    trigger: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'manual'")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"to_status IN {RELATIONSHIP_STATUSES}", name="to_status_valid"),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN {RELATIONSHIP_STATUSES}",
            name="from_status_valid",
        ),
        CheckConstraint(
            "trigger IN ('claim_promotion','evidence_threshold','manual_approval',"
            "'new_evidence','rule','migration','manual')",
            name="trigger_valid",
        ),
        # Entering `disputed` must cite at least one contradicting evidence item.
        # cardinality(), not array_length(): array_length('{}') is NULL, and a NULL
        # CHECK expression counts as satisfied — the guard would silently pass.
        CheckConstraint(
            "to_status <> 'disputed' OR cardinality(evidence_ids) >= 1",
            name="disputed_requires_evidence",
        ),
        Index("ix_relationship_history_rel", "relationship_id", "created_at"),
    )


__all__ = ["ACTIVE_TRIPLE_SQL", "RELATIONSHIP_STATUSES", "Relationship", "RelationshipEvidence", "RelationshipHistory"]
