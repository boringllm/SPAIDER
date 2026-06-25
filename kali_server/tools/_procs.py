"""Running-process registry for the SPAIDER Kali MCP server.

Every command launched by a tool (via ``_common.run`` / ``run_shell``) is registered here while
it runs and deregistered when it exits, tagged with WHO launched it (the SPAIDER session / agent /
tool, carried in the JSON-RPC ``_meta`` the control app sends). This lets the operator:

  * SEE what offensive tooling is currently running in the container, per session (an enumeration
    scan can easily overload a target), and
  * KILL a runaway process, and
  * have SPAIDER kill EVERY process of a session when that session is stopped.

Processes are launched in their own session/process-group (``start_new_session=True``) so a kill
takes down the whole tool tree (``/bin/sh -c`` plus the real tool it spawned), not just the shell.
"""
from __future__ import annotations

import contextvars
import os
import signal
import time
import uuid
from typing import Any

# Per-request metadata about the caller, set by the MCP server from the JSON-RPC ``_meta`` before
# a tool runs, and read by run()/run_shell() when they register a process. A ContextVar so it is
# correctly scoped to the handling task.
CURRENT_META: contextvars.ContextVar[dict] = contextvars.ContextVar("spider_meta", default={})

# proc_id -> record. ``proc`` is the live asyncio subprocess; the rest is JSON-serialisable.
_PROCS: dict[str, dict[str, Any]] = {}


def register(proc, command: str) -> str:
    """Record a freshly-spawned subprocess and return its registry id. Reads the caller tags
    (session/agent/tool) from CURRENT_META so the operator can attribute it."""
    meta = CURRENT_META.get() or {}
    pid = uuid.uuid4().hex[:12]
    _PROCS[pid] = {
        "id": pid,
        "pid": getattr(proc, "pid", None),
        "command": (command or "")[:600],
        "session": str(meta.get("session", "")),
        "agent": str(meta.get("agent", "")),
        "agent_name": str(meta.get("agent_name", "")),
        "tool": str(meta.get("tool", "")),
        "started": time.time(),
        "killed": False,
        "proc": proc,
    }
    return pid


def deregister(proc_id: str) -> None:
    _PROCS.pop(proc_id, None)


def was_killed(proc_id: str) -> bool:
    rec = _PROCS.get(proc_id)
    return bool(rec and rec.get("killed"))


def _public(rec: dict, now: float) -> dict:
    return {
        "id": rec["id"], "pid": rec["pid"], "command": rec["command"],
        "session": rec["session"], "agent": rec["agent"], "agent_name": rec["agent_name"],
        "tool": rec["tool"], "started": rec["started"], "killed": rec["killed"],
        "runtime": round(now - rec["started"], 1),
    }


def list_processes(session: str | None = None) -> list[dict]:
    """Public (JSON-serialisable) snapshot of running processes, optionally filtered to one
    SPAIDER session. Newest first."""
    now = time.time()
    out = [_public(r, now) for r in _PROCS.values() if not session or r["session"] == session]
    return sorted(out, key=lambda r: r["started"], reverse=True)


def _kill_record(rec: dict) -> None:
    rec["killed"] = True
    pid = rec.get("pid")
    if pid:
        # Kill the whole process group (the command runs in its own session), so the real tool
        # dies too — not just the /bin/sh that launched it.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    proc = rec.get("proc")
    if proc is not None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def kill_process(proc_id: str) -> dict | None:
    """Kill one process by registry id. Returns its public record (so the caller can tell the
    responsible agent), or None if there is no such process."""
    rec = _PROCS.get(proc_id)
    if rec is None:
        return None
    pub = _public(rec, time.time())
    _kill_record(rec)
    return pub


def kill_session(session: str) -> list[dict]:
    """Kill EVERY running process of a SPAIDER session (called when the session is stopped).
    Returns the list of killed records."""
    killed = []
    for rec in list(_PROCS.values()):
        if rec["session"] == session:
            killed.append(_public(rec, time.time()))
            _kill_record(rec)
    return killed
