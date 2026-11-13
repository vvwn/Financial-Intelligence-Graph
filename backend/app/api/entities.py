"""Entity, company and industry read endpoints (contract 6.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError, ErrorCode
from app.models.entity import CompanyProfile, Entity, EntityAlias, IndustryTaxonomy
from app.models.relationship import Relationship
from app.schemas.api import (
    EntityDetail,
    EntityOut,
    EntityPage,
    Envelope,
    IndustryNode,
    IndustryTree,
    RelationshipOut,
    RelationshipPage,
)
from app.schemas.envelope import ok

router = APIRouter(tags=["entities"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _to_out(entity: Entity) -> EntityOut:
    return EntityOut(
        id=str(entity.id),
        entity_type=entity.entity_type,
        name=entity.canonical_name,
        normalized_name=entity.normalized_name,
        name_sort_key=entity.name_sort_key,
        stock_code=entity.stock_code,
        exchange=entity.exchange,
        industry_code=entity.industry_code,
        status=entity.status,
    )


async def _page(
    session: AsyncSession,
    stmt,
    limit: int,
    cursor: str | None,
) -> tuple[list, str | None]:
    """Cursor pagination on the UUIDv7 primary key (time-ordered, so it is stable)."""
    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "invalid cursor", details={"cursor": cursor}
            ) from exc
        stmt = stmt.where(Entity.id > cursor_uuid)

    rows = list((await session.execute(stmt.limit(limit + 1))).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = str(rows[-1].id)
    return rows, next_cursor


@router.get("/industries", response_model=Envelope[IndustryTree], summary="产业树")
async def list_industries(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    rows = list(
        (
            await session.execute(
                select(IndustryTaxonomy).order_by(IndustryTaxonomy.level, IndustryTaxonomy.code)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await session.execute(
                select(Entity.industry_code, func.count())
                .where(Entity.industry_code.is_not(None), Entity.status == "active")
                .group_by(Entity.industry_code)
            )
        ).all()
    )
    industries = [
        IndustryNode(
            code=row.code,
            name=row.name,
            parent_code=row.parent_code,
            level=row.level,
            entity_count=int(counts.get(row.code, 0)),
        )
        for row in rows
    ]
    return ok(request, IndustryTree(industries=industries).model_dump())


@router.get("/entities", response_model=Envelope[EntityPage], summary="实体列表")
async def list_entities(
    request: Request,
    entity_type: str | None = None,
    q: str | None = None,
    industry_code: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(Entity).where(Entity.status == "active")
    if entity_type:
        stmt = stmt.where(Entity.entity_type == entity_type)
    if industry_code:
        stmt = stmt.where(Entity.industry_code == industry_code)
    if q:
        # Search the sort key so Chinese matches without relying on DB collation.
        from app.core.sortkey import build_sort_key

        stmt = stmt.where(
            Entity.name_sort_key.ilike(f"%{build_sort_key(q)}%")
            | Entity.normalized_name.ilike(f"%{q.lower()}%")
        )
    stmt = stmt.order_by(Entity.id)

    rows, next_cursor = await _page(session, stmt, limit, cursor)
    payload = EntityPage(items=[_to_out(r) for r in rows])
    return ok(request, payload.model_dump(), next_cursor=next_cursor)


@router.get("/entities/{entity_id}", response_model=Envelope[EntityDetail], summary="实体详情")
async def get_entity(
    request: Request, entity_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    entity = (
        await session.execute(select(Entity).where(Entity.id == entity_id))
    ).scalar_one_or_none()
    if entity is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Entity not found", details={"entity_id": str(entity_id)}
        )

    aliases = list(
        (
            await session.execute(
                select(EntityAlias.alias).where(EntityAlias.entity_id == entity_id)
            )
        ).scalars()
    )
    detail = EntityDetail(
        **_to_out(entity).model_dump(),
        aliases=aliases,
        attributes=entity.attributes or {},
    )
    return ok(request, detail.model_dump())


@router.get(
    "/entities/{entity_id}/relations",
    response_model=Envelope[RelationshipPage],
    summary="某实体的关系",
)
async def list_entity_relations(
    request: Request,
    entity_id: uuid.UUID,
    status: str = "verified",
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = (
        select(Relationship)
        .where(
            (Relationship.source_entity_id == entity_id)
            | (Relationship.target_entity_id == entity_id)
        )
        .order_by(Relationship.id)
        .limit(limit)
    )
    if status != "all":
        stmt = stmt.where(Relationship.status == status)

    rows = list((await session.execute(stmt)).scalars().all())
    items = [
        RelationshipOut(
            id=str(r.id),
            source_entity_id=str(r.source_entity_id),
            target_entity_id=str(r.target_entity_id),
            relationship_type=r.relationship_type,
            status=r.status,
            confidence=float(r.confidence),
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            last_verified_at=r.last_verified_at,
            version=r.version,
        )
        for r in rows
    ]
    return ok(request, RelationshipPage(items=items).model_dump())


@router.get("/companies", response_model=Envelope[EntityPage], summary="公司列表")
async def list_companies(
    request: Request,
    industry_code: str | None = None,
    q: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await list_entities(
        request,
        entity_type="listed_company",
        q=q,
        industry_code=industry_code,
        limit=limit,
        cursor=cursor,
        session=session,
    )


@router.get(
    "/companies/{stock_code}", response_model=Envelope[EntityDetail], summary="按股票代码查公司"
)
async def get_company(
    request: Request, stock_code: str, session: AsyncSession = Depends(get_session)
) -> dict:
    entity = (
        await session.execute(
            select(Entity).where(
                Entity.stock_code == stock_code, Entity.entity_type == "listed_company"
            )
        )
    ).scalar_one_or_none()
    if entity is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Company not found", details={"stock_code": stock_code}
        )

    profile = (
        await session.execute(
            select(CompanyProfile).where(CompanyProfile.entity_id == entity.id)
        )
    ).scalar_one_or_none()
    aliases = list(
        (
            await session.execute(
                select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id)
            )
        ).scalars()
    )
    attributes = dict(entity.attributes or {})
    if profile is not None:
        attributes["profile"] = {
            "full_name": profile.full_name,
            "main_business": profile.main_business,
            "chain_position": profile.chain_position,
            "core_products": profile.core_products,
            "revenue_mix": profile.revenue_mix,
        }

    detail = EntityDetail(**_to_out(entity).model_dump(), aliases=aliases, attributes=attributes)
    return ok(request, detail.model_dump())


__all__ = ["router"]
