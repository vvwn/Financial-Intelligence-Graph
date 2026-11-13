"""iFinD MCP collector (同花顺 iFinD).

Protocol notes, verified on 2026-11-13:

  BASE  = https://api-mcp.51ifind.com:8643/ds-mcp-servers
  auth  = `Authorization: <token>`   (raw value, NOT "Bearer <token>")
  flow  = initialize (session id in response header)
        -> notifications/initialized (echo the session id)
        -> tools/call

Quota, measured by a controlled test (7 -> 8 on one call):

  * 1 tool call = 1 quota unit
  * identical parameters are NOT cached server-side — a repeat costs again
  * failed calls also consume (a 502 and a "node not found" each cost 1)

Therefore this module keeps a **local response cache** and a **budget guard**.
Re-running a build must not spend quota twice for the same question.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import REPO_ROOT, settings

logger = logging.getLogger("fig.collector.ifind")

BASE = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"
SERVICES = {
    "stock": f"{BASE}/hexin-ifind-ds-stock-mcp",
    "fund": f"{BASE}/hexin-ifind-ds-fund-mcp",
    "edb": f"{BASE}/hexin-ifind-ds-edb-mcp",
    "news": f"{BASE}/hexin-ifind-ds-news-mcp",
    "bond": f"{BASE}/hexin-ifind-ds-bond-mcp",
    "global_stock": f"{BASE}/hexin-ifind-ds-global-stock-mcp",
    "index": f"{BASE}/hexin-ifind-ds-index-mcp",
    "futures": f"{BASE}/hexin-ifind-ds-futures-mcp",
    "enterprise": f"{BASE}/kuaicha-enterprise-mcp",
    "law": f"{BASE}/hexin-law-mcp",
}

CACHE_DIR = REPO_ROOT / ".cache" / "ifind" / "responses"
TIMEOUT = 60.0
PROTOCOL_VERSION = "2025-03-26"


class QuotaBudgetExceeded(RuntimeError):
    """Raised before a call that would exceed the local budget."""


@dataclass
class CallLedger:
    """Every tool call this process makes, so it can be reconciled with the console."""

    calls: list[dict] = field(default_factory=list)
    budget: int = 0

    def remaining(self) -> int:
        return max(0, self.budget - len(self.calls)) if self.budget else 10**9

    def record(self, tool_id: str, params: dict, ok: bool, note: str = "") -> None:
        self.calls.append({"tool_id": tool_id, "params": params, "ok": ok, "note": note})

    def summary(self) -> dict:
        return {
            "calls": len(self.calls),
            "ok": sum(1 for c in self.calls if c["ok"]),
            "failed": sum(1 for c in self.calls if not c["ok"]),
            "detail": self.calls,
        }


class IfindClient:
    #: Minimum gap between two tool calls. Bursting triggers throttling, and a
    #: throttled call still costs quota — so pacing is cheaper than retrying.
    MIN_INTERVAL_SECONDS = 3.0

    def __init__(self, service: str = "enterprise", *, budget: int = 0) -> None:
        token = (settings.ifind_mcp_token or "").strip()
        if not token:
            raise RuntimeError("IFIND_MCP_TOKEN is not set; put it in .env (never commit it)")
        if service not in SERVICES:
            raise ValueError(f"unknown service {service!r}; expected one of {sorted(SERVICES)}")

        self._token = token
        self._url = SERVICES[service]
        self._session: str | None = None
        self._http = httpx.Client(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": token,
                "User-Agent": "fig-collector",
            },
            timeout=TIMEOUT,
        )
        self.ledger = CallLedger(budget=budget)
        self._last_call_at = 0.0

    # -- transport ---------------------------------------------------------

    def _handshake(self) -> str:
        """Initialize and return the session id. Retries: the header is flaky."""
        last_error = ""
        for _ in range(5):
            resp = self._http.post(
                self._url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "fig-collector", "version": "0.1"},
                    },
                },
            )
            session = resp.headers.get("mcp-session-id")
            if session:
                self._http.post(
                    self._url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers={"mcp-session-id": session},
                )
                return session
            last_error = f"status={resp.status_code} body={resp.text[:80]}"
            logger.warning("handshake returned no session id: %s", last_error)
        raise RuntimeError(f"iFinD handshake failed after retries: {last_error}")

    def _ensure_session(self) -> str:
        if self._session is None:
            self._session = self._handshake()
        return self._session

    # -- tool calls --------------------------------------------------------

    def call_tool(self, tool_id: str, params: dict | None = None) -> dict:
        """One quota-consuming call. Cached locally by (tool_id, params)."""
        params = params or {}
        cached = self._cache_read(tool_id, params)
        if cached is not None:
            logger.info("cache hit: %s %s", tool_id, params)
            return cached

        if self.ledger.budget and self.ledger.remaining() <= 0:
            raise QuotaBudgetExceeded(
                f"local budget of {self.ledger.budget} calls reached; refusing to spend more"
            )

        session = self._ensure_session()
        self._pace()
        payload = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "kuaicha_tool_call",
                "arguments": {
                    "tool_id": tool_id,
                    "params_to_tool": json.dumps(params, ensure_ascii=False),
                },
            },
        }
        resp = self._http.post(self._url, json=payload, headers={"mcp-session-id": session})
        try:
            body = resp.json()
            text = body["result"]["content"][0]["text"]
            result = json.loads(text)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # The gateway sometimes answers with a non-JSON page (rate limit, 5xx
            # passthrough). The call is already spent, so record it and move on
            # rather than aborting a batch.
            self.ledger.record(tool_id, params, False, f"unparseable: {type(exc).__name__}")
            logger.warning("tool %s returned unparseable body: %s", tool_id, resp.text[:120])
            return {"data": {"status_code": -1, "status_msg": "unparseable response"}}

        ok = result.get("data", {}).get("status_code") == 0
        self.ledger.record(tool_id, params, ok, str(result.get("data", {}).get("status_msg"))[:60])
        if ok:
            self._cache_write(tool_id, params, result)
        else:
            logger.warning("tool %s returned failure: %s", tool_id, result.get("data"))
        return result

    def discover(self, query: str) -> dict:
        """Capability search. Also costs 1 call, so it is cached too."""
        params = {"query": query}
        cached = self._cache_read("kuaicha_tool_discover", params)
        if cached is not None:
            return cached

        if self.ledger.budget and self.ledger.remaining() <= 0:
            raise QuotaBudgetExceeded("local budget reached before discover")

        session = self._ensure_session()
        self._pace()
        resp = self._http.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "kuaicha_tool_discover", "arguments": params},
            },
            headers={"mcp-session-id": session},
        )
        result = json.loads(resp.json()["result"]["content"][0]["text"])
        self.ledger.record("kuaicha_tool_discover", params, True, "")
        self._cache_write("kuaicha_tool_discover", params, result)
        return result

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self.MIN_INTERVAL_SECONDS:
            time.sleep(self.MIN_INTERVAL_SECONDS - elapsed)
        self._last_call_at = time.monotonic()

    # -- cache -------------------------------------------------------------

    def _cache_path(self, tool_id: str, params: dict) -> Path:
        key = hashlib.sha256(
            f"{tool_id}|{json.dumps(params, sort_keys=True, ensure_ascii=False)}".encode()
        ).hexdigest()[:32]
        return CACHE_DIR / f"{tool_id[:40]}_{key}.json"

    def _cache_read(self, tool_id: str, params: dict) -> dict | None:
        path = self._cache_path(tool_id, params)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def _cache_write(self, tool_id: str, params: dict, result: dict) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._cache_path(tool_id, params).write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )

    def close(self) -> None:
        self._http.close()


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def chain_tree(client: IfindClient) -> list[dict]:
    result = client.call_tool("filter_get_industry_chain_tree_structure", {})
    raw = json.loads(result["data"]["data"]["raw"])
    return raw["data"]["list"]


def chain_atlas(client: IfindClient, node_code: str) -> dict:
    result = client.call_tool("filter_get_industry_chain_atlas", {"node_code": node_code})
    if result["data"].get("status_code") != 0:
        return {}
    raw = json.loads(result["data"]["data"]["raw"])
    return raw["data"]


def find_node(tree: list[dict], name: str) -> list[tuple[str, str, int]]:
    """Search the chain tree.

    Exact name matches come first, then partial matches; within each group the
    deepest (most specific) node wins. Without this ordering "晶圆制造" matches
    "晶圆制造材料", which is a different node.
    """
    exact: list[tuple[str, str, int]] = []
    partial: list[tuple[str, str, int]] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            node_name = node.get("node_name", "")
            item = (node["node_code"], node_name, node.get("level", 0))
            if node_name == name:
                exact.append(item)
            elif name in node_name and len(node_name) <= len(name) + 3:
                partial.append(item)
            walk(node.get("sub_node") or [])

    walk(tree)
    exact.sort(key=lambda x: -x[2])
    partial.sort(key=lambda x: -x[2])
    return exact + partial


__all__ = [
    "SERVICES",
    "CallLedger",
    "IfindClient",
    "QuotaBudgetExceeded",
    "chain_atlas",
    "chain_tree",
    "find_node",
]
