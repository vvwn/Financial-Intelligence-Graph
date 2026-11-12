"""Impact propagation results and operational bookkeeping tables."""

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
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

IMPACT_DIRECTIONS = ("positive", "negative", "uncertain")
IMPACT_PATH_STATUSES = ("valid", "invalidated", "stale")
ISSUE_SEVERITIES = ("low", "medium", "high", "critical")
ISSUE_STATUSES = ("open", "acknowledged", "resolved", "wontfix")
RUN_STATUSES = ("running", "succeeded", "partial", "failed")


class ImpactPath(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "impact_path"

    event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_event.id"), nullable=False
    )
    path_nodes: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), nullable=False
    )
    path_relationships: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), nullable=False
    )
    propagation_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    impact_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    impact_horizon: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    min_evidence_grade: Mapped[str | None] = mapped_column(String(1))
    uncertain_factors: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Needed so that revoking a relationship can mark affected paths invalidated.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'valid'")
    )
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"impact_direction IN {IMPACT_DIRECTIONS}", name="direction_valid"),
        CheckConstraint(f"status IN {IMPACT_PATH_STATUSES}", name="status_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("propagation_depth >= 1 AND propagation_depth <= 5", name="depth_range"),
        CheckConstraint(
            "impact_horizon IS NULL OR impact_horizon IN ('short','medium','long')",
            name="horizon_valid",
        ),
        Index("ix_impact_path_event", "event_id"),
        Index("ix_impact_path_status", "status"),
    )


class QualityIssue(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "quality_issue"

    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    target_table: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    detected_by: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'open'")
    )
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"severity IN {ISSUE_SEVERITIES}", name="severity_valid"),
        CheckConstraint(f"status IN {ISSUE_STATUSES}", name="status_valid"),
        Index("ix_quality_issue_status", "status", "severity"),
        Index("ix_quality_issue_target", "target_table", "target_id"),
    )


class AnalysisRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_run"

    news_event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("news_event.id"), nullable=False
    )
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text)
    output_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded','parse_error','failed')", name="status_valid"
        ),
        Index("ix_analysis_run_event", "news_event_id"),
    )


class GraphProjectionRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "graph_projection_run"

    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    nodes_upserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    edges_upserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    edges_removed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("mode IN ('full','incremental')", name="mode_valid"),
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status_valid"),
    )


class IdempotencyKey(UUIDPrimaryKeyMixin, Base):
    """Backs the Idempotency-Key header. Without this the header is decoration."""

    __tablename__ = "idempotency_key"

    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ux_idempotency_scope_key", "scope", "key", unique=True),
        Index("ix_idempotency_expires", "expires_at"),
    )


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)


__all__ = [
    "AnalysisRun",
    "AppSetting",
    "GraphProjectionRun",
    "IdempotencyKey",
    "ImpactPath",
    "QualityIssue",
]
