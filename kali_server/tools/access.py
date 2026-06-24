"""Credential-attack and exploitation tools (categories: bruteforce / exploit).

These are the highest-impact tools: credential attacks can lock accounts and are very noisy;
exploitation can crash or alter the target. They are operator-gated by default in Spider, and
several have extra guardrails here. Stay strictly in scope and respect intensity."""
from __future__ import annotations

import os
import time

from ..registry import tool
from ._common import check_scope, host_of, hydra_tasks, rate, require_arg, run

# Interpreters the run_poc tool will execute, mapped to a file extension for the temp script.
_POC_INTERPRETERS = {
    "python3": "py", "python": "py", "bash": "sh", "sh": "sh",
    "perl": "pl", "ruby": "rb", "php": "php", "node": "js",
}


@tool(
    name="run_poc",
    category="exploit",
    requires=[],
    description=(
        "Write a proof-of-concept / exploit script INSIDE the Kali container and execute it "
        "there, returning its output. This is the canonical way to run a PoC: PoCs always run in "
        "the isolated Kali container, never on the Spider host. Provide the script `code`, the "
        "`interpreter` (python3 (default), bash, sh, perl, ruby, php, node), optional `args`, and "
        "an optional `target` (validated against scope). HIGH IMPACT — only run validated, "
        "in-scope, minimally-destructive PoCs; never DoS or destroy data without explicit "
        "authorisation. The script is saved under the Kali work dir's poc/ folder so you can "
        "re-read or reference it (e.g. include it as evidence in the report)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The PoC/exploit source code to run."},
            "interpreter": {"type": "string",
                            "enum": ["python3", "python", "bash", "sh", "perl", "ruby", "php", "node"],
                            "description": "Interpreter to run the script with (default python3)."},
            "args": {"type": "array", "items": {"type": "string"},
                     "description": "Command-line arguments passed to the script (optional)."},
            "target": {"type": "string",
                       "description": "Optional in-scope target the PoC hits; checked against SPIDER_SCOPE."},
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["code"],
    },
)
async def run_poc(args: dict) -> str:
    code = require_arg(args, "code")
    if args.get("target"):
        check_scope(str(args["target"]))
    interp = (args.get("interpreter") or "python3").strip()
    if interp not in _POC_INTERPRETERS:
        raise ValueError(f"interpreter must be one of {sorted(_POC_INTERPRETERS)}")
    base = os.environ.get("SPIDER_KALI_WORKDIR", "/root/spider")
    poc_dir = os.path.join(base, "poc")
    os.makedirs(poc_dir, exist_ok=True)
    path = os.path.join(poc_dir, f"poc_{int(time.time() * 1000)}.{_POC_INTERPRETERS[interp]}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    extra = [str(a) for a in (args.get("args") or [])]
    return await run([interp, path, *extra], timeout=int(args.get("timeout", 300)))


@tool(
    name="searchsploit",
    category="exploit",
    requires=["searchsploit"],
    description=(
        "Search the local Exploit-DB (searchsploit) for public exploits/PoCs matching a "
        "product and version (e.g. 'vsftpd 2.3.4' or 'Apache 2.4.49'). READ-ONLY lookup — it "
        "does not run anything. Use it to find candidate exploits after fingerprinting a "
        "service version."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Product and (ideally) version to search for."},
            "timeout": {"type": "integer", "description": "Max seconds (default 60)."},
        },
        "required": ["query"],
    },
)
async def searchsploit(args: dict) -> str:
    query = require_arg(args, "query")
    return await run(["searchsploit", "--colour", "--disable-colour", *query.split()],
                     timeout=int(args.get("timeout", 60)))


@tool(
    name="nuclei_scan",
    category="exploit",
    requires=["nuclei"],
    description=(
        "Run nuclei against a target URL/host with its templated checks for known CVEs, "
        "misconfigurations, and exposures. Sends crafted requests (active). Use `severity` to "
        "limit (e.g. 'critical,high') and `tags` to focus (e.g. 'cve,exposure'). Intensity "
        "caps the request rate. Detection-focused, but some templates are intrusive."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target URL or host."},
            "severity": {"type": "string", "description": "Comma list to include (info,low,medium,high,critical)."},
            "tags": {"type": "string", "description": "Comma list of template tags to focus on (optional)."},
            "intensity": {"type": "string", "enum": ["passive", "stealth", "normal", "aggressive", "insane"],
                           "description": "Caps the requests/second rate."},
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["target"],
    },
)
async def nuclei_scan(args: dict) -> str:
    target = require_arg(args, "target")
    check_scope(target)
    argv = ["nuclei", "-u", target, "-nc", "-silent", "-rl", str(rate(args.get("intensity")))]
    if args.get("severity"):
        argv += ["-severity", str(args["severity"])]
    if args.get("tags"):
        argv += ["-tags", str(args["tags"])]
    return await run(argv, timeout=int(args.get("timeout", 900)))


@tool(
    name="hydra_bruteforce",
    category="bruteforce",
    requires=["hydra"],
    description=(
        "Online password attack with THC-Hydra against a network service. VERY HIGH IMPACT: "
        "noisy, can LOCK OUT accounts, and may be illegal out of scope — only run when "
        "explicitly authorised. You must give `service` (e.g. ssh, ftp, http-post-form, smb, "
        "rdp, mysql) and at least one of a username/userlist and a password/passlist.\n"
        "- `username` or `userlist` : single user or a file path of users.\n"
        "- `password` or `passlist` : single password or a file path of passwords.\n"
        "- `service_args`           : extra hydra module arguments (REQUIRED for http forms, "
        "e.g. '/login:user=^USER^&pass=^PASS^:F=incorrect').\n"
        "Intensity caps the parallel task count (kept low to reduce lockouts). Start with a "
        "tiny, targeted list — do not throw huge wordlists at production services."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target host/IP."},
            "service": {"type": "string", "description": "Hydra service/module (ssh, ftp, smb, rdp, mysql, http-post-form, ...)."},
            "port": {"type": "integer", "description": "Service port (optional; hydra default for the service)."},
            "username": {"type": "string", "description": "Single username (use this OR userlist)."},
            "userlist": {"type": "string", "description": "Path to a username wordlist on Kali (use this OR username)."},
            "password": {"type": "string", "description": "Single password (use this OR passlist)."},
            "passlist": {"type": "string", "description": "Path to a password wordlist on Kali (use this OR password)."},
            "service_args": {"type": "string", "description": "Extra module args (required for http-*-form modules)."},
            "stop_on_first": {"type": "boolean", "description": "Stop at the first valid pair (-f). Default true."},
            "intensity": {"type": "string", "enum": ["passive", "stealth", "normal", "aggressive", "insane"],
                           "description": "Caps parallel tasks (passive=1 ... insane=16)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["target", "service"],
    },
)
async def hydra_bruteforce(args: dict) -> str:
    target = host_of(require_arg(args, "target"))
    check_scope(target)
    service = require_arg(args, "service")
    if not (args.get("username") or args.get("userlist")):
        raise ValueError("provide a 'username' or a 'userlist'")
    if not (args.get("password") or args.get("passlist")):
        raise ValueError("provide a 'password' or a 'passlist'")
    argv = ["hydra", "-t", str(hydra_tasks(args.get("intensity")))]
    if args.get("stop_on_first", True):
        argv += ["-f"]
    argv += ["-L", str(args["userlist"])] if args.get("userlist") else ["-l", str(args["username"])]
    argv += ["-P", str(args["passlist"])] if args.get("passlist") else ["-p", str(args["password"])]
    if args.get("port"):
        argv += ["-s", str(int(args["port"]))]
    # hydra target/service form: hydra ... <target> <service> [service_args]
    argv += [target, service]
    if args.get("service_args"):
        argv += [str(args["service_args"])]
    return await run(argv, timeout=int(args.get("timeout", 900)))


@tool(
    name="metasploit_run",
    category="exploit",
    requires=["msfconsole"],
    description=(
        "Run a Metasploit module non-interactively. EXTREMELY HIGH IMPACT — a real exploit "
        "module can crash, alter, or compromise the target. Only use against authorised "
        "targets after a finding is validated, and prefer auxiliary/scanner modules first.\n"
        "Provide `module` (e.g. 'auxiliary/scanner/ssh/ssh_version' or 'exploit/...') and "
        "`options` as a name->value map (RHOSTS, RPORT, etc.). By default runs with "
        "`action='check'` (safe capability check where supported); set action='run' to "
        "actually execute, and for exploits set a `payload` if needed. Use a scanner/check "
        "before ever choosing run."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "module": {"type": "string", "description": "Full msf module path."},
            "options": {"type": "object", "description": "Module options (RHOSTS, RPORT, ...). RHOSTS must be in scope."},
            "action": {"type": "string", "enum": ["check", "run"], "description": "check (safe, default) or run (executes)."},
            "payload": {"type": "string", "description": "Payload for exploit modules when action='run' (optional)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 600)."},
        },
        "required": ["module"],
    },
)
async def metasploit_run(args: dict) -> str:
    module = require_arg(args, "module")
    options = args.get("options") or {}
    rhosts = options.get("RHOSTS") or options.get("rhosts")
    if rhosts:
        check_scope(str(rhosts))
    action = (args.get("action") or "check").lower()
    lines = [f"use {module}"]
    for k, v in options.items():
        lines.append(f"set {k} {v}")
    if args.get("payload"):
        lines.append(f"set PAYLOAD {args['payload']}")
    lines.append("check" if action == "check" else "run")
    lines.append("exit")
    rc = "; ".join(lines)
    return await run(["msfconsole", "-q", "-x", rc], timeout=int(args.get("timeout", 600)))
