"""Tool base types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..agents import Agent


class ToolError(Exception):
    """Raised by a tool handler to signal a recoverable error returned to the model."""


# handler(agent, args) -> result string
ToolHandler = Callable[["Agent", dict[str, Any]], Awaitable[str]]


@dataclass
class Tool:
    """One callable capability exposed to an agent.

    SPAIDER extends ReLive's Tool with a ``category`` (one of config.TOOL_CATEGORIES). The
    category drives the human-in-the-loop tool-approval policy: the operator configures, per
    category, whether a tool runs automatically or must be validated first. ``requires_approval``
    remains a hard floor — a tool that sets it True is ALWAYS gated regardless of policy (reserve
    it for any inherently dangerous action you add)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    # Hard floor: True => always operator-gated (e.g. elevated local commands).
    requires_approval: bool = False
    parallel_safe: bool = True
    # Approval-policy category (see config.TOOL_CATEGORIES). MCP/Kali tools get their
    # category from the server's catalog; internal tools set it explicitly below.
    category: str = "control"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
