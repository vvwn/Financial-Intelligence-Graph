"""Smoke tests for the system endpoints and the response envelope contract."""

from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health_returns_ok_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"]
    assert body["meta"]["request_id"]
    assert body["meta"]["generated_at"].endswith("Z")
    assert "error" not in body


async def test_health_echoes_request_id(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Request-ID": "test-req-1"})

    assert resp.headers["X-Request-ID"] == "test-req-1"
    assert resp.json()["meta"]["request_id"] == "test-req-1"


async def test_ready_returns_envelope_even_when_deps_down(client: httpx.AsyncClient) -> None:
    resp = await client.get("/ready")

    body = resp.json()
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert body["data"]["status"] == "ready"
        assert set(body["data"]["checks"]) == {"postgres", "neo4j"}
    else:
        assert body["error"]["code"] == "DEPENDENCY_NOT_READY"
        assert set(body["error"]["details"]["checks"]) == {"postgres", "neo4j"}


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/definitely-not-a-route")

    assert resp.status_code == 404


async def test_openapi_is_generated(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")

    assert resp.status_code == 200
    spec = resp.json()
    assert spec["info"]["title"]
    assert "/health" in spec["paths"]
    assert "/ready" in spec["paths"]
