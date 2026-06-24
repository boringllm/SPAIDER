"""Tool registry for the Spider Kali MCP server.

Each pentest tool is registered with the ``@tool`` decorator, which records its name, a
DETAILED description (what it does + the impact of its parameters), a JSON-schema for its
arguments, an approval CATEGORY (one of the categories Spider understands —
recon/enum/web/exploit/bruteforce/network/destructive), and the list of Kali binaries it
needs. The category travels to Spider in the MCP ``tools/list`` metadata so the operator's
tool-approval policy can gate the right things.

Add a new tool by writing an ``async def`` handler in one of the modules under ``tools/``
and decorating it. Keep the descriptions precise — pentest tools have parameters with very
different blast radius, and the agent decides what to run from these descriptions alone."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Handler = Callable[[dict], Awaitable[str]]


@dataclass
class KaliTool:
    name: str
    description: str
    input_schema: dict
    handler: Handler
    category: str = "enum"
    requires: list[str] = field(default_factory=list)


REGISTRY: dict[str, KaliTool] = {}


def tool(name: str, description: str, input_schema: dict, category: str = "enum",
         requires: list[str] | None = None) -> Callable[[Handler], Handler]:
    """Register a Kali tool. ``requires`` is the list of CLI binaries it shells out to;
    if any are missing the tool reports that cleanly instead of crashing."""
    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = KaliTool(
            name=name, description=description, input_schema=input_schema,
            handler=fn, category=category, requires=requires or [],
        )
        return fn
    return deco


def mcp_tool_list() -> list[dict]:
    """Render the registry as MCP ``tools/list`` entries. ``_meta.category`` is read by
    Spider's MCP client to assign each tool an approval category; ``_meta.requires`` lets
    the UI show which Kali binaries back the tool and whether they are installed.

    For tools that have a static output filter, a ``raw`` boolean parameter is injected into the
    advertised schema so the agent can opt into the FULL unfiltered output on demand (see
    ``tools/_filters.py``)."""
    from .tools._filters import has_filter

    out: list[dict] = []
    for t in REGISTRY.values():
        missing = [b for b in t.requires if shutil.which(b) is None]
        schema = t.input_schema
        if has_filter(t.name):
            schema = _with_raw_param(schema)
        out.append({
            "name": t.name,
            "description": t.description,
            "inputSchema": schema,
            "_meta": {
                "category": t.category,
                "requires": t.requires,
                "available": not missing,
                "missing": missing,
                "filterable": has_filter(t.name),
            },
        })
    return out


def _with_raw_param(schema: dict) -> dict:
    """Return a shallow copy of ``schema`` with a ``raw`` boolean property added (output is
    filtered to notable findings by default; ``raw=true`` returns the tool's complete output)."""
    import copy

    s = copy.deepcopy(schema or {"type": "object", "properties": {}})
    props = s.setdefault("properties", {})
    props.setdefault("raw", {
        "type": "boolean",
        "description": "Return the tool's FULL unfiltered output. Default false: output is "
                       "statically filtered to the notable findings to save context.",
    })
    return s


async def call_tool(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Execute a registered tool. Returns ``(text, is_error)``. Missing binaries and handler
    exceptions are turned into clear, non-fatal error text for the agent.

    Reserved ``__*__`` names are operator/control operations (process monitor), NOT agent tools —
    they are handled here and deliberately absent from ``tools/list`` so agents never get them."""
    if name.startswith("__") and name.endswith("__"):
        return _control_op(name, arguments)
    t = REGISTRY.get(name)
    if t is None:
        return f"Unknown tool: {name}", True
    missing = [b for b in t.requires if shutil.which(b) is None]
    if missing:
        return (f"[unavailable] '{name}' needs these binaries which are not installed in this "
                f"Kali container: {', '.join(missing)}. Install them (e.g. `apt install ...`) or "
                f"use a different tool."), True
    arguments = dict(arguments or {})
    # `raw` (agent opt-out of filtering) is a wrapper concern, not a handler arg — pull it out
    # before dispatch. The global filter toggle rides in the JSON-RPC _meta Spider sends.
    raw = bool(arguments.pop("raw", False))
    try:
        result = await t.handler(arguments)
    except ValueError as e:  # bad/missing arguments — recoverable
        return f"Error: {e}", True
    except Exception as e:  # noqa: BLE001
        return f"Unexpected tool error in '{name}': {e}", True
    return _maybe_filter(name, result, raw=raw), False


def _maybe_filter(name: str, result: str, raw: bool) -> str:
    """Apply the tool's static output filter unless the agent asked for ``raw`` output or the
    operator disabled filtering globally (carried in CURRENT_META['filter'], default on)."""
    if raw:
        return result
    from .tools._filters import apply_filter
    from .tools._procs import CURRENT_META

    if not CURRENT_META.get().get("filter", True):
        return result
    return apply_filter(name, result)


def _control_op(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    """Operator process-monitor operations (called by Spider, never by agents). Results are
    returned as JSON text. See ``tools/_procs.py``."""
    import json

    from .tools import _procs

    if name == "__list_processes__":
        return json.dumps(_procs.list_processes(arguments.get("session") or None)), False
    if name == "__kill_process__":
        rec = _procs.kill_process(str(arguments.get("proc_id", "")))
        if rec is None:
            return json.dumps({"ok": False, "error": "no such process (it may have already finished)"}), False
        return json.dumps({"ok": True, "killed": rec}), False
    if name == "__kill_session__":
        killed = _procs.kill_session(str(arguments.get("session", "")))
        return json.dumps({"ok": True, "count": len(killed), "killed": killed}), False
    return f"Unknown control op: {name}", True
