"""Tool definitions: native (shell/file), agent-control, strix-inspired pentest, custom,
and MCP-backed (Kali) tools.

`base_tools()` is the single source of truth for every internally-implemented tool
(everything except MCP-backed tools). Adding a new tool to `custom.py` (or `pentest.py`)
makes it appear here automatically — and therefore everywhere in the app (Settings list,
custom-agent tool picker, role tool lists). MCP/Kali tools are discovered at runtime."""
from .base import Tool, ToolError
from .control import control_tools
from .custom import custom_tools
from .native import native_tools
from .pentest import pentest_tools


def base_tools() -> dict[str, Tool]:
    """All natively-implemented tools (native + control + pentest + custom), keyed by name."""
    return {**native_tools(), **control_tools(), **pentest_tools(), **custom_tools()}


def tool_catalog() -> list[dict]:
    """UI/metadata view of every internal tool: name, description, schema, flags, category, source."""
    sources = [
        ("file/shell", native_tools()),
        ("agent-control", control_tools()),
        ("pentest", pentest_tools()),
        ("custom", custom_tools()),
    ]
    out: list[dict] = []
    for source, tools in sources:
        for t in tools.values():
            out.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "source": source,
                    "category": t.category,
                    "requires_approval": t.requires_approval,
                    "parallel_safe": t.parallel_safe,
                    "parameters": (t.input_schema or {}).get("properties", {}),
                    "required": (t.input_schema or {}).get("required", []),
                }
            )
    return sorted(out, key=lambda d: (d["source"], d["name"]))


__all__ = ["Tool", "ToolError", "base_tools", "tool_catalog"]
