"""Web application testing tools (category: web).

These are ACTIVE tests that send many requests to the target and, in sqlmap's case, attempt
injection. They are operator-gated by default in SPAIDER. Respect intensity (it caps threads
and request rate) and stay strictly in scope."""
from __future__ import annotations

import os

from ..registry import tool
from ._common import check_scope, rate, require_arg, run, threads

_INTENSITY = {
    "type": "string",
    "enum": ["passive", "stealth", "normal", "aggressive", "insane"],
    "description": "Caps concurrency and request rate (passive=very gentle ... insane=max).",
}

# Common wordlists shipped with Kali; fall back gracefully if absent.
_DIR_WORDLISTS = [
    "/usr/share/wordlists/dirb/common.txt",
    "/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt",
    "/usr/share/seclists/Discovery/Web-Content/common.txt",
]


def _pick_wordlist(explicit: str | None) -> str:
    if explicit and os.path.exists(explicit):
        return explicit
    for w in _DIR_WORDLISTS:
        if os.path.exists(w):
            return w
    raise ValueError("no wordlist found; install seclists/dirb or pass an explicit `wordlist` path")


@tool(
    name="nikto_scan",
    category="web",
    requires=["nikto"],
    description=(
        "Run Nikto against a web server: checks for thousands of known dangerous files/CGIs, "
        "outdated server software, and common misconfigurations. Noisy (hundreds–thousands of "
        "requests) and easily logged/IDS-detected. Use `ssl=true` for HTTPS and `tuning` to "
        "restrict test categories (e.g. '1' = interesting files, '9' = SQLi; see Nikto -Tuning)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Host or URL (e.g. http://10.0.0.5 or 10.0.0.5)."},
            "port": {"type": "integer", "description": "Port (default 80, or 443 if ssl)."},
            "ssl": {"type": "boolean", "description": "Use HTTPS. Default false."},
            "tuning": {"type": "string", "description": "Nikto -Tuning string to limit test categories (optional)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["target"],
    },
)
async def nikto_scan(args: dict) -> str:
    target = require_arg(args, "target")
    check_scope(target)
    argv = ["nikto", "-host", target, "-nointeractive", "-ask", "no"]
    if args.get("port"):
        argv += ["-port", str(int(args["port"]))]
    if args.get("ssl"):
        argv += ["-ssl"]
    if args.get("tuning"):
        argv += ["-Tuning", str(args["tuning"])]
    return await run(argv, timeout=int(args.get("timeout", 900)))


@tool(
    name="gobuster_dir",
    category="web",
    requires=["gobuster"],
    description=(
        "Brute-force directories/files on a web server with Gobuster (dir mode). Discovers "
        "hidden paths, admin panels, backups. Sends one request per wordlist entry — can be "
        "thousands. `extensions` adds file extensions to try (e.g. 'php,txt,bak'). Intensity "
        "controls thread count. Provide a `wordlist` path or rely on the default."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Base URL to scan (e.g. http://host/)."},
            "wordlist": {"type": "string", "description": "Path to a wordlist on the Kali host (optional; sensible default used)."},
            "extensions": {"type": "string", "description": "Comma-separated extensions to append (e.g. 'php,html,bak')."},
            "status_codes": {"type": "string", "description": "Status codes to treat as found (default gobuster behaviour)."},
            "intensity": _INTENSITY,
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["url"],
    },
)
async def gobuster_dir(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    wl = _pick_wordlist(args.get("wordlist"))
    argv = ["gobuster", "dir", "-u", url, "-w", wl, "-q", "--no-color",
            "-t", str(threads(args.get("intensity")))]
    if args.get("extensions"):
        argv += ["-x", str(args["extensions"])]
    if args.get("status_codes"):
        argv += ["-s", str(args["status_codes"]), "-b", ""]
    return await run(argv, timeout=int(args.get("timeout", 900)))


@tool(
    name="ffuf_fuzz",
    category="web",
    requires=["ffuf"],
    description=(
        "Fuzz a single injection point with ffuf. Put the keyword FUZZ where the wordlist "
        "value should go — in the URL (e.g. http://host/FUZZ), a header, or POST data. Great "
        "for directory/parameter/vhost discovery and value brute-forcing. `match_codes`/"
        "`filter_codes`/`filter_size` tune what counts as a hit. Intensity caps the request "
        "rate. Very flexible but can be loud — set a sensible rate."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL containing the FUZZ keyword (e.g. http://host/FUZZ)."},
            "wordlist": {"type": "string", "description": "Wordlist path (optional; default used)."},
            "method": {"type": "string", "description": "HTTP method (default GET)."},
            "data": {"type": "string", "description": "POST body, may contain FUZZ (sets method POST)."},
            "headers": {"type": "object", "description": "Extra headers; a value may contain FUZZ (e.g. vhost/Host fuzzing)."},
            "match_codes": {"type": "string", "description": "Match these status codes (ffuf -mc, e.g. '200,301,403'). Default 'all' with size filter."},
            "filter_codes": {"type": "string", "description": "Filter OUT these status codes (ffuf -fc)."},
            "filter_size": {"type": "string", "description": "Filter OUT responses of this byte size (ffuf -fs)."},
            "intensity": _INTENSITY,
            "timeout": {"type": "integer", "description": "Max seconds (default 600)."},
        },
        "required": ["url"],
    },
)
async def ffuf_fuzz(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    wl = _pick_wordlist(args.get("wordlist"))
    argv = ["ffuf", "-u", url, "-w", wl, "-s", "-rate", str(rate(args.get("intensity"))),
            "-t", str(threads(args.get("intensity")))]
    if args.get("data"):
        argv += ["-X", "POST", "-d", str(args["data"])]
    elif args.get("method"):
        argv += ["-X", str(args["method"]).upper()]
    for k, v in (args.get("headers") or {}).items():
        argv += ["-H", f"{k}: {v}"]
    if args.get("match_codes"):
        argv += ["-mc", str(args["match_codes"])]
    if args.get("filter_codes"):
        argv += ["-fc", str(args["filter_codes"])]
    if args.get("filter_size"):
        argv += ["-fs", str(args["filter_size"])]
    return await run(argv, timeout=int(args.get("timeout", 600)))


@tool(
    name="sqlmap_test",
    category="web",
    requires=["sqlmap"],
    description=(
        "Test a single URL/request for SQL injection with sqlmap and, if found, optionally "
        "extract data. HIGH IMPACT: it sends many crafted/malformed requests and can MODIFY "
        "data with some techniques — only run against authorised targets. Controls:\n"
        "- `data`    : POST body to test (sets POST). Mark the tested param with * or let "
        "sqlmap pick.\n"
        "- `level` (1-5) and `risk` (1-3): higher = more payloads and riskier tests "
        "(risk 3 can include heavy/UPDATE-based tests). Keep low unless authorised.\n"
        "- `extra`   : raw sqlmap flags for extraction once injection is confirmed (e.g. "
        "'--dbs', '--current-user', '-D shop --tables'). Start WITHOUT extraction to just "
        "detect, then re-run with extraction flags.\n"
        "Always runs with --batch (non-interactive)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (may include query params to test)."},
            "data": {"type": "string", "description": "POST data to test (optional)."},
            "cookie": {"type": "string", "description": "Cookie header for authenticated testing (optional)."},
            "level": {"type": "integer", "enum": [1, 2, 3, 4, 5], "description": "Test depth (default 1)."},
            "risk": {"type": "integer", "enum": [1, 2, 3], "description": "Test riskiness (default 1; 3 may modify data)."},
            "extra": {"type": "string", "description": "Extra sqlmap flags (e.g. extraction: '--dbs', '-D db --tables')."},
            "timeout": {"type": "integer", "description": "Max seconds (default 1200)."},
        },
        "required": ["url"],
    },
)
async def sqlmap_test(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    argv = ["sqlmap", "-u", url, "--batch", "--disable-coloring",
            "--level", str(int(args.get("level", 1))), "--risk", str(int(args.get("risk", 1)))]
    if args.get("data"):
        argv += ["--data", str(args["data"])]
    if args.get("cookie"):
        argv += ["--cookie", str(args["cookie"])]
    if args.get("extra"):
        argv += str(args["extra"]).split()
    return await run(argv, timeout=int(args.get("timeout", 1200)))


@tool(
    name="wpscan_scan",
    category="web",
    requires=["wpscan"],
    description=(
        "Scan a WordPress site with WPScan: core/plugin/theme versions and known "
        "vulnerabilities, user enumeration, and (optionally) plugin discovery. `enumerate` "
        "selects what to enumerate (e.g. 'vp' vulnerable plugins, 'u' users, 'ap' all plugins "
        "— 'ap' is slow/loud). Provide `api_token` to enrich with the WPScan vuln DB."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "WordPress site URL."},
            "enumerate": {"type": "string", "description": "WPScan --enumerate arg (e.g. 'vp,u'). Default 'vp,vt,u'."},
            "api_token": {"type": "string", "description": "WPScan API token for vuln data (optional)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["url"],
    },
)
async def wpscan_scan(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    argv = ["wpscan", "--url", url, "--no-banner", "--disable-tls-checks",
            "--enumerate", str(args.get("enumerate") or "vp,vt,u"), "--format", "cli-no-color"]
    if args.get("api_token"):
        argv += ["--api-token", str(args["api_token"])]
    return await run(argv, timeout=int(args.get("timeout", 900)))
