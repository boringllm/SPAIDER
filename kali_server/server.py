"""Spider Kali MCP server — an MCP-over-HTTP (Streamable-HTTP) endpoint that exposes the
Kali pentest tools to Spider.

It speaks the minimal JSON-RPC that Spider's MCP client (`spider/tools/mcp.py`) uses:
``initialize`` -> ``notifications/initialized`` -> ``tools/list`` -> ``tools/call``. Responses
are plain JSON (the client also accepts SSE, but JSON is simpler and sufficient).

Run this INSIDE your Kali container, then point Spider's `kali.url` at it
(default http://<kali-host>:8765/mcp). See README.md.

SECURITY: this server runs real offensive tools. Bind it to a trusted network only, set an
optional ``SPIDER_KALI_TOKEN`` to require a bearer token, and set ``SPIDER_SCOPE`` to restrict
targets. It is meant to sit on an isolated lab/engagement network."""
from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import tools as _tools  # noqa: F401  (side effect: registers all tools)
from .registry import REGISTRY, call_tool, mcp_tool_list

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "spider-kali", "version": "0.1.0"}

app = FastAPI(title="Spider Kali MCP server", version="0.1.0")

# Optional shared-secret bearer token. When set, every /mcp request must present it.
_TOKEN = os.environ.get("SPIDER_KALI_TOKEN", "").strip()


def _rpc_result(rid, result) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _authorized(authorization: str | None) -> bool:
    if not _TOKEN:
        return True
    if not authorization:
        return False
    parts = authorization.split(None, 1)
    return len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == _TOKEN


@app.get("/")
async def index() -> PlainTextResponse:
    """Human-friendly status page listing the registered tools and their availability."""
    lines = [f"Spider Kali MCP server — {len(REGISTRY)} tools", ""]
    for entry in mcp_tool_list():
        meta = entry["_meta"]
        status = "ok" if meta["available"] else f"MISSING: {', '.join(meta['missing'])}"
        lines.append(f"  [{meta['category']:<10}] {entry['name']:<22} ({status})")
    lines += ["", "MCP endpoint: POST /mcp", f"auth required: {bool(_TOKEN)}",
              f"scope restriction: {os.environ.get('SPIDER_SCOPE') or '(none)'}"]
    return PlainTextResponse("\n".join(lines))


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "tools": len(REGISTRY)}


@app.post("/mcp")
async def mcp(request: Request, authorization: str | None = Header(default=None)):
    """The MCP JSON-RPC endpoint. Handles initialize / initialized / tools.list / tools.call."""
    if not _authorized(authorization):
        return JSONResponse(_rpc_error(None, -32001, "unauthorized: bad or missing bearer token"),
                            status_code=401)
    try:
        msg = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(_rpc_error(None, -32700, "parse error"), status_code=400)

    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    # Notifications (no id) — acknowledge with 202, no body needed.
    if rid is None and method and method.startswith("notifications/"):
        return JSONResponse({}, status_code=202)

    headers = {"Mcp-Session-Id": request.headers.get("Mcp-Session-Id") or uuid.uuid4().hex}

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
        return JSONResponse(_rpc_result(rid, result), headers=headers)

    if method == "tools/list":
        return JSONResponse(_rpc_result(rid, {"tools": mcp_tool_list()}), headers=headers)

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        # Spider tags each call with who launched it ({session, agent, agent_name, tool}) in
        # `_meta`, so the process registry can attribute the running command. Scope it to this task.
        from .tools._procs import CURRENT_META

        CURRENT_META.set(params.get("_meta") or {})
        text, is_error = await call_tool(name, arguments)
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
        return JSONResponse(_rpc_result(rid, result), headers=headers)

    if method in ("ping",):
        return JSONResponse(_rpc_result(rid, {}), headers=headers)

    return JSONResponse(_rpc_error(rid, -32601, f"method not found: {method}"), headers=headers)
