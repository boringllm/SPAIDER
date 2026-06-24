"""Role registry: built-in roles plus user-defined custom agents.

Built-in roles (orchestrator, recon, web_app, network, exploitation, post_exploit,
reporting, summarizer, tool_selector) cannot be removed. Custom agents can be added/removed;
they are spawnable by the orchestrator. Custom role definitions persist in
`<agents_dir>/custom_roles.json`. Add a custom role to extend Spider with a new
pentest discipline (e.g. `cloud`, `mobile`, `wireless`, `social_eng`)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config as cfg_mod
from .roles import ROLES as BUILTIN_ROLES
from .tools import base_tools

CUSTOM_FILE = "custom_roles.json"

# A reasonable default toolset offered to new custom pentest agents.
DEFAULT_CUSTOM_TOOLS = [
    "read_file", "write_file", "append_file", "list_dir", "make_dir",
    "run_shell", "run_process",
    "terminal", "http_request", "record_note",
    "store_finding", "list_findings", "read_finding",
    "spawn_agent", "wait_for_agent", "message_agent", "get_agent_status", "validate_agent",
    "ask_parent", "request_file_load",
    "finish",
]


def all_tool_names() -> list[str]:
    """Every internal tool name (for the custom-agent tool picker in the UI)."""
    return sorted(base_tools().keys())


def _agents_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("agents_dir", str(cfg_mod.BASE_DIR / "agents")))


def _custom_path(cfg: dict[str, Any]) -> Path:
    return _agents_dir(cfg) / CUSTOM_FILE


def load_custom_roles(cfg: dict[str, Any]) -> dict[str, dict]:
    """Read user-defined roles from agents/custom_roles.json ({role: {system, tools}})."""
    p = _custom_path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_custom_roles(cfg: dict[str, Any], data: dict[str, dict]) -> None:
    _agents_dir(cfg).mkdir(parents=True, exist_ok=True)
    _custom_path(cfg).write_text(json.dumps(data, indent=2), encoding="utf-8")


def role_specs(cfg: dict[str, Any]) -> dict[str, dict]:
    """All roles -> {system_default, tools, builtin}."""
    specs: dict[str, dict] = {}
    for role, spec in BUILTIN_ROLES.items():
        specs[role] = {"system_default": spec["system"], "tools": list(spec["tools"]), "builtin": True}
    for role, c in load_custom_roles(cfg).items():
        if role in specs:
            continue
        specs[role] = {
            "system_default": c.get("system", f"You are the {role} agent."),
            "tools": list(c.get("tools", DEFAULT_CUSTOM_TOOLS)),
            "builtin": False,
        }
    return specs


# Roles the framework manages automatically — not manually spawnable by other agents.
# (orchestrator is the root; tool_selector/summarizer are helpers; reporting is launched
# by the operator's "generate report" action, not by an agent.)
_NON_SPAWNABLE = {"orchestrator", "tool_selector", "summarizer", "reporting"}


def spawnable_roles(cfg: dict[str, Any]) -> list[str]:
    """Roles the orchestrator (and other spawners) may spawn."""
    return [r for r in role_specs(cfg) if r not in _NON_SPAWNABLE]


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def add_custom_role(cfg: dict[str, Any], role: str, system: str, tools: list[str]) -> None:
    """Register a new custom agent role: validate the name, keep only known tools (always
    adding `finish`), persist to custom_roles.json, and scaffold its agents/<role>/ folder.
    The orchestrator can then spawn it. Raises ValueError on bad/duplicate names."""
    role = (role or "").strip().lower()
    if not _NAME_RE.match(role):
        raise ValueError("role name must be lowercase letters/digits/underscores (e.g. 'fuzzer')")
    if role in BUILTIN_ROLES:
        raise ValueError("cannot override a built-in role")
    custom = load_custom_roles(cfg)
    if role in custom:
        raise ValueError("a custom role with that name already exists")
    valid = set(all_tool_names())
    chosen = [t for t in (tools or DEFAULT_CUSTOM_TOOLS) if t in valid]
    if "finish" not in chosen:
        chosen.append("finish")
    custom[role] = {"system": system or f"You are the {role} agent.", "tools": chosen}
    _save_custom_roles(cfg, custom)
    # scaffold folder
    from . import agentdefs

    agentdefs.ensure_role_folder(cfg, role, custom[role]["system"])


def remove_custom_role(cfg: dict[str, Any], role: str) -> None:
    """Delete a custom role (built-ins cannot be removed). Raises ValueError otherwise."""
    if role in BUILTIN_ROLES:
        raise ValueError("built-in roles cannot be removed")
    custom = load_custom_roles(cfg)
    if role not in custom:
        raise ValueError("no such custom role")
    del custom[role]
    _save_custom_roles(cfg, custom)
