"""Generic terminal & file tools on the Kali host (categories: shell / filesystem).

The escape hatch: when no purpose-built tool fits, the agent can run an arbitrary command in
Kali. This is powerful and gated as `shell` (operator-approved by default in Spider). Keep a
persistent working directory so commands chain naturally."""
from __future__ import annotations

import os

from ..registry import tool
from ._common import clip, require_arg, run_shell

# Persistent working directory for the generic terminal (per terminal_id).
_CWD: dict[str, str] = {}
_BASE = os.environ.get("SPIDER_KALI_WORKDIR", "/root/spider")


def _cwd(term_id: str) -> str:
    if term_id not in _CWD:
        os.makedirs(_BASE, exist_ok=True)
        _CWD[term_id] = _BASE
    return _CWD[term_id]


@tool(
    name="run_command",
    category="shell",
    requires=[],
    description=(
        "Run an ARBITRARY shell command on the Kali host and return its output. The flexible "
        "fallback for any tool/technique without a dedicated function (msfvenom, curl, nc, "
        "python exploit scripts, custom one-liners, etc.). Runs via /bin/sh -c with a "
        "PERSISTENT working directory per `terminal_id` (so `cd` sticks across calls). High "
        "impact — you can do anything Kali can; stay strictly in scope and avoid destructive "
        "commands. Prefer the dedicated tools when one exists (they set safe defaults)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command line to run."},
            "terminal_id": {"type": "string", "description": "Persistent session name for cwd (default 'default')."},
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["command"],
    },
)
async def run_command(args: dict) -> str:
    command = require_arg(args, "command")
    term_id = str(args.get("terminal_id") or "default")
    cwd = _cwd(term_id)
    marker = "__SPIDER_KCWD__"
    # IMPORTANT: assemble the marker AT RUNTIME from two literals ("__SPIDER" + "_KCWD__$PWD") so
    # the full marker string never appears in the command line itself. run_shell echoes the command
    # in its output; if the marker were literal there, a command that is KILLED or times out before
    # printf runs would leave the marker only in that echo, and the parser below would mis-read the
    # cwd and corrupt the persistent terminal. Built this way, the marker appears ONLY in printf's
    # real output, so cwd tracking survives kills/timeouts.
    wrapped = f'cd "{cwd}" || exit 1; {command}; printf "\\n%s%s" "__SPIDER" "_KCWD__$PWD"'
    out = await run_shell(wrapped, timeout=int(args.get("timeout", 300)))
    if marker in out:
        body, _, new_cwd = out.rpartition(marker)
        new_cwd = new_cwd.strip()
        # Only accept a plausible absolute path (defends against any stray marker in output).
        if new_cwd and new_cwd.startswith("/") and "\n" not in new_cwd and " " not in new_cwd:
            _CWD[term_id] = new_cwd
        out = body.rstrip()
    return f"[kali terminal {term_id} | cwd={_CWD[term_id]}]\n{out}"


@tool(
    name="write_file",
    category="filesystem",
    requires=[],
    description="Write a text file on the Kali host (e.g. a target list, an exploit script, a "
                "custom wordlist). Overwrites. Relative paths resolve under the Kali work dir.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative paths under the Kali work dir)."},
            "content": {"type": "string", "description": "File contents."},
        },
        "required": ["path", "content"],
    },
)
async def write_file(args: dict) -> str:
    path = require_arg(args, "path")
    if not os.path.isabs(path):
        path = os.path.join(_BASE, path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    content = args.get("content", "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content)} chars to {path}"


@tool(
    name="read_file",
    category="filesystem",
    requires=[],
    description="Read a text file from the Kali host (e.g. a tool's output file you redirected). "
                "Relative paths resolve under the Kali work dir.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path to read."}},
        "required": ["path"],
    },
)
async def read_file(args: dict) -> str:
    path = require_arg(args, "path")
    if not os.path.isabs(path):
        path = os.path.join(_BASE, path)
    if not os.path.exists(path):
        raise ValueError(f"file not found: {path}")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return clip(f.read())
