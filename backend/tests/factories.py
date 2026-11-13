"""Test data factories. Kept out of conftest so tests can import them directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.ids import uuid7
from app.core.sortkey import build_sort_key, sort_key_version
from app.models.claim import Claim, ClaimEvidence, ClaimRelationship
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.relationship import Relationship, RelationshipEvidence
from sqlalchemy.ext.asyncio import AsyncSession


async def make_entity(session: AsyncSession, name: str, stock_code: str | None = None) -> Entity:
    entity = Entity(
        id=uuid7(),
        entity_type="listed_company",
        canonical_name=name,
        normalized_name=name.strip().lower(),
        name_sort_key=build_sort_key(name),
        name_sort_key_version=sort_key_version(),
        stock_code=stock_code,
        industry_code="AI-COMPUTE-GPU",
    )
    session.add(entity)
    await session.flush()
    return entity


def make_evidence(
    grade: str,
    *,
    origin_key: str | None = None,
    content_hash: str | None = None,
    source_name: str = "测试公告",
) -> Evidence:
    """`origin_key` models the ORIGINAL report; reposts share one origin_key."""
    return Evidence(
        id=uuid7(),
        source_type="announcement",
        source_name=source_name,
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        title="测试证据",
        original_excerpt="本公司向客户供应高速光模块。",
        collected_at=datetime.now(UTC),
        evidence_grade=grade,
        content_hash=content_hash or uuid.uuid4().hex,
        origin_key=origin_key or uuid.uuid4().hex,
    )


async def add_evidence(session: AsyncSession, evidence: Evidence) -> Evidence:
    session.add(evidence)
    await session.flush()
    return evidence


async def make_claim(
    session: AsyncSession,
    subject: Entity,
    obj: Entity,
    claim_type: str = "fact_reported",
    confidence: float | None = None,
    predicate: str = "supplies_to",
) -> Claim:
    # Inference must not look certain; the DB enforces this, so pick a legal default.
    if confidence is None:
        confidence = {"inferred": 0.5, "hypothesis": 0.3}.get(claim_type, 0.8)
    claim = Claim(
        id=uuid7(),
        subject_entity_id=subject.id,
        predicate=predicate,
        object_entity_id=obj.id,
        claim_type=claim_type,
        confidence=confidence,
        status="supported" if claim_type == "fact_reported" else "candidate",
    )
    session.add(claim)
    await session.flush()
    return claim


async def make_relationship(
    session: AsyncSession,
    subject: Entity,
    obj: Entity,
    status: str = "candidate",
    relationship_type: str = "supplies_to",
) -> Relationship:
    rel = Relationship(
        id=uuid7(),
        source_entity_id=subject.id,
        target_entity_id=obj.id,
        relationship_type=relationship_type,
        status=status,
        confidence=0.8,
    )
    session.add(rel)
    await session.flush()
    return rel


async def link_claim(session: AsyncSession, claim: Claim, rel: Relationship) -> None:
    session.add(ClaimRelationship(claim_id=claim.id, relationship_id=rel.id))
    await session.flush()


async def link_evidence(
    session: AsyncSession,
    rel: Relationship,
    ev: Evidence,
    claim: Claim | None = None,
    *,
    relation: str = "supporting",
) -> None:
    session.add(
        RelationshipEvidence(relationship_id=rel.id, evidence_id=ev.id, relation=relation)
    )
    if claim is not None and relation == "supporting":
        session.add(ClaimEvidence(claim_id=claim.id, evidence_id=ev.id, relation="supporting"))
    await session.flush()


__all__ = [
    "add_evidence",
    "link_claim",
    "link_evidence",
    "make_claim",
    "make_entity",
    "make_evidence",
    "make_relationship",
]
