"""Smoke tests for system endpoints and the response envelope contract."""

from __future__ import annotations

import logging

import httpx
import pytest
from app.core.context import request_id_var
from app.core.logging import RequestIdFilter
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


async def test_ready_returns_envelope_with_all_checks(client: httpx.AsyncClient) -> None:
    resp = await client.get("/ready")

    body = resp.json()
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert body["data"]["status"] == "ready"
        assert set(body["data"]["checks"]) == {"postgres", "neo4j", "migration"}
    else:
        assert body["error"]["code"] == "DEPENDENCY_NOT_READY"
        assert set(body["error"]["details"]["checks"]) == {"postgres", "neo4j", "migration"}


async def test_404_uses_error_envelope_not_detail(client: httpx.AsyncClient) -> None:
    """Regression: FastAPI's default {"detail": ...} broke the contract while tests stayed green."""
    resp = await client.get("/api/v1/definitely-not-a-route")

    assert resp.status_code == 404
    body = resp.json()
    assert "detail" not in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"]


async def test_probes_are_not_versioned(client: httpx.AsyncClient) -> None:
    """Probes live at the root; the contract base path carries business endpoints only."""
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/api/v1/health")).status_code == 404


async def test_openapi_is_generated(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")

    assert resp.status_code == 200
    spec = resp.json()
    assert spec["info"]["title"]
    assert "/health" in spec["paths"]
    assert "/ready" in spec["paths"]


def test_log_filter_attaches_request_id() -> None:
    """A log line without request_id cannot be tied to the response the user saw."""
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    token = request_id_var.set("req-abc")
    try:
        assert RequestIdFilter().filter(record) is True
    finally:
        request_id_var.reset(token)

    assert record.request_id == "req-abc"
