"""Natively-implemented tools: host shell / process execution and file I/O.

These run on the SPAIDER host (Windows or Linux) — NOT in the Kali container. Heavy
offensive tooling lives in the Kali MCP server; these host tools are for local helper
work (prep wordlists/payloads, run a generated PoC, read/write files). Command-execution
is approval-gated by the tool's `category` ("shell"); the operator decides per category
what needs validation (Session.tool_needs_approval)."""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import Tool, ToolError

if TYPE_CHECKING:
    from ..agents import Agent

MAX_OUTPUT = 60_000  # chars returned to the model
DEFAULT_TIMEOUT = 120  # seconds


def _resolve(agent: "Agent", path: str) -> Path:
    """Resolve a tool-supplied path: absolute paths are used as-is, relative paths
    resolve against this session's workspace folder. Change this to sandbox file access."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (agent.session.workspace / p).resolve()


def _clip(text: str) -> str:
    """Truncate tool output to MAX_OUTPUT chars so a huge dump can't blow the model's
    context. Raise MAX_OUTPUT at the top of the file to allow larger results."""
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n...[truncated, {len(text) - MAX_OUTPUT} more chars]"
    return text


async def _run(cmd: list[str], timeout: int, cwd: str | None = None) -> str:
    """Run a subprocess (argv list), merging stderr into stdout, killing it on timeout,
    and returning ``[exit=N]\\n<clipped output>``. Shared by every command-exec tool below."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
    except FileNotFoundError as e:
        raise ToolError(f"Executable not found: {e}") from e
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ToolError(f"Command timed out after {timeout}s")
    decoded = out.decode("utf-8", errors="replace") if out else ""
    return f"[exit={proc.returncode}]\n{_clip(decoded)}"


# --------------------------------------------------------------------------- #
def _shell_argv(command: str) -> list[str]:
    """Build the argv to run `command` in the host's native shell, per OS.

    Windows -> pwsh (if installed) else powershell.exe, with -Command.
    POSIX   -> bash (if installed) else /bin/sh, with -c.
    This is what makes the host shell tool work the same on Windows and Linux."""
    if os.name == "nt":
        shell = shutil.which("pwsh") or "powershell.exe"
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    shell = shutil.which("bash") or "/bin/sh"
    return [shell, "-c", command]


async def _h_run_shell(agent: "Agent", args: dict[str, Any]) -> str:
    """Run a command in the host's native shell (PowerShell on Windows, bash/sh on
    Linux), in the workspace dir. Approval-gated by category."""
    command = args.get("command", "")
    if not command:
        raise ToolError("command is required")
    timeout = int(args.get("timeout", DEFAULT_TIMEOUT))
    return await _run(_shell_argv(command), timeout, cwd=str(agent.session.workspace))


async def _h_run_process(agent: "Agent", args: dict[str, Any]) -> str:
    """Launch a binary with optional args and capture its output (e.g. run a sample or
    a generated PoC). Approval-gated."""
    path = args.get("path", "")
    if not path:
        raise ToolError("path is required")
    proc_args = args.get("args", []) or []
    timeout = int(args.get("timeout", DEFAULT_TIMEOUT))
    return await _run([path, *[str(a) for a in proc_args]], timeout, cwd=str(agent.session.workspace))


async def _h_read_file(agent: "Agent", args: dict[str, Any]) -> str:
    """Read a UTF-8 text file (clipped to MAX_OUTPUT). Relative paths -> workspace."""
    p = _resolve(agent, args.get("path", ""))
    if not p.exists():
        raise ToolError(f"File not found: {p}")
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ToolError(str(e)) from e
    return _clip(data)


async def _h_write_file(agent: "Agent", args: dict[str, Any]) -> str:
    """Write (overwrite) a text file, creating parent dirs. Relative paths -> workspace."""
    p = _resolve(agent, args.get("path", ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args.get("content", ""), encoding="utf-8")
    return f"Wrote {len(args.get('content', ''))} chars to {p}"


async def _h_append_file(agent: "Agent", args: dict[str, Any]) -> str:
    """Append text to a file (creating it and parent dirs if missing)."""
    p = _resolve(agent, args.get("path", ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(args.get("content", ""))
    return f"Appended to {p}"


async def _h_list_dir(agent: "Agent", args: dict[str, Any]) -> str:
    """List a directory's entries (name + dir/size). Defaults to the workspace root."""
    p = _resolve(agent, args.get("path", "."))
    if not p.exists():
        raise ToolError(f"Path not found: {p}")
    if p.is_file():
        return f"{p} (file, {p.stat().st_size} bytes)"
    entries = []
    for child in sorted(p.iterdir()):
        kind = "dir" if child.is_dir() else f"{child.stat().st_size}B"
        entries.append(f"  {child.name} [{kind}]")
    return f"{p}:\n" + "\n".join(entries) if entries else f"{p}: (empty)"


async def _h_make_dir(agent: "Agent", args: dict[str, Any]) -> str:
    """Create a directory (and any parents). Relative paths -> workspace."""
    p = _resolve(agent, args.get("path", ""))
    p.mkdir(parents=True, exist_ok=True)
    return f"Created directory {p}"


def native_tools() -> dict[str, Tool]:
    """All natively-implemented host/file tools, keyed by name (these run on the SPAIDER host,
    Windows or Linux — not in Kali). They are 'internal' (mandatory) tools and are never
    trimmed by the tool_selector. Gating is policy-driven via each tool's ``category`` (the
    operator decides, per category, what needs validation)."""
    return {
        "run_shell": Tool(
            name="run_shell",
            description="Execute a command in the SPAIDER host's native shell (PowerShell on "
            "Windows, bash/sh on Linux). Use for local helper tooling, orchestrating utilities, "
            "and preparing payloads/wordlists. Offensive scans against targets should use the "
            "Kali tools instead.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command line to run."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)."},
                },
                "required": ["command"],
            },
            handler=_h_run_shell,
            parallel_safe=False,
            category="shell",
        ),
        "run_process": Tool(
            name="run_process",
            description="Launch a binary/executable on the SPAIDER host with optional arguments and "
            "capture its output. Use to run a local helper tool or a generated PoC.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the executable."},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "timeout": {"type": "integer"},
                },
                "required": ["path"],
            },
            handler=_h_run_process,
            parallel_safe=False,
            category="shell",
        ),
        "read_file": Tool(
            name="read_file",
            description="Read a text file. Relative paths resolve against the session workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_h_read_file,
            category="filesystem",
        ),
        "write_file": Tool(
            name="write_file",
            description="Write a text file (overwrites). Use to store notes, scripts, wordlists, or PoC source.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            handler=_h_write_file,
            category="filesystem",
        ),
        "append_file": Tool(
            name="append_file",
            description="Append text to a file (creates if missing).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
            handler=_h_append_file,
            category="filesystem",
        ),
        "list_dir": Tool(
            name="list_dir",
            description="List the contents of a directory.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
            handler=_h_list_dir,
            category="filesystem",
        ),
        "make_dir": Tool(
            name="make_dir",
            description="Create a directory (and parents).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_h_make_dir,
            category="filesystem",
        ),
    }
