"""Relationship read endpoints and the status lifecycle (contract 6.7).

Lifecycle endpoints are thin: all rules live in services/relationship_service.py,
which in turn delegates to validation/state_guard.py. No rule is duplicated here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.models.evidence import Evidence
from app.models.relationship import Relationship, RelationshipEvidence, RelationshipHistory
from app.schemas.api import (
    ActorRequest,
    DisputeRequest,
    Envelope,
    EvidenceOut,
    RelationshipHistoryOut,
    RelationshipOut,
    RelationshipPage,
    VerifyRequest,
)
from app.schemas.envelope import ok
from app.services import relationship_service as svc

router = APIRouter(tags=["relationships"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _out(rel: Relationship) -> RelationshipOut:
    return RelationshipOut(
        id=str(rel.id),
        source_entity_id=str(rel.source_entity_id),
        target_entity_id=str(rel.target_entity_id),
        relationship_type=rel.relationship_type,
        status=rel.status,
        confidence=float(rel.confidence),
        valid_from=rel.valid_from,
        valid_to=rel.valid_to,
        last_verified_at=rel.last_verified_at,
        version=rel.version,
    )


@router.get("/relationships", response_model=Envelope[RelationshipPage], summary="关系列表")
async def list_relationships(
    request: Request,
    status: str | None = None,
    relationship_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(Relationship).order_by(Relationship.id).limit(limit)
    if status:
        stmt = stmt.where(Relationship.status == status)
    if relationship_type:
        stmt = stmt.where(Relationship.relationship_type == relationship_type)
    if entity_id:
        stmt = stmt.where(
            (Relationship.source_entity_id == entity_id)
            | (Relationship.target_entity_id == entity_id)
        )

    rows = list((await session.execute(stmt)).scalars().all())
    return ok(request, RelationshipPage(items=[_out(r) for r in rows]).model_dump())


@router.get("/relationships/{relationship_id}", response_model=Envelope[RelationshipOut])
async def get_relationship(
    request: Request, relationship_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    rel = (
        await session.execute(select(Relationship).where(Relationship.id == relationship_id))
    ).scalar_one_or_none()
    if rel is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Relationship not found",
            details={"relationship_id": str(relationship_id)},
        )

    count = (
        await session.execute(
            select(func.count())
            .select_from(RelationshipEvidence)
            .where(
                RelationshipEvidence.relationship_id == relationship_id,
                RelationshipEvidence.relation == "supporting",
            )
        )
    ).scalar_one()

    payload = _out(rel)
    payload.evidence_count = int(count)
    return ok(request, payload.model_dump())


@router.get(
    "/relationships/{relationship_id}/evidence",
    response_model=Envelope[list[EvidenceOut]],
    summary="关系的全部证据（含正反）",
)
async def list_relationship_evidence(
    request: Request, relationship_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    stmt = (
        select(Evidence, RelationshipEvidence.relation)
        .join(RelationshipEvidence, RelationshipEvidence.evidence_id == Evidence.id)
        .where(RelationshipEvidence.relationship_id == relationship_id)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        EvidenceOut(
            id=str(ev.id),
            source_type=ev.source_type,
            source_name=ev.source_name,
            source_url=ev.source_url,
            title=ev.title,
            original_excerpt=ev.original_excerpt,
            published_at=ev.published_at,
            collected_at=ev.collected_at,
            evidence_grade=ev.evidence_grade,
            verification_status=ev.verification_status,
            content_hash=ev.content_hash,
            origin_key=ev.origin_key,
            syndicated_from_id=str(ev.syndicated_from_id) if ev.syndicated_from_id else None,
            supersedes_id=str(ev.supersedes_id) if ev.supersedes_id else None,
            relation=relation,
        )
        for ev, relation in rows
    ]
    return ok(request, [i.model_dump() for i in items])


@router.get(
    "/history/relationships/{relationship_id}",
    response_model=Envelope[list[RelationshipHistoryOut]],
    summary="关系历史",
)
async def get_history(
    request: Request, relationship_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    rows = list(
        (
            await session.execute(
                select(RelationshipHistory)
                .where(RelationshipHistory.relationship_id == relationship_id)
                .order_by(RelationshipHistory.created_at)
            )
        )
        .scalars()
        .all()
    )
    items = [
        RelationshipHistoryOut(
            id=str(h.id),
            from_status=h.from_status,
            to_status=h.to_status,
            actor=h.actor,
            trigger=h.trigger,
            reason=h.reason,
            evidence_ids=[str(e) for e in (h.evidence_ids or [])],
            created_at=h.created_at,
        )
        for h in rows
    ]
    return ok(request, [i.model_dump() for i in items])


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post(
    "/relationships/{relationship_id}/submit-review",
    response_model=Envelope[RelationshipOut],
    summary="candidate -> pending_review（证据达阈值）",
)
async def submit_review(
    request: Request,
    relationship_id: uuid.UUID,
    body: ActorRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rel = await svc.submit_for_review(
        session, relationship_id, actor=body.actor, reason=body.reason
    )
    await session.commit()
    return ok(request, _out(rel).model_dump())


@router.post(
    "/relationships/{relationship_id}/verify",
    response_model=Envelope[RelationshipOut],
    summary="pending_review -> verified（需显式批准）",
)
async def verify(
    request: Request,
    relationship_id: uuid.UUID,
    body: VerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rel = await svc.verify(
        session,
        relationship_id,
        approved_by=body.approved_by,
        reason=body.reason,
        evidence_ids=[uuid.UUID(e) for e in body.evidence_ids],
    )
    await session.commit()
    return ok(request, _out(rel).model_dump())


@router.post(
    "/relationships/{relationship_id}/dispute",
    response_model=Envelope[RelationshipOut],
    summary="verified -> disputed（需反向证据）",
)
async def dispute(
    request: Request,
    relationship_id: uuid.UUID,
    body: DisputeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rel = await svc.dispute(
        session,
        relationship_id,
        actor=body.actor,
        reason=body.reason,
        contradicting_evidence_ids=[uuid.UUID(e) for e in body.contradicting_evidence_ids],
    )
    await session.commit()
    return ok(request, _out(rel).model_dump())


@router.post(
    "/relationships/{relationship_id}/reject",
    response_model=Envelope[RelationshipOut],
    summary="-> rejected（终态）",
)
async def reject(
    request: Request,
    relationship_id: uuid.UUID,
    body: ActorRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rel = await svc.transition(
        session, relationship_id, "rejected", actor=body.actor, reason=body.reason
    )
    await session.commit()
    return ok(request, _out(rel).model_dump())


@router.post(
    "/relationships/{relationship_id}/revoke",
    response_model=Envelope[RelationshipOut],
    summary="-> revoked（终态，行不删除）",
)
async def revoke(
    request: Request,
    relationship_id: uuid.UUID,
    body: ActorRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rel = await svc.transition(
        session, relationship_id, "revoked", actor=body.actor, reason=body.reason
    )
    await session.commit()
    return ok(request, _out(rel).model_dump())


__all__ = ["router"]
