"""User-defined tools — the one place to add new internal tools by writing code.

To add a tool:
  1. Write an async handler `async def _h_my_tool(agent, args) -> str:` that returns
     a string (what the model sees). Raise `ToolError("...")` for recoverable errors.
  2. Append a `Tool(...)` entry to the dict returned by `custom_tools()` below.
  3. (optional) Set `requires_approval=True` to gate it behind the command-approval
     flow; set `parallel_safe=False` for side-effecting tools.

That's it — the tool is auto-discovered everywhere: it appears in the Settings
"Internal tools" list, becomes selectable when creating custom agents, and can be
added to any role's tool list. No registration elsewhere is required.

`agent` is the running Agent; useful members:
  agent.session            -> the Session (workspace, findings, plan, owner…)
  agent.session.workspace  -> per-session working directory (pathlib.Path)
  agent.name / agent.role  -> identity of the calling agent
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import Tool, ToolError  # noqa: F401  (ToolError re-exported for tool authors)

if TYPE_CHECKING:
    from ..agents import Agent


# --------------------------------------------------------------------------- #
# Example (disabled). Copy this shape to add your own tool, then register it in
# `custom_tools()`.
# --------------------------------------------------------------------------- #
async def _h_sha256_file(agent: "Agent", args: dict[str, Any]) -> str:
    import hashlib
    from pathlib import Path

    raw = args.get("path", "")
    if not raw:
        raise ToolError("path is required")
    p = Path(raw)
    if not p.is_absolute():
        p = (agent.session.workspace / p).resolve()
    if not p.exists():
        raise ToolError(f"File not found: {p}")
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return f"sha256({p.name}) = {h}"


def custom_tools() -> dict[str, Tool]:
    """Return user-defined tools keyed by name. Add entries here."""
    return {
        "sha256_file": Tool(
            name="sha256_file",
            description="Compute the SHA-256 hash of a file. Relative paths resolve "
            "against the session workspace. Useful for fingerprinting a sample or PoC.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File to hash."}},
                "required": ["path"],
            },
            handler=_h_sha256_file,
        ),
    }
