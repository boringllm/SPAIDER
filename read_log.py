#!/usr/bin/env python3
"""View a SPAIDER session event log as a chat-style web UI (or a terminal timeline).

Every session records its full live event stream to
`workspaces/<session_id>/logs/events.jsonl` — one JSON event per line (messages, the
model's thinking, every tool call + its full result, narration, skills, memory, the plan,
plan-approval sign-offs, operator interjections, intensity changes, findings, approvals,
cost, errors). This tool renders that log.

DEFAULT (web UI): builds a self-contained HTML "chatbot" view of everything the agents
said and did, and opens it in your browser. A **Chat / Raw** toggle switches between the
filtered chat and the whole LLM conversation (reasoning + answer + exact tool calls +
stop reason + tool outputs), organized per agent:

    python read_log.py s_5f6e26d2                 # by session id -> opens the UI
    python read_log.py path/to/events.jsonl       # by file
    python read_log.py s_x --no-open --out ui.html # just write the HTML, don't open

RAW (console): dump the full raw LLM conversation to the terminal (great for grep/diffing):

    python read_log.py s_x --raw
    python read_log.py s_x --raw --agent recon#1

LIVE (web server): re-reads the log and auto-refreshes while a session is still running:

    python read_log.py s_x --serve                # http://127.0.0.1:8770 , live updates

LIST: show the sessions that have a log on disk (id, last activity, event count):

    python read_log.py --list

TERMINAL (the old view): a color-coded timeline + summary in the console:

    python read_log.py s_x --text
    python read_log.py s_x --text --agent recon#1
    python read_log.py s_x --text --type tool.call,error --grep sqlmap
    python read_log.py s_x --text --tokens --tail 50 --summary-only --no-color
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# Log loading / path resolution
# --------------------------------------------------------------------------- #
def _workspace_roots() -> list[Path]:
    """Candidate workspace roots to search for a session's log. Defaults to
    ``./workspaces`` next to this script, plus any custom ``workspace_root`` from
    ``config/config.json`` (so a relocated workspace folder still resolves)."""
    base = Path(__file__).resolve().parent
    roots = [base / "workspaces"]
    cfg = base / "config" / "config.json"
    if cfg.is_file():
        try:
            wr = json.loads(cfg.read_text(encoding="utf-8")).get("workspace_root")
            if wr:
                roots.insert(0, Path(wr))
        except Exception:  # noqa: BLE001 — config is best-effort
            pass
    # de-dup while preserving order
    seen, out = set(), []
    for r in roots:
        key = str(r.resolve()) if r.exists() else str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def resolve_log_path(arg: str) -> Path:
    """Accept a session id, a workspace dir, or a direct path to events.jsonl."""
    p = Path(arg)
    if p.is_file():
        return p
    if (p / "logs" / "events.jsonl").is_file():
        return p / "logs" / "events.jsonl"
    tried = []
    for root in _workspace_roots():
        cand = root / arg / "logs" / "events.jsonl"
        tried.append(cand)
        if cand.is_file():
            return cand
    raise SystemExit(
        f"Log not found for '{arg}'. Looked for a file/workspace dir, or:\n  "
        + "\n  ".join(str(t) for t in tried)
        + "\nRun `python read_log.py --list` to see available sessions."
    )


def list_sessions() -> int:
    """Print every session that has an events.jsonl, newest first."""
    rows: list[tuple[float, str, Path, int]] = []
    for root in _workspace_roots():
        if not root.is_dir():
            continue
        for log in root.glob("*/logs/events.jsonl"):
            sid = log.parent.parent.name
            try:
                mtime = log.stat().st_mtime
                n = sum(1 for _ in log.open(encoding="utf-8"))
            except OSError:
                continue
            rows.append((mtime, sid, log, n))
    if not rows:
        print("No session logs found under:", ", ".join(str(r) for r in _workspace_roots()))
        return 0
    rows.sort(reverse=True)
    print(f"{'SESSION':<14} {'LAST ACTIVITY':<20} {'EVENTS':>7}  LOG")
    for mtime, sid, log, n in rows:
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{sid:<14} {ts:<20} {n:>7}  {log}")
    print(f"\nOpen one with:  python read_log.py {rows[0][1]}")
    return 0


def load_events(path: Path) -> list[dict]:
    """Read events.jsonl into a list of event dicts (skipping any malformed lines)."""
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def session_id_of(path: Path) -> str:
    """Best-effort session id from the workspace path (…/workspaces/<sid>/logs/…)."""
    parts = path.resolve().parts
    if "logs" in parts:
        i = parts.index("logs")
        if i >= 1:
            return parts[i - 1]
    return path.stem


# --------------------------------------------------------------------------- #
# Web UI (self-contained HTML, no external assets / no dependencies)
# --------------------------------------------------------------------------- #
def build_html(events: list[dict] | None, session_id: str, *, live: bool) -> str:
    """Render the chat UI page. In static mode the events are embedded directly; in live
    (`--serve`) mode the page starts empty and polls /api/events for new lines."""
    boot = {
        "events": events if events is not None else [],
        "live": live,
        "session": session_id,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Embed safely inside a <script> tag (escape the only sequence that could close it).
    boot_json = json.dumps(boot, ensure_ascii=False).replace("</", "<\\/")
    return _PAGE_TEMPLATE.replace("/*__BOOT__*/", "window.__BOOT__ = " + boot_json + ";")


def write_and_open(path: Path, html: str, *, open_browser: bool) -> None:
    """Write the static HTML file and (optionally) open it in the default browser."""
    path.write_text(html, encoding="utf-8")
    print(f"Wrote UI -> {path}")
    if open_browser:
        webbrowser.open(path.resolve().as_uri())
        print("Opened in your browser.")


def _bindable(host: str, port: int) -> bool:
    """True if we can bind host:port (Windows reserves some dynamic ports -> WinError 10013)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def serve(log_path: Path, session_id: str, host: str, port: int, open_browser: bool) -> None:
    """Run a tiny stdlib HTTP server that serves the UI and streams new log lines so the
    page live-updates while the session is still running. `/` returns the page; the page
    polls `/api/events?offset=N` which returns events from line N onward. If the requested
    port is taken/reserved, the next free port is used."""
    import http.server
    import socketserver
    import threading
    import urllib.parse

    if not _bindable(host, port):
        for cand in range(port + 1, port + 40):
            if _bindable(host, cand):
                print(f"port {port} unavailable; using {cand} instead.")
                port = cand
                break
        else:
            raise SystemExit(f"Could not find a free port near {port}.")

    page = build_html(None, session_id, live=True).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/events":
                qs = urllib.parse.parse_qs(parsed.query)
                offset = int((qs.get("offset", ["0"])[0]) or 0)
                evs = load_events(log_path)
                body = json.dumps({"events": evs[offset:], "next": len(evs)}).encode("utf-8")
                self._send(body, "application/json")
                return
            self.send_error(404)

        def log_message(self, *args) -> None:  # silence per-request console spam
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((host, port), Handler) as httpd:
        url = f"http://{host}:{port}"
        print(f"SPAIDER log UI (live) serving at {url}  —  Ctrl+C to stop")
        if open_browser:
            import time
            threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)), daemon=True).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


# --------------------------------------------------------------------------- #
# Terminal renderer (the original view, now behind --text)
# --------------------------------------------------------------------------- #
class C:
    RESET = "\033[0m"; DIM = "\033[2m"; BOLD = "\033[1m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; MAGENTA = "\033[35m"; CYAN = "\033[36m"; GREY = "\033[90m"


_USE_COLOR = True


def col(text: str, *codes: str) -> str:
    if not _USE_COLOR or not codes:
        return text
    return "".join(codes) + text + C.RESET


# Event type -> (label, color) for the terminal timeline.
EVENTS = {
    "session.status": ("SESSION", C.CYAN),
    "plan.update": ("PLAN", C.BLUE),
    "plan.step": ("PLAN·STEP", C.BLUE),
    "plan.approval_request": ("PLAN?", C.MAGENTA),
    "plan.approval_resolved": ("PLAN✓", C.MAGENTA),
    "operator.interjection": ("OPERATOR", C.CYAN),
    "intensity.changed": ("INTENSITY", C.YELLOW),
    "approval.mode_changed": ("APPROVAL-MODE", C.YELLOW),
    "agent.created": ("SPAWN", C.CYAN),
    "agent.status": ("STATUS", C.GREY),
    "agent.message": ("MSG", C.RESET),
    "agent.raw": ("RAW", C.MAGENTA),
    "agent.thinking": ("THINK", C.MAGENTA),
    "agent.narration": ("NARRATE", C.CYAN),
    "agent.skill_loaded": ("SKILL", C.GREEN),
    "agent.memory_loaded": ("MEMORY", C.YELLOW),
    "tool.call": ("TOOL→", C.YELLOW),
    "tool.result": ("TOOL✓", C.GREY),
    "approval.request": ("APPROVAL?", C.MAGENTA),
    "approval.resolved": ("APPROVAL", C.MAGENTA),
    "user.request": ("ASK-USER", C.MAGENTA),
    "user.request_resolved": ("ASK-USER✓", C.MAGENTA),
    "finding.stored": ("FINDING", C.MAGENTA),
    "cost.update": ("COST", C.GREY),
    "context.compacted": ("COMPACT", C.YELLOW),
    "agent.token": ("token", C.GREY),
    "log": ("LOG", C.GREY),
    "error": ("ERROR", C.RED),
}


def _clip(s: str, n: int = 400) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + " …"


def _content_text(content) -> str:
    """Flatten an agent.message content (string or block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            t = b.get("type")
            if t == "text":
                out.append(b.get("text", ""))
            elif t == "tool_use":
                out.append(f"[call {b.get('name')}({json.dumps(b.get('input', {}))})]")
            elif t == "tool_result":
                out.append(f"[result {_clip(b.get('content', ''), 200)}]")
        return " ".join(out)
    return json.dumps(content)


def describe(ev: dict) -> str:
    """Human-readable one-line description of an event's payload (terminal mode)."""
    t = ev["type"]
    p = ev.get("payload", {}) or {}
    if t == "agent.created":
        return f"{p.get('role')} ({p.get('name')}) — {_clip(p.get('task', ''), 160)}"
    if t == "agent.status":
        return p.get("status", "")
    if t == "session.status":
        return p.get("status", "")
    if t == "plan.update":
        steps = (p.get("plan", {}) or {}).get("steps", [])
        return f"{len(steps)} steps: " + "; ".join(s.get("text", "") for s in steps[:8])
    if t == "plan.step":
        return f"step {p.get('index')} -> {p.get('status')}"
    if t == "plan.approval_request":
        steps = (p.get("plan", {}) or {}).get("steps", [])
        return f"awaiting operator sign-off ({p.get('mode', '?')}) — {len(steps)} steps"
    if t == "plan.approval_resolved":
        fb = p.get("feedback")
        return f"{p.get('decision', '?')}" + (f" — {_clip(fb, 200)}" if fb else "")
    if t == "operator.interjection":
        return _clip(p.get("message", ""), 400)
    if t == "intensity.changed":
        return f"intensity -> {p.get('intensity')}"
    if t == "approval.mode_changed":
        m = p.get("approval_mode")
        return "command validation BYPASSED (auto)" if m == "auto" else "command validation re-enabled (manual)"
    if t == "agent.message":
        return f"[{p.get('role')}] {_clip(_content_text(p.get('content')), 500)}"
    if t == "agent.raw":
        calls = ", ".join(c.get("name", "?") for c in (p.get("tool_calls") or []))
        bits = []
        if p.get("thinking"):
            bits.append(f"think {len(p['thinking'])}c")
        if p.get("text"):
            bits.append(_clip(p["text"], 240))
        if calls:
            bits.append(f"→ {calls}")
        return f"[{p.get('stop_reason', '?')}] " + " | ".join(bits)
    if t == "agent.thinking":
        return _clip(p.get("text", ""), 500)
    if t == "agent.narration":
        return _clip(p.get("message", ""), 500)
    if t == "agent.skill_loaded":
        return f"{p.get('title') or p.get('name')}" + (" (at start)" if p.get("auto") else " (on demand)")
    if t == "agent.memory_loaded":
        return "loaded: " + ", ".join(p.get("files", [])) if p.get("files") else "shared memory"
    if t == "tool.call":
        return f"{p.get('tool')}({_clip(json.dumps(p.get('input', {})), 300)})"
    if t == "tool.result":
        flag = "ERROR " if p.get("is_error") else ""
        return f"{p.get('tool')}: {flag}{_clip(p.get('result', ''), 400)}"
    if t == "finding.stored":
        f = p.get("finding", {}) or {}
        d = f.get("data", {}) or {}
        return f"{f.get('title')} [{f.get('severity')}/{f.get('status')}] @ {d.get('location', '?')}"
    if t == "approval.request":
        return f"{p.get('agent_name')} wants to run {p.get('tool')}: {_clip(json.dumps(p.get('input', {})), 200)}"
    if t == "approval.resolved":
        return "approved" if p.get("approved") else f"denied ({p.get('reason', '')})"
    if t in ("user.request",):
        return _clip(p.get("message", ""), 300)
    if t == "cost.update":
        c = p.get("cost", {}) or {}
        return f"total ${c.get('total_usd', 0):.4f}  in={c.get('input_tokens', 0)} out={c.get('output_tokens', 0)}"
    if t == "context.compacted":
        return f"{p.get('name')} compacted (summary {p.get('summary_chars')} chars)"
    if t == "agent.token":
        return _clip(p.get("text", ""), 200)
    if t == "log":
        return f"[{p.get('level')}] {p.get('message', '')}"
    if t == "error":
        return p.get("message", "")
    return _clip(json.dumps(p), 300)


def run_text(events: list[dict], args, path: Path) -> int:
    """The original console timeline + summary (now invoked with --text)."""
    global _USE_COLOR
    _USE_COLOR = (not args.no_color) and sys.stdout.isatty()
    types = set(args.type.split(",")) if args.type else None
    grep = args.grep.lower() if args.grep else None

    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    per_agent: dict[str, int] = {}
    findings: list[str] = []
    errors: list[str] = []
    last_cost = None
    rendered: list[str] = []

    for ev in events:
        t = ev.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
        p = ev.get("payload", {}) or {}
        if t == "agent.created":
            names[ev.get("agent_id")] = f"{p.get('name')} ({p.get('role')})"
        if t == "finding.stored":
            findings.append(describe(ev))
        if t == "error":
            errors.append(describe(ev))
        if t == "cost.update":
            last_cost = p.get("cost", {})

        if t == "agent.token" and not args.tokens:
            continue
        aid = ev.get("agent_id")
        who = names.get(aid, aid or "session")
        if args.agent and args.agent not in who:
            continue
        if types and t not in types:
            continue
        desc = describe(ev)
        if grep and grep not in desc.lower():
            continue
        per_agent[who] = per_agent.get(who, 0) + 1

        label, color = EVENTS.get(t, (t.upper(), C.RESET))
        ts = datetime.fromtimestamp(ev.get("ts", 0)).strftime("%H:%M:%S")
        rendered.append(f"{col(ts, C.GREY)} {col(label.ljust(10), color, C.BOLD)} {col(who, C.BOLD)}  {desc}")

    if not args.summary_only:
        shown = rendered[-args.tail:] if args.tail else rendered
        for ln in shown:
            print(ln)
        print()

    print(col("── Summary " + "─" * 50, C.BOLD))
    print(f"  log: {path}")
    print(f"  events: {sum(counts.values())} total")
    for t in sorted(counts, key=lambda k: -counts[k]):
        label = EVENTS.get(t, (t, ""))[0]
        print(f"    {counts[t]:>5}  {label}  ({t})")
    if per_agent:
        print(col("  by agent:", C.BOLD))
        for who in sorted(per_agent, key=lambda k: -per_agent[k]):
            print(f"    {per_agent[who]:>5}  {who}")
    if findings:
        print(col(f"  findings ({len(findings)}):", C.MAGENTA))
        for fdesc in findings:
            print(f"    • {fdesc}")
    if last_cost:
        print(col("  final cost:", C.BOLD)
              + f" ${last_cost.get('total_usd', 0):.4f}"
              + f"  (in {last_cost.get('input_tokens', 0)}, out {last_cost.get('output_tokens', 0)} tokens)")
    if errors:
        print(col(f"  errors ({len(errors)}):", C.RED))
        for e in errors[:10]:
            print(f"    • {e}")
    return 0


def run_raw_text(events: list[dict], args, path: Path) -> int:
    """Dump the whole RAW LLM conversation to the console (per --raw): user/task inputs, each
    assistant turn (reasoning + answer + exact tool calls with full JSON) and its tool results,
    interjections and errors — in order, optionally filtered to one agent with --agent."""
    global _USE_COLOR
    _USE_COLOR = (not args.no_color) and sys.stdout.isatty()
    names: dict[str, str] = {}
    for ev in events:
        if ev.get("type") == "agent.created":
            p = ev.get("payload", {}) or {}
            names[ev.get("agent_id")] = f"{p.get('name')} ({p.get('role')})"

    def who_of(aid):
        return names.get(aid, aid or "session")

    shown = 0
    for ev in events:
        t = ev.get("type")
        aid = ev.get("agent_id")
        who = who_of(aid)
        if args.agent and args.agent not in who:
            continue
        p = ev.get("payload", {}) or {}
        if t == "agent.created":
            print(col(f"\n===== spawned {who} =====", C.CYAN, C.BOLD))
            print(f"task: {p.get('task', '')}")
            shown += 1
        elif t == "agent.message" and p.get("role") == "user":
            print(col(f"\n--- {who} · USER ---", C.BLUE, C.BOLD))
            print(_content_text(p.get("content")))
            shown += 1
        elif t == "operator.interjection":
            print(col(f"\n--- OPERATOR -> {who} ---", C.CYAN, C.BOLD))
            print(p.get("message", ""))
            shown += 1
        elif t == "agent.raw":
            print(col(f"\n--- {who} · ASSISTANT  [stop={p.get('stop_reason', '?')}] ---", C.MAGENTA, C.BOLD))
            if p.get("thinking"):
                print(col("[reasoning]", C.MAGENTA))
                print(p["thinking"])
            if p.get("text"):
                print(p["text"])
            for tc in p.get("tool_calls") or []:
                print(col(f"[tool_call] {tc.get('name')}", C.YELLOW))
                print(json.dumps(tc.get("input", {}), indent=2, ensure_ascii=False))
            shown += 1
        elif t == "tool.result":
            flag = "ERROR " if p.get("is_error") else ""
            print(col(f"[tool_result {p.get('tool')}] {flag}", C.GREY))
            print(_clip(p.get("result", ""), 6000))
            shown += 1
        elif t == "error":
            print(col(f"\n!!! {who} · ERROR: {p.get('message', '')}", C.RED, C.BOLD))
            shown += 1
    if not shown:
        print("No raw conversation found in this log "
              "(agent.raw is recorded for sessions run after the raw-logging update).")
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    # The log and labels contain Unicode; force UTF-8 so Windows cp1252 consoles
    # don't raise UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(
        description="View a SPAIDER session log as a chat-style web UI (default) or a terminal timeline (--text)."
    )
    ap.add_argument("target", nargs="?", help="session id, a workspace dir, or a path to events.jsonl")
    ap.add_argument("--list", action="store_true", help="list sessions that have a log on disk and exit")
    # web UI
    ap.add_argument("--serve", action="store_true", help="run a live web server that auto-refreshes while the session runs")
    ap.add_argument("--host", default="127.0.0.1", help="host for --serve (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8770, help="port for --serve (default 8770)")
    ap.add_argument("--out", help="where to write the static HTML (default: chat.html next to the log)")
    ap.add_argument("--no-open", action="store_true", help="build the UI but do not open a browser")
    # terminal mode
    ap.add_argument("--text", action="store_true", help="print the color-coded console timeline instead of the web UI")
    ap.add_argument("--agent", help="(text) only events from this agent name")
    ap.add_argument("--type", help="(text) comma-separated event types to include")
    ap.add_argument("--grep", help="(text) only lines whose description contains this text")
    ap.add_argument("--tokens", action="store_true", help="(text) include noisy agent.token deltas")
    ap.add_argument("--tail", type=int, default=0, help="(text) show only the last N matching events")
    ap.add_argument("--summary-only", action="store_true", help="(text) print only the summary")
    ap.add_argument("--no-color", action="store_true", help="(text) disable ANSI colors")
    ap.add_argument("--raw", action="store_true",
                    help="dump the FULL raw LLM conversation to the console (reasoning + answer + "
                         "exact tool calls + tool results), per turn. Combine with --agent to focus.")
    args = ap.parse_args()

    if args.list:
        return list_sessions()
    if not args.target:
        ap.error("a session id / workspace dir / events.jsonl path is required (or use --list)")

    path = resolve_log_path(args.target)
    sid = session_id_of(path)

    if args.raw:
        return run_raw_text(load_events(path), args, path)

    # Backward-compat / convenience: any text-only filter flag implies the terminal view.
    if any([args.agent, args.type, args.grep, args.tail, args.summary_only, args.no_color]):
        args.text = True

    if args.text:
        return run_text(load_events(path), args, path)

    if args.serve:
        serve(path, sid, args.host, args.port, open_browser=not args.no_open)
        return 0

    events = load_events(path)
    html = build_html(events, sid, live=False)
    out = Path(args.out) if args.out else path.parent / "chat.html"
    write_and_open(out, html, open_browser=not args.no_open)
    print(f"Tip: for a live view while a session runs, use:  python read_log.py {args.target} --serve")
    return 0


# --------------------------------------------------------------------------- #
# The page template. Self-contained: HTML + CSS + JS, no external requests.
# `/*__BOOT__*/` is replaced with `window.__BOOT__ = {...};` by build_html().
# To restyle the UI, edit the <style> block; to change how an event renders,
# edit the matching branch in the render() function below.
# --------------------------------------------------------------------------- #
_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPAIDER — session chat</title>
<style>
  :root{
    --bg:#0d1117; --panel:#11161d; --panel2:#161b22; --border:#222b36;
    --fg:#e6edf3; --muted:#8b949e; --accent:#2f81f7;
    --tool:#d29922; --result:#3fb950; --err:#f85149; --think:#a371f7;
    --narr:#1f6feb; --finding:#db61a2; --skill:#3fb950; --memory:#d29922;
    --operator:#39c5cf;
  }
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
  header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--border);padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  header h1{font-size:15px;margin:0;font-weight:600}
  header .sub{color:var(--muted);font-size:12px}
  .stats{display:flex;gap:14px;margin-left:auto;flex-wrap:wrap}
  .stat{font-size:12px;color:var(--muted)} .stat b{color:var(--fg);font-size:13px}
  .live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--result);margin-right:5px;animation:pulse 1.4s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .wrap{display:flex;min-height:calc(100vh - 52px)}
  aside{width:260px;flex:0 0 260px;border-right:1px solid var(--border);background:var(--panel);padding:10px;overflow:auto;position:sticky;top:52px;height:calc(100vh - 52px)}
  aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:12px 4px 6px}
  .agent{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:7px;cursor:pointer;font-size:13px}
  .agent:hover{background:var(--panel2)} .agent.active{background:#1c2733;outline:1px solid var(--accent)}
  .av{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;flex:0 0 24px}
  .agent .meta{min-width:0} .agent .nm{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .agent .rl{color:var(--muted);font-size:11px}
  .agent .badge{margin-left:auto;font-size:10px;color:var(--muted)}
  main{flex:1;min-width:0;padding:18px 22px;overflow:auto}
  .controls{display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
  .controls input[type=search]{flex:1;min-width:180px;background:var(--panel2);border:1px solid var(--border);color:var(--fg);padding:7px 10px;border-radius:8px}
  .controls label{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
  .row{display:flex;gap:10px;margin:14px 0;align-items:flex-start}
  .row .av{margin-top:2px}
  .bubble{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:9px 12px;max-width:920px;min-width:0}
  .head{display:flex;gap:8px;align-items:baseline;margin-bottom:2px}
  .head .nm{font-weight:600} .head .rl{color:var(--muted);font-size:11px} .head .ts{color:var(--muted);font-size:11px;margin-left:auto}
  .text{white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere}
  .narr{border-left:3px solid var(--narr);background:#11203a}
  .operator{border-left:3px solid var(--operator);background:#0c2630}
  .think{border-left:3px solid var(--think);background:#1a1430;color:#d7c9f5}
  .think .text{font-style:italic;opacity:.92}
  details.tool{border:1px solid var(--border);border-left:3px solid var(--tool);border-radius:8px;background:var(--panel2);max-width:920px;min-width:0;flex:1}
  details.tool>summary{cursor:pointer;padding:8px 12px;list-style:none;display:flex;gap:8px;align-items:center}
  details.tool>summary::-webkit-details-marker{display:none}
  .tool .tname{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--tool);font-weight:600;white-space:nowrap}
  .tool.err{border-left-color:var(--err)} .tool.err .tname{color:var(--err)}
  .tool .ok{color:var(--result);font-size:11px} .tool .bad{color:var(--err);font-size:11px}
  .tool pre{margin:0;padding:10px 12px;border-top:1px solid var(--border);overflow:auto;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px;max-height:520px}
  .tool .args{color:var(--muted);font-family:ui-monospace,monospace;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
  .chip{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--muted);background:var(--panel2);border:1px solid var(--border);border-radius:20px;padding:4px 11px}
  .chip.skill{border-color:#1d3b27;color:var(--skill)} .chip.memory{border-color:#3a3014;color:var(--memory)}
  .chip.compact{border-color:#3a3014;color:var(--memory)} .chip.intensity{border-color:#3a3014;color:var(--memory)}
  .finding{border:1px solid var(--border);border-left:3px solid var(--finding);border-radius:8px;padding:9px 12px;background:var(--panel2);max-width:920px}
  .finding .ttl{font-weight:600} .finding .sev{font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:1px 7px;border-radius:10px;margin-left:6px}
  .sev.critical,.sev.high{background:#3d1418;color:#ff7b72} .sev.medium{background:#3a2d12;color:#e3b341}
  .sev.low,.sev.info{background:#16233a;color:#79c0ff}
  .approval{border:1px solid var(--border);border-left:3px solid var(--think);border-radius:8px;padding:9px 12px;background:var(--panel2);max-width:920px}
  .err-row{border:1px solid #5a1d1d;border-left:3px solid var(--err);border-radius:8px;padding:9px 12px;background:#2a1416;color:#ffb4ad;max-width:920px}
  .divider{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin:22px 0 8px}
  .divider::before,.divider::after{content:"";height:1px;background:var(--border);flex:1}
  .plan{border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;padding:9px 12px;background:var(--panel2);max-width:920px}
  .plan.pending{border-left-color:var(--tool)}
  .plan ol{margin:6px 0 0;padding-left:22px} .plan li{margin:2px 0}
  .plan .done{color:var(--result)} .plan .failed{color:var(--err)} .plan .in_progress{color:var(--tool)}
  .empty{color:var(--muted);text-align:center;padding:60px 0}
  code{font-family:ui-monospace,monospace}
  /* Chat / Raw mode toggle + the raw LLM conversation view */
  .modes{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;flex:0 0 auto}
  .modes .mode{background:var(--panel2);border:none;color:var(--muted);padding:7px 16px;cursor:pointer;font-size:13px}
  .modes .mode+.mode{border-left:1px solid var(--border)}
  .modes .mode.active{background:var(--accent);color:#06121f;font-weight:600}
  body.rawmode .chatonly{display:none}
  .raw-turn{border:1px solid var(--border);border-left:3px solid var(--think);border-radius:8px;background:var(--panel2);max-width:920px;min-width:0;padding:9px 12px}
  .raw-stopbadge{font-size:10px;color:var(--muted);margin-bottom:4px}
  .raw-stopbadge b{color:var(--accent)}
  .raw-turn details{margin:2px 0 6px}
  .raw-turn details>summary{cursor:pointer;color:var(--think);font-style:italic}
  .raw-tool{margin-top:6px}
  .raw-tool b{color:var(--tool);font-family:ui-monospace,monospace}
  .raw-tool pre,.raw-turn details pre{margin:4px 0 0;padding:8px 10px;background:#0a0e14;border:1px solid var(--border);border-radius:6px;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,monospace;font-size:12px;max-height:460px;overflow:auto}
  .user-msg{border-left:3px solid var(--narr);background:#11203a}
</style>
</head>
<body>
<header>
  <div>
    <h1>🕷 SPAIDER session <span id="sid"></span></h1>
    <div class="sub" id="sub"></div>
  </div>
  <div class="stats" id="stats"></div>
</header>
<div class="wrap">
  <aside>
    <h2>Agents</h2>
    <div id="agentlist"></div>
  </aside>
  <main>
    <div class="controls">
      <span class="modes" title="Chat = filtered & readable · Raw = the whole LLM conversation (reasoning, answer, exact tool calls)">
        <button id="mChat" class="mode active" data-m="chat">💬 Chat</button>
        <button id="mRaw" class="mode" data-m="raw">⚙ Raw</button>
      </span>
      <input type="search" id="q" placeholder="Search messages, tools, findings…">
      <label class="chatonly"><input type="checkbox" id="cbThink" checked> thinking</label>
      <label class="chatonly"><input type="checkbox" id="cbTokens"> token deltas</label>
      <label class="chatonly"><input type="checkbox" id="cbLogs"> logs/status/cost</label>
    </div>
    <div id="feed"><div class="empty">Loading…</div></div>
  </main>
</div>
<script>
/*__BOOT__*/
(function(){
  const BOOT = window.__BOOT__ || {events:[],live:false};
  const PALETTE = ["#2f81f7","#3fb950","#d29922","#db61a2","#a371f7","#f85149","#39c5cf","#e3b341","#bc8cff","#56d364"];
  let events = [];
  const agents = {};        // agent_id -> {name,role,parent,model,task,tools,status,color}
  let lastCost = null, errorCount = 0, findingCount = 0;
  let activeAgent = null;   // sidebar filter (null = all)
  let mode = 'chat';        // 'chat' (filtered) | 'raw' (whole LLM conversation)
  const ui = {
    q: document.getElementById('q'),
    think: document.getElementById('cbThink'),
    tokens: document.getElementById('cbTokens'),
    logs: document.getElementById('cbLogs'),
    feed: document.getElementById('feed'),
    agentlist: document.getElementById('agentlist'),
    stats: document.getElementById('stats'),
    sid: document.getElementById('sid'),
    sub: document.getElementById('sub'),
    mChat: document.getElementById('mChat'),
    mRaw: document.getElementById('mRaw'),
  };
  ui.sid.textContent = BOOT.session || '';
  ui.sub.textContent = BOOT.live ? 'live • auto-refreshing' : ('static snapshot • generated ' + (BOOT.generated||''));

  function esc(s){ return String(s==null?'':s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
  function colorFor(id){ let h=0; const s=String(id); for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0; return PALETTE[h%PALETTE.length]; }
  function initials(name){ const m=String(name||'?').replace('#',' ').trim().split(/[ _]/).filter(Boolean); return ((m[0]||'?')[0]+(m[1]?m[1][0]:'')).toUpperCase(); }
  function tstr(ev){ return new Date((ev.ts||0)*1000).toLocaleTimeString(); }
  function pretty(v){ try{ return typeof v==='string'? v : JSON.stringify(v,null,2);}catch(e){return String(v);} }
  function oneline(s){ s=String(s||'').replace(/\s+/g,' ').trim(); return s.length>140? s.slice(0,140)+' …':s; }

  // Build the agents index + running totals as each event arrives.
  function ingest(ev){
    events.push(ev);
    const p = ev.payload||{}, t = ev.type, aid = ev.agent_id;
    if(t==='agent.created'){
      agents[aid] = {name:p.name, role:p.role, parent:p.parent, model:p.model, task:p.task,
                     tools:p.tools||[], status:'running', color:colorFor(aid)};
    }
    if(t==='agent.status' && agents[aid]) agents[aid].status = p.status;
    if(t==='cost.update') lastCost = p.cost;
    if(t==='error') errorCount++;
    if(t==='finding.stored') findingCount++;
  }

  function agentName(aid){ return agents[aid] ? agents[aid].name : (aid||'session'); }
  function agentRole(aid){ return agents[aid] ? agents[aid].role : ''; }
  function depthOf(aid){ let d=0,a=agents[aid],seen={}; while(a && a.parent && !seen[a.parent]){ seen[a.parent]=1; d++; a=agents[a.parent]; } return d; }
  function avatar(aid){
    const c = agents[aid]? agents[aid].color : '#6e7681';
    return '<div class="av" style="background:'+c+'">'+esc(initials(agentName(aid)))+'</div>';
  }
  function headLine(ev){
    const aid=ev.agent_id;
    return '<div class="head"><span class="nm">'+esc(agentName(aid))+'</span>'+
           '<span class="rl">'+esc(agentRole(aid))+'</span>'+
           '<span class="ts">'+esc(tstr(ev))+'</span></div>';
  }

  // Render the whole feed from `events`, applying the current filters.
  // tool.result is paired to its preceding tool.call (FIFO per agent).
  function render(){
    if(mode==='raw'){ renderRaw(); return; }
    const q = ui.q.value.trim().toLowerCase();
    const showThink = ui.think.checked, showTokens = ui.tokens.checked, showLogs = ui.logs.checked;
    const pending = {};  // agent_id -> indexes of open tool.call entries in `out`
    const out = [];
    const match = (s)=> !q || String(s||'').toLowerCase().includes(q);

    for(const ev of events){
      const t=ev.type, p=ev.payload||{}, aid=ev.agent_id;
      if(activeAgent && aid!==activeAgent) continue;
      if(t==='agent.raw') continue;  // raw turns are shown only in Raw mode
      if(t==='agent.token' && !showTokens) continue;
      if(t==='agent.thinking' && !showThink) continue;
      if((t==='log'||t==='agent.status'||t==='session.status'||t==='cost.update'||t==='plan.step') && !showLogs) continue;

      if(t==='agent.created'){
        const a=agents[aid]||{};
        if(!match((a.name||'')+' '+(a.role||'')+' '+(a.task||''))) continue;
        out.push('<div class="divider">spawned '+esc(a.name)+' · '+esc(a.role)+(a.model?' · '+esc(a.model):'')+'</div>'+
          '<div class="row">'+avatar(aid)+'<div class="bubble">'+headLine(ev)+
          '<div class="text"><b>Task:</b> '+esc(a.task||'')+'</div>'+
          (a.tools&&a.tools.length? '<div class="text" style="color:var(--muted);margin-top:4px"><b>Tools:</b> '+esc(a.tools.join(', '))+'</div>':'')+
          '</div></div>');
        continue;
      }
      if(t==='agent.message'){
        const content=p.content, txt = typeof content==='string'? content : pretty(content);
        if(!txt.trim() || !match(txt)) continue;
        const dim = p.role==='user' ? ' style="opacity:.7"' : '';
        out.push('<div class="row"'+dim+'>'+avatar(aid)+'<div class="bubble">'+headLine(ev)+
          '<div class="text">'+esc(txt)+'</div></div></div>');
        continue;
      }
      if(t==='agent.thinking'){
        if(!match(p.text)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="bubble think">'+headLine(ev)+
          '<div class="text">💭 '+esc(p.text)+'</div></div></div>');
        continue;
      }
      if(t==='agent.narration'){
        if(!match(p.message)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="bubble narr">'+headLine(ev)+
          '<div class="text">📣 '+esc(p.message)+'</div></div></div>');
        continue;
      }
      if(t==='operator.interjection'){
        if(!match(p.message)) continue;
        out.push('<div class="row"><div class="av" style="background:var(--operator)">🧭</div>'+
          '<div class="bubble operator"><div class="head"><span class="nm">operator</span>'+
          '<span class="ts" style="margin-left:auto">'+esc(tstr(ev))+'</span></div>'+
          '<div class="text">🧭 '+esc(p.message)+'</div></div></div>');
        continue;
      }
      if(t==='intensity.changed'){
        out.push('<div class="row"><span class="chip intensity">⚡ tool intensity → <b style="margin-left:4px">'+esc(p.intensity)+'</b></span></div>');
        continue;
      }
      if(t==='approval.mode_changed'){
        const auto=p.approval_mode==='auto';
        out.push('<div class="row"><span class="chip intensity">'+(auto?'🔓 command validation BYPASSED (auto)':'🔒 command validation re-enabled (manual)')+'</span></div>');
        continue;
      }
      if(t==='tool.call'){
        const args=pretty(p.input);
        if(!match(p.tool+' '+args)) continue;
        out.push('<div class="row">'+avatar(aid)+'<details class="tool">'+
          '<summary><span class="tname">🔧 '+esc(p.tool)+'</span><span class="args">'+esc(oneline(args))+'</span>'+
          '<span class="ts" style="margin-left:auto">'+esc(tstr(ev))+'</span></summary>'+
          '<pre>'+esc(args)+'</pre><div class="result-slot"></div></details></div>');
        (pending[aid]=pending[aid]||[]).push(out.length-1);
        continue;
      }
      if(t==='tool.result'){
        const res=p.result||'';
        const k=(pending[aid]&&pending[aid].length)? pending[aid].shift() : null;
        const cls=p.is_error? ' err':'';
        const badge=p.is_error? '<span class="bad">error</span>':'<span class="ok">ok</span>';
        const resHtml='<pre>'+badge+'\n'+esc(res)+'</pre>';
        if(k!=null){
          out[k]=out[k].replace('class="tool"','class="tool'+cls+'"')
                       .replace('<div class="result-slot"></div>', resHtml);
        }else{
          if(!match(p.tool+' '+res)) continue;
          out.push('<div class="row">'+avatar(aid)+'<details class="tool'+cls+'">'+
            '<summary><span class="tname">⮑ '+esc(p.tool)+' result</span>'+badge+
            '<span class="ts" style="margin-left:auto">'+esc(tstr(ev))+'</span></summary>'+resHtml+'</details></div>');
        }
        continue;
      }
      if(t==='agent.skill_loaded'){
        out.push('<div class="row">'+avatar(aid)+'<span class="chip skill">📘 '+esc(agentName(aid))+
          ' loaded skill <b style="margin:0 3px">'+esc(p.title||p.name)+'</b>'+(p.auto?'(at start)':'(on demand)')+'</span></div>');
        continue;
      }
      if(t==='agent.memory_loaded'){
        const files=(p.files||[]).join(', ');
        out.push('<div class="row">'+avatar(aid)+'<span class="chip memory">🧠 '+esc(agentName(aid))+
          ' loaded memory'+(files?': '+esc(files):'')+'</span></div>');
        continue;
      }
      if(t==='context.compacted'){
        out.push('<div class="row">'+avatar(aid)+'<span class="chip compact">🗜 context compacted ('+esc(p.summary_chars||0)+' chars)</span></div>');
        continue;
      }
      if(t==='finding.stored'){
        const f=p.finding||{}, d=f.data||{};
        if(!match((f.title||'')+' '+(d.description||'')+' '+(d.evidence||''))) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="finding">'+headLine(ev)+
          '<div class="ttl">🔎 '+esc(f.title)+'<span class="sev '+esc(f.severity)+'">'+esc(f.severity)+'</span>'+
          ' <span style="color:var(--muted);font-size:11px">'+esc(f.status)+'</span></div>'+
          (d.location?'<div class="text" style="color:var(--muted);font-size:12px">@ '+esc(d.location)+'</div>':'')+
          (d.description?'<div class="text" style="margin-top:4px">'+esc(d.description)+'</div>':'')+
          (d.evidence?'<details class="tool" style="margin-top:6px"><summary><span class="tname">evidence</span></summary><pre>'+esc(d.evidence)+'</pre></details>':'')+
          '</div></div>');
        continue;
      }
      if(t==='approval.request'){
        out.push('<div class="row">'+avatar(aid)+'<div class="approval">'+headLine(ev)+
          '<div class="text">🔐 <b>'+esc(p.agent_name)+'</b> requests approval to run <code>'+esc(p.tool)+'</code>'+
          (p.category?' <span style="color:var(--muted);font-size:11px">['+esc(p.category)+']</span>':'')+'</div>'+
          '<pre style="margin:6px 0 0;white-space:pre-wrap">'+esc(pretty(p.input))+'</pre></div></div>');
        continue;
      }
      if(t==='approval.resolved'){
        out.push('<div class="row"><span class="chip">'+(p.approved?'✅ approval granted':'⛔ approval denied'+(p.reason?': '+esc(p.reason):''))+'</span></div>');
        continue;
      }
      if(t==='user.request'){
        out.push('<div class="row">'+avatar(aid)+'<div class="bubble narr">'+headLine(ev)+
          '<div class="text">❓ '+esc(p.message)+'</div></div></div>');
        continue;
      }
      if(t==='user.request_resolved'){
        out.push('<div class="row"><span class="chip">✅ operator answered'+(p.answer?': '+esc(oneline(p.answer)):'')+'</span></div>');
        continue;
      }
      if(t==='plan.update'){
        const steps=(p.plan&&p.plan.steps)||[];
        out.push('<div class="row">'+avatar(aid)+'<div class="plan">'+headLine(ev)+'<b>Plan</b><ol>'+
          steps.map(s=>'<li class="'+esc(s.status)+'">'+esc(s.text)+'</li>').join('')+'</ol></div></div>');
        continue;
      }
      if(t==='plan.approval_request'){
        const steps=(p.plan&&p.plan.steps)||[];
        out.push('<div class="row">'+avatar(aid)+'<div class="plan pending">'+headLine(ev)+
          '<b>📋 Plan proposed — awaiting operator sign-off</b> <span style="color:var(--muted);font-size:11px">('+esc(p.mode||'')+')</span><ol>'+
          steps.map(s=>'<li class="'+esc(s.status)+'">'+esc(s.text||s)+'</li>').join('')+'</ol></div></div>');
        continue;
      }
      if(t==='plan.approval_resolved'){
        const icon = p.decision==='approve'?'✅':(p.decision==='edit'?'✏️':'⛔');
        out.push('<div class="row"><span class="chip">'+icon+' plan '+esc(p.decision||'')+(p.feedback?': '+esc(oneline(p.feedback)):'')+'</span></div>');
        continue;
      }
      if(t==='plan.step'){ out.push('<div class="row"><span class="chip">📋 step '+esc(p.index)+' → '+esc(p.status)+'</span></div>'); continue; }
      if(t==='session.status'){ out.push('<div class="divider">session '+esc(p.status)+'</div>'); continue; }
      if(t==='log'){ out.push('<div class="row"><span class="chip">['+esc(p.level)+'] '+esc(p.message)+'</span></div>'); continue; }
      if(t==='cost.update'){ const c=p.cost||{}; out.push('<div class="row"><span class="chip">💲 $'+(c.total_usd||0).toFixed(4)+' · in '+(c.input_tokens||0)+' / out '+(c.output_tokens||0)+' tok</span></div>'); continue; }
      if(t==='error'){
        if(!match(p.message)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="err-row">'+headLine(ev)+'<div class="text">⛔ '+esc(p.message)+'</div></div></div>');
        continue;
      }
    }
    ui.feed.innerHTML = out.length? out.join('') : '<div class="empty">No matching events.</div>';
  }

  // RAW mode: the whole LLM conversation per agent, in order — the user/task inputs, each
  // assistant turn (reasoning + answer + the exact tool calls with full JSON input + stop
  // reason), the tool outputs, operator interjections, and errors. Nothing filtered out.
  function renderRaw(){
    const q = ui.q.value.trim().toLowerCase();
    const match = (s)=> !q || String(s||'').toLowerCase().includes(q);
    const out = [];
    for(const ev of events){
      const t=ev.type, p=ev.payload||{}, aid=ev.agent_id;
      if(activeAgent && aid!==activeAgent) continue;
      if(t==='agent.created'){
        const a=agents[aid]||{};
        out.push('<div class="divider">spawned '+esc(a.name)+' · '+esc(a.role)+(a.model?' · '+esc(a.model):'')+'</div>'+
          '<div class="row">'+avatar(aid)+'<div class="bubble user-msg">'+headLine(ev)+
          '<div class="text"><b>Task:</b> '+esc(a.task||'')+'</div></div></div>');
        continue;
      }
      if(t==='agent.message' && p.role==='user'){
        const txt = typeof p.content==='string'? p.content : pretty(p.content);
        if(!txt.trim() || !match(txt)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="bubble user-msg">'+headLine(ev)+
          '<div class="text">'+esc(txt)+'</div></div></div>');
        continue;
      }
      if(t==='operator.interjection'){
        if(!match(p.message)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="bubble user-msg">'+headLine(ev)+
          '<div class="text">🧭 '+esc(p.message)+'</div></div></div>');
        continue;
      }
      if(t==='approval.mode_changed'){
        out.push('<div class="row"><span class="chip intensity">'+(p.approval_mode==='auto'?'🔓 command validation BYPASSED (auto)':'🔒 command validation re-enabled (manual)')+'</span></div>');
        continue;
      }
      if(t==='agent.raw'){
        const tools = p.tool_calls||[];
        if(!match((p.thinking||'')+' '+(p.text||'')+' '+JSON.stringify(tools))) continue;
        let inner='';
        if(p.thinking) inner+='<details class="think" open><summary>💭 reasoning ('+p.thinking.length+' chars)</summary><pre>'+esc(p.thinking)+'</pre></details>';
        if(p.text) inner+='<div class="text">'+esc(p.text)+'</div>';
        for(const tc of tools) inner+='<div class="raw-tool">🔧 <b>'+esc(tc.name)+'</b><pre>'+esc(pretty(tc.input))+'</pre></div>';
        if(!p.thinking && !p.text && !tools.length) inner+='<div class="text" style="color:var(--muted)">(empty turn)</div>';
        out.push('<div class="row">'+avatar(aid)+'<div class="raw-turn">'+headLine(ev)+
          '<div class="raw-stopbadge">stop reason: <b>'+esc(p.stop_reason||'?')+'</b></div>'+inner+'</div></div>');
        continue;
      }
      if(t==='tool.result'){
        const res=p.result||'';
        if(!match(p.tool+' '+res)) continue;
        const cls=p.is_error?' err':'';
        out.push('<div class="row">'+avatar(aid)+'<details class="tool'+cls+'"><summary><span class="tname">⮑ '+esc(p.tool)+' result</span>'+
          (p.is_error?'<span class="bad">error</span>':'<span class="ok">ok</span>')+'</summary><pre>'+esc(res)+'</pre></details></div>');
        continue;
      }
      if(t==='error'){
        if(!match(p.message)) continue;
        out.push('<div class="row">'+avatar(aid)+'<div class="err-row">'+headLine(ev)+'<div class="text">⛔ '+esc(p.message)+'</div></div></div>');
        continue;
      }
    }
    ui.feed.innerHTML = out.length? out.join('') :
      '<div class="empty">No raw LLM turns in this log.<br>Raw output (agent.raw) is recorded for sessions run after the raw-logging update.</div>';
  }

  function renderAgents(){
    const ids = Object.keys(agents);
    const html = ['<div class="agent'+(activeAgent===null?' active':'')+'" data-id=""><div class="av" style="background:#6e7681">∑</div>'+
      '<div class="meta"><div class="nm">All agents</div><div class="rl">'+ids.length+' agents</div></div></div>'];
    for(const id of ids){
      const a=agents[id], pad=depthOf(id)*12;
      html.push('<div class="agent'+(activeAgent===id?' active':'')+'" data-id="'+id+'" style="margin-left:'+pad+'px">'+
        '<div class="av" style="background:'+a.color+'">'+esc(initials(a.name))+'</div>'+
        '<div class="meta"><div class="nm">'+esc(a.name)+'</div><div class="rl">'+esc(a.role)+'</div></div>'+
        '<span class="badge">'+esc(a.status||'')+'</span></div>');
    }
    ui.agentlist.innerHTML = html.join('');
    ui.agentlist.querySelectorAll('.agent').forEach(el=>{
      el.onclick = ()=>{ const id=el.getAttribute('data-id'); activeAgent = id||null; renderAgents(); render(); };
    });
  }

  function renderStats(){
    const cost = lastCost? ('$'+(lastCost.total_usd||0).toFixed(4)) : '$0.0000';
    const tin = lastCost? (lastCost.input_tokens||0):0, tout = lastCost? (lastCost.output_tokens||0):0;
    ui.stats.innerHTML =
      (BOOT.live?'<span class="stat"><span class="live-dot"></span>live</span>':'')+
      '<span class="stat"><b>'+Object.keys(agents).length+'</b> agents</span>'+
      '<span class="stat"><b>'+events.length+'</b> events</span>'+
      '<span class="stat"><b>'+findingCount+'</b> findings</span>'+
      '<span class="stat">tokens <b>'+(tin+tout).toLocaleString()+'</b></span>'+
      '<span class="stat">cost <b>'+cost+'</b></span>'+
      (errorCount?'<span class="stat" style="color:var(--err)"><b>'+errorCount+'</b> errors</span>':'');
  }

  function refreshAll(){ renderAgents(); renderStats(); render(); }
  ['q','think','tokens','logs'].forEach(k=>{ ui[k].addEventListener('input',render); ui[k].addEventListener('change',render); });
  function setMode(m){
    mode = m;
    ui.mChat.classList.toggle('active', m==='chat');
    ui.mRaw.classList.toggle('active', m==='raw');
    document.body.classList.toggle('rawmode', m==='raw');
    render();
  }
  ui.mChat.addEventListener('click', ()=>setMode('chat'));
  ui.mRaw.addEventListener('click', ()=>setMode('raw'));

  // Data source: embedded events (static) or polled (live --serve).
  if(BOOT.live){
    let offset=0;
    async function poll(){
      try{
        const r=await fetch('/api/events?offset='+offset);
        const j=await r.json();
        if(j.events && j.events.length){
          const nearBottom = (window.innerHeight+window.scrollY) >= (document.body.scrollHeight-140);
          j.events.forEach(ingest); offset=j.next; refreshAll();
          if(nearBottom) window.scrollTo(0,document.body.scrollHeight);
        }
      }catch(e){ /* server stopped */ }
      setTimeout(poll, 1500);
    }
    poll();
  } else {
    (BOOT.events||[]).forEach(ingest);
    refreshAll();
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
