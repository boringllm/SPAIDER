"""Modular, file-based agent definitions.

Each role has a folder under the configurable agents directory:

    agents/<role>/prompt.md   <- system prompt (editable)
    agents/<role>/mcp.json    <- mcpo-style MCP config (editable / UI-managed)

MCP servers declared in a role's mcp.json are available to that agent AND every
sub-agent it spawns. Each server entry may carry an "enabled" flag (default true)
so agents can toggle servers on/off without deleting them.

mcp.json shape (mcpo / Claude-desktop style):

    {
      "mcpServers": {
        "kali":   {"type": "streamable-http", "url": "http://kali-host:8765/mcp", "enabled": true},
        "custom": {"command": "python", "args": ["my_mcp_server.py"], "enabled": true}
      }
    }

Note: the main Kali offensive-tool server is usually configured once via the top-level
`kali` config (Settings -> Kali) rather than per-agent. Use per-agent mcp.json for extra,
role-specific MCP servers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config as cfg_mod


def agents_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("agents_dir", str(cfg_mod.BASE_DIR / "agents")))


def _mcp_template() -> dict:
    return {
        "_comment": "mcpo-style config. Servers here are usable by this agent and all "
        "its sub-agents. stdio: {'command','args','env'} ; http: {'type':'streamable-http','url'}. "
        "Each server may have an 'enabled' flag (default true).",
        "mcpServers": {},
    }


def ensure_role_folder(cfg: dict[str, Any], role: str, system_default: str) -> None:
    folder = agents_dir(cfg) / role
    folder.mkdir(parents=True, exist_ok=True)
    prompt = folder / "prompt.md"
    if not prompt.exists():
        prompt.write_text(system_default, encoding="utf-8")
    mcp = folder / "mcp.json"
    if not mcp.exists():
        mcp.write_text(json.dumps(_mcp_template(), indent=2), encoding="utf-8")


def ensure_scaffold(cfg: dict[str, Any]) -> None:
    """Create agents/<role>/ folders for every known role (built-in + custom)."""
    from .registry import role_specs

    agents_dir(cfg).mkdir(parents=True, exist_ok=True)
    for role, spec in role_specs(cfg).items():
        ensure_role_folder(cfg, role, spec["system_default"])


def normalize_mcp(raw: dict) -> dict[str, dict]:
    """mcpo `mcpServers` -> {name: {transport, command, args, url, env, enabled}}."""
    servers = (raw or {}).get("mcpServers", {})
    out: dict[str, dict] = {}
    for name, s in servers.items():
        if not isinstance(s, dict):
            continue
        stype = (s.get("type") or s.get("server_type") or "").lower()
        url = s.get("url", "")
        is_http = bool(url) or "http" in stype
        out[name] = {
            "transport": "http" if is_http else "stdio",
            "command": s.get("command", ""),
            "args": s.get("args", []) or [],
            "url": url,
            "env": s.get("env", {}) or {},
            "enabled": s.get("enabled", True),
        }
    return out


def _system_for(cfg: dict[str, Any], role: str) -> str:
    from .registry import role_specs

    spec = role_specs(cfg).get(role)
    return spec["system_default"] if spec else f"You are the {role} agent."


def load_def(cfg: dict[str, Any], role: str) -> dict[str, Any]:
    folder = agents_dir(cfg) / role
    prompt_path = folder / "prompt.md"
    mcp_path = folder / "mcp.json"
    system = _system_for(cfg, role)
    if prompt_path.exists():
        try:
            system = prompt_path.read_text(encoding="utf-8")
        except OSError:
            pass
    mcp: dict[str, dict] = {}
    if mcp_path.exists():
        try:
            mcp = normalize_mcp(json.loads(mcp_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            mcp = {}
    return {"role": role, "system": system, "mcp": mcp, "dir": str(folder)}


def load_all(cfg: dict[str, Any]) -> dict[str, dict]:
    from .registry import role_specs

    ensure_scaffold(cfg)
    return {role: load_def(cfg, role) for role in role_specs(cfg)}


def raw_def(cfg: dict[str, Any], role: str) -> dict[str, Any]:
    from .registry import role_specs

    folder = agents_dir(cfg) / role
    prompt_path = folder / "prompt.md"
    mcp_path = folder / "mcp.json"
    spec = role_specs(cfg).get(role, {})
    prompt = spec.get("system_default", "")
    if prompt_path.exists():
        prompt = prompt_path.read_text(encoding="utf-8")
    mcp_text = json.dumps(_mcp_template(), indent=2)
    if mcp_path.exists():
        mcp_text = mcp_path.read_text(encoding="utf-8")
    return {
        "role": role,
        "prompt": prompt,
        "mcp": mcp_text,
        "tools": spec.get("tools", []),
        "builtin": spec.get("builtin", True),
        "servers": list_mcp(cfg, role),
        "dir": str(folder),
    }


def save_def(cfg: dict[str, Any], role: str, prompt: str | None, mcp_text: str | None) -> None:
    from .registry import role_specs

    if role not in role_specs(cfg):
        raise ValueError(f"unknown role {role}")
    folder = agents_dir(cfg) / role
    folder.mkdir(parents=True, exist_ok=True)
    if prompt is not None:
        (folder / "prompt.md").write_text(prompt, encoding="utf-8")
    if mcp_text is not None:
        json.loads(mcp_text)  # validate
        (folder / "mcp.json").write_text(mcp_text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Structured MCP-server management (used by the UI)
# --------------------------------------------------------------------------- #
def _read_servers(cfg: dict[str, Any], role: str) -> dict:
    """Load a role's raw mcp.json (the mcpo ``{mcpServers: {...}}`` shape), falling back to
    an empty template if missing/invalid. The structured add/remove/toggle helpers build on this."""
    mcp_path = agents_dir(cfg) / role / "mcp.json"
    if not mcp_path.exists():
        return _mcp_template()
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = _mcp_template()
    data.setdefault("mcpServers", {})
    return data


def _write_servers(cfg: dict[str, Any], role: str, data: dict) -> None:
    folder = agents_dir(cfg) / role
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mcp.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_mcp(cfg: dict[str, Any], role: str) -> list[dict]:
    """Return a role's MCP servers as a normalised list (for the Settings UI)."""
    norm = normalize_mcp(_read_servers(cfg, role))
    return [{"name": n, **d} for n, d in norm.items()]


def add_mcp(cfg: dict[str, Any], role: str, name: str, config_text: str) -> None:
    """Add server(s). `config_text` is JSON — either a single server config object,
    or a full `{"mcpServers": {...}}` block (in which case `name` is optional)."""
    parsed = json.loads(config_text)
    data = _read_servers(cfg, role)
    if isinstance(parsed, dict) and "mcpServers" in parsed:
        for n, s in parsed["mcpServers"].items():
            s.setdefault("enabled", True)
            data["mcpServers"][n] = s
    else:
        if not name:
            raise ValueError("a server name is required when pasting a single server config")
        if not isinstance(parsed, dict):
            raise ValueError("config must be a JSON object")
        parsed.setdefault("enabled", True)
        data["mcpServers"][name] = parsed
    _write_servers(cfg, role, data)


def remove_mcp(cfg: dict[str, Any], role: str, name: str) -> None:
    data = _read_servers(cfg, role)
    data["mcpServers"].pop(name, None)
    _write_servers(cfg, role, data)


def set_mcp_enabled(cfg: dict[str, Any], role: str, name: str, enabled: bool) -> None:
    data = _read_servers(cfg, role)
    if name in data["mcpServers"]:
        data["mcpServers"][name]["enabled"] = bool(enabled)
        _write_servers(cfg, role, data)


def get_mcp_normalized(cfg: dict[str, Any], role: str, name: str) -> dict | None:
    return normalize_mcp(_read_servers(cfg, role)).get(name)
