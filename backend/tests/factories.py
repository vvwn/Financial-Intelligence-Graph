"""Test data factories. Kept out of conftest so tests can import them directly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.ids import uuid7
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
        stock_code=stock_code,
        industry_code="AI-COMPUTE-GPU",
    )
    session.add(entity)
    await session.flush()
    return entity


async def make_evidence(
    session: AsyncSession,
    grade: str,
    content_hash: str | None = None,
) -> Evidence:
    ev = Evidence(
        id=uuid7(),
        source_type="announcement",
        source_name="测试公告",
        source_url="https://example.com/a",
        title="测试证据",
        original_excerpt="本公司向客户供应高速光模块。",
        collected_at=datetime.now(UTC),
        evidence_grade=grade,
        content_hash=content_hash or uuid.uuid4().hex,
    )
    session.add(ev)
    await session.flush()
    return ev


async def make_claim(
    session: AsyncSession,
    subject: Entity,
    obj: Entity,
    claim_type: str = "fact_reported",
    confidence: float | None = None,
) -> Claim:
    # Inference must not look certain; the DB enforces this, so pick a legal default.
    if confidence is None:
        confidence = {"inferred": 0.5, "hypothesis": 0.3}.get(claim_type, 0.8)
    claim = Claim(
        id=uuid7(),
        subject_entity_id=subject.id,
        predicate="supplies_to",
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
    session: AsyncSession, rel: Relationship, ev: Evidence, claim: Claim | None = None
) -> None:
    session.add(RelationshipEvidence(relationship_id=rel.id, evidence_id=ev.id))
    if claim is not None:
        session.add(ClaimEvidence(claim_id=claim.id, evidence_id=ev.id, relation="supporting"))
    await session.flush()


__all__ = [
    "link_claim",
    "link_evidence",
    "make_claim",
    "make_entity",
    "make_evidence",
    "make_relationship",
]
