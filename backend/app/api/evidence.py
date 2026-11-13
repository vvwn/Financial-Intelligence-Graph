"""Evidence write/read endpoints (contract 6.5).

Evidence is immutable (I-5): there is no PUT/PATCH/DELETE. Corrections are new
rows carrying `supersedes_id`, and the database enforces the same-origin and
time-ordering rules.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.models.evidence import Evidence
from app.schemas.api import Envelope, EvidenceCreate, EvidenceOut
from app.schemas.envelope import ok

router = APIRouter(tags=["evidence"])

_WHITESPACE = re.compile(r"\s+")


def compute_content_hash(excerpt: str, source_url: str | None) -> str:
    """Same text from the same URL yields the same hash; whitespace is normalised."""
    normalised = _WHITESPACE.sub("", excerpt or "")
    return hashlib.sha256(f"{normalised}|{source_url or ''}".encode()).hexdigest()


def _out(ev: Evidence, relation: str | None = None) -> dict:
    return EvidenceOut(
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
    ).model_dump()


@router.post("/evidence", response_model=Envelope[EvidenceOut], summary="写入证据")
async def create_evidence(
    request: Request, body: EvidenceCreate, session: AsyncSession = Depends(get_session)
) -> dict:
    if not body.original_excerpt.strip():
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "original_excerpt must not be empty", details={}
        )

    ev = Evidence(
        source_type=body.source_type,
        source_name=body.source_name,
        source_url=body.source_url,
        title=body.title,
        original_excerpt=body.original_excerpt,
        published_at=body.published_at,
        collected_at=datetime.now(UTC),
        evidence_grade=body.evidence_grade,
        content_hash=body.content_hash or compute_content_hash(body.original_excerpt, body.source_url),
        origin_key=body.origin_key,
        syndicated_from_id=uuid.UUID(body.syndicated_from_id) if body.syndicated_from_id else None,
        supersedes_id=uuid.UUID(body.supersedes_id) if body.supersedes_id else None,
    )
    session.add(ev)
    try:
        await session.commit()
    except Exception as exc:  # DB-level guards (I-5 linkage rules) surface here
        await session.rollback()
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Evidence rejected by the immutability rules",
            details={"reason": str(exc).split("\n")[0][:200]},
        ) from exc

    return ok(request, _out(ev))


@router.get("/evidence/{evidence_id}", response_model=Envelope[EvidenceOut], summary="单条证据")
async def get_evidence(
    request: Request, evidence_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    ev = (
        await session.execute(select(Evidence).where(Evidence.id == evidence_id))
    ).scalar_one_or_none()
    if ev is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Evidence not found", details={"evidence_id": str(evidence_id)}
        )
    return ok(request, _out(ev))


__all__ = ["compute_content_hash", "router"]
