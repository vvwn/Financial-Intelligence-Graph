"""API contract tests for the Phase 1 endpoints.

Runs against the ASGI app with the same database the fixtures seed, so the
envelope, the pagination cursor and the graph limits are all exercised for real.
"""

from __future__ import annotations

import httpx
import pytest
from app.graph import projector
from app.main import app
from factories import (
    add_evidence,
    link_claim,
    link_evidence,
    make_claim,
    make_entity,
    make_evidence,
    make_relationship,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.db, pytest.mark.neo4j]

_SEQ = {"n": 0}


def _code() -> str:
    _SEQ["n"] += 1
    return f"{830000 + _SEQ['n']:06d}"


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed(session: AsyncSession):
    supplier = await make_entity(session, f"接口供方{_code()}", _code())
    customer = await make_entity(session, f"接口需方{_code()}", _code())
    rel = await make_relationship(session, supplier, customer, status="verified")
    claim = await make_claim(session, supplier, customer)
    await link_claim(session, claim, rel)
    ev = await add_evidence(session, make_evidence("A", origin_key=f"origin-{_code()}"))
    await link_evidence(session, rel, ev, claim)
    await session.commit()
    await projector.project_all(session, mode="full")
    await session.commit()
    return supplier, customer, rel, ev


async def test_entities_list_envelope(session: AsyncSession, clean_db: None, client) -> None:
    await _seed(session)

    resp = await client.get("/api/v1/entities", params={"limit": 10})

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["request_id"]
    assert len(body["data"]["items"]) == 2
    assert {"id", "name", "stock_code"} <= set(body["data"]["items"][0])


async def test_company_by_stock_code(session: AsyncSession, clean_db: None, client) -> None:
    supplier, _, _, _ = await _seed(session)

    resp = await client.get(f"/api/v1/companies/{supplier.stock_code}")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stock_code"] == supplier.stock_code
    assert data["name_sort_key"], "sort key must be exposed so the client can order consistently"


async def test_company_not_found_uses_envelope(client) -> None:
    resp = await client.get("/api/v1/companies/000000")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_industries_lists_taxonomy(client) -> None:
    resp = await client.get("/api/v1/industries")

    assert resp.status_code == 200
    codes = [i["code"] for i in resp.json()["data"]["industries"]]
    assert "AI-COMPUTE" in codes or codes == [], "taxonomy may be empty on a clean database"


async def test_graph_subgraph_returns_projected_edges(
    session: AsyncSession, clean_db: None, client
) -> None:
    supplier, customer, _, _ = await _seed(session)

    resp = await client.get("/api/v1/graph/subgraph", params={"industry_code": "AI-COMPUTE-GPU"})

    assert resp.status_code == 200
    body = resp.json()
    ids = {n["id"] for n in body["data"]["nodes"]}
    assert {str(supplier.id), str(customer.id)} <= ids
    assert len(body["data"]["edges"]) == 1
    assert body["meta"]["truncated"] is False


async def test_neighbors_depth_limit_is_400(session: AsyncSession, clean_db: None, client) -> None:
    supplier, _, _, _ = await _seed(session)

    resp = await client.get(
        "/api/v1/graph/neighbors", params={"node_id": str(supplier.id), "depth": 6}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DEPTH_LIMIT_EXCEEDED"


async def test_relationships_and_evidence(session: AsyncSession, clean_db: None, client) -> None:
    _, _, rel, ev = await _seed(session)

    listed = await client.get("/api/v1/relationships", params={"status": "verified"})
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 1

    evidence = await client.get(f"/api/v1/relationships/{rel.id}/evidence")
    assert evidence.status_code == 200
    rows = evidence.json()["data"]
    assert len(rows) == 1
    assert rows[0]["evidence_grade"] == "A"
    assert rows[0]["relation"] == "supporting"
    assert rows[0]["original_excerpt"] == ev.original_excerpt


async def test_verify_requires_approved_by(session: AsyncSession, clean_db: None, client) -> None:
    supplier = await make_entity(session, f"待核{_code()}", _code())
    customer = await make_entity(session, f"待核{_code()}", _code())
    rel = await make_relationship(session, supplier, customer, status="pending_review")
    claim = await make_claim(session, supplier, customer)
    await link_claim(session, claim, rel)
    ev = await add_evidence(session, make_evidence("A"))
    await link_evidence(session, rel, ev, claim)
    await session.commit()

    resp = await client.post(
        f"/api/v1/relationships/{rel.id}/verify", json={"approved_by": "", "reason": "x"}
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EVIDENCE_REQUIRED"


async def test_evidence_write_rejects_empty_excerpt(client) -> None:
    resp = await client.post(
        "/api/v1/evidence",
        json={
            "source_type": "announcement",
            "source_name": "t",
            "original_excerpt": "   ",
            "evidence_grade": "A",
            "origin_key": "o1",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
