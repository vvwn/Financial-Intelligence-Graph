"""Response models for the public API.

These exist so `/openapi.json` is usable: the frontend generates its TypeScript
types from it, and the contract tests can assert the shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Meta(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    generated_at: str
    next_cursor: str | None = None
    truncated: bool | None = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class EntityOut(BaseModel):
    id: str
    entity_type: str
    name: str
    normalized_name: str | None = None
    name_sort_key: str | None = None
    stock_code: str | None = None
    exchange: str | None = None
    industry_code: str | None = None
    status: str = "active"


class EntityDetail(EntityOut):
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EntityPage(BaseModel):
    items: list[EntityOut]


class IndustryNode(BaseModel):
    code: str
    name: str
    parent_code: str | None = None
    level: int
    entity_count: int = 0


class IndustryTree(BaseModel):
    industries: list[IndustryNode]


# ---------------------------------------------------------------------------
# Evidence and relationships
# ---------------------------------------------------------------------------


class EvidenceOut(BaseModel):
    id: str
    source_type: str
    source_name: str
    source_url: str | None = None
    title: str | None = None
    original_excerpt: str
    published_at: datetime | None = None
    collected_at: datetime
    evidence_grade: str
    verification_status: str
    content_hash: str
    origin_key: str
    syndicated_from_id: str | None = None
    supersedes_id: str | None = None
    relation: str | None = None


class RelationshipOut(BaseModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    status: str
    confidence: float
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_verified_at: datetime | None = None
    version: int = 1
    evidence_count: int = 0
    evidence_grade_max: str | None = None


class RelationshipPage(BaseModel):
    items: list[RelationshipOut]


class RelationshipHistoryOut(BaseModel):
    id: str
    from_status: str | None
    to_status: str
    actor: str
    trigger: str
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class GraphNode(BaseModel):
    id: str
    entity_type: str | None = None
    name: str | None = None
    stock_code: str | None = None
    industry_code: str | None = None


class GraphEdge(BaseModel):
    relationship_id: str | None = None
    source: str
    target: str
    relationship_type: str
    status: str
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence_count: int = 0
    contradicting_count: int = 0
    evidence_grade_max: str | None = None
    evidence_missing: bool = True


class GraphView(BaseModel):
    center: str | None = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class PathOut(BaseModel):
    nodes: list[GraphNode | None]
    relationships: list[dict[str, Any]]
    depth: int
    min_confidence: float


class PathView(BaseModel):
    from_: str = Field(alias="from")
    to: str
    paths: list[PathOut]
    max_depth: int

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class EvidenceCreate(BaseModel):
    source_type: str
    source_name: str
    source_url: str | None = None
    title: str | None = None
    original_excerpt: str
    published_at: datetime | None = None
    evidence_grade: str
    origin_key: str
    content_hash: str | None = None
    syndicated_from_id: str | None = None
    supersedes_id: str | None = None


class VerifyRequest(BaseModel):
    approved_by: str
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class DisputeRequest(BaseModel):
    actor: str
    reason: str
    contradicting_evidence_ids: list[str]


class ActorRequest(BaseModel):
    actor: str
    reason: str | None = None


__all__ = [
    "ActorRequest",
    "DisputeRequest",
    "EntityDetail",
    "EntityOut",
    "EntityPage",
    "Envelope",
    "ErrorBody",
    "ErrorEnvelope",
    "EvidenceCreate",
    "EvidenceOut",
    "GraphEdge",
    "GraphNode",
    "GraphView",
    "IndustryNode",
    "IndustryTree",
    "Meta",
    "PathOut",
    "PathView",
    "RelationshipHistoryOut",
    "RelationshipOut",
    "RelationshipPage",
    "VerifyRequest",
]
