"""API & web-application testing tools (categories: recon / web / exploit).

A second wave of web-focused tooling beyond the basics in web.py — built for mapping and
attacking modern web apps and HTTP APIs: fast probing, crawling/endpoint discovery, hidden
parameter discovery, command-injection testing, and WAF fingerprinting. Like every tool here
they are ACTIVE (they send requests to the target); respect intensity and stay in scope."""
from __future__ import annotations

from ..registry import tool
from ._common import check_scope, host_of, require_arg, run, threads

_INTENSITY = {
    "type": "string",
    "enum": ["passive", "stealth", "normal", "aggressive", "insane"],
    "description": "Caps concurrency/threads (passive=very gentle ... insane=max).",
}


@tool(
    name="http_probe",
    category="recon",
    requires=["httpx-toolkit"],
    description=(
        "Probe one or more URLs/hosts with httpx and report, per target: HTTP status code, page "
        "title, detected technologies, web-server header, final URL after redirects, and resolved "
        "IP. The fast way to triage a list of hosts/endpoints (e.g. from a crawl or subdomain "
        "enumeration) and fingerprint what's actually live. Low impact (a few requests per "
        "target). Pass several targets separated by spaces, commas or newlines."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string",
                       "description": "One or more URLs/hosts (space/comma/newline separated), e.g. "
                                      "'https://a.tld http://b.tld:8080'."},
            "ports": {"type": "string", "description": "Extra ports to probe per host (httpx -p, e.g. '80,443,8080')."},
            "match_codes": {"type": "string", "description": "Only report these status codes (httpx -mc, e.g. '200,401,403')."},
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["target"],
    },
)
async def http_probe(args: dict) -> str:
    target = require_arg(args, "target")
    targets = [t for t in target.replace(",", " ").split() if t]
    for t in targets:
        check_scope(t)
    argv = ["httpx-toolkit", "-silent", "-nc", "-title", "-status-code", "-tech-detect",
            "-web-server", "-ip", "-follow-redirects"]
    if args.get("ports"):
        argv += ["-p", str(args["ports"])]
    if args.get("match_codes"):
        argv += ["-mc", str(args["match_codes"])]
    # httpx reads targets from stdin (one per line) when no -u/-l is given.
    return await run(argv, timeout=int(args.get("timeout", 300)), input_text="\n".join(targets))


@tool(
    name="web_crawl",
    category="recon",
    requires=["gospider"],
    description=(
        "Crawl a web app with gospider to enumerate its attack surface: linked URLs, forms, and "
        "endpoints/paths extracted from inline and external JavaScript. The go-to for discovering "
        "API endpoints and hidden routes a wordlist won't find. `depth` controls how deep to "
        "follow links (default 2 — higher is slower/louder). Set `other_sources=true` to also pull "
        "URLs from robots.txt/sitemap and public archives (needs internet). Active crawling — "
        "respect scope and intensity."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Base URL to crawl (e.g. https://host/)."},
            "depth": {"type": "integer", "description": "Crawl depth (default 2)."},
            "other_sources": {"type": "boolean",
                              "description": "Also gather URLs from robots/sitemap/archives (gospider -a --other-source). Default false."},
            "include_subs": {"type": "boolean", "description": "Also crawl in-scope subdomains (gospider --subs). Default false."},
            "intensity": _INTENSITY,
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["url"],
    },
)
async def web_crawl(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    argv = ["gospider", "-s", url, "--no-redirect",
            "-d", str(int(args.get("depth", 2))),
            "-t", str(threads(args.get("intensity"))), "-c", "5"]
    if args.get("other_sources"):
        argv += ["-a", "--other-source"]
    if args.get("include_subs"):
        argv += ["--subs"]
    return await run(argv, timeout=int(args.get("timeout", 300)))


@tool(
    name="param_discover",
    category="web",
    requires=["arjun"],
    description=(
        "Discover hidden HTTP parameters on an endpoint with Arjun — query-string, body, JSON or "
        "header params the app accepts but doesn't advertise. Core API-testing step: finds the "
        "inputs you then test for IDOR/injection/mass-assignment. Sends bursts of requests "
        "(bucketed brute-force), so it's moderately noisy. `method` selects GET (default)/POST/"
        "JSON. Optionally pass a `wordlist` of candidate names."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target endpoint URL (e.g. https://host/api/item)."},
            "method": {"type": "string", "enum": ["GET", "POST", "JSON", "XML"],
                       "description": "Request method/body type to fuzz (default GET)."},
            "wordlist": {"type": "string", "description": "Path to a parameter-name wordlist on Kali (optional; Arjun default used)."},
            "headers": {"type": "string", "description": "Extra header(s) to send, e.g. 'Authorization: Bearer x' (optional)."},
            "intensity": _INTENSITY,
            "timeout": {"type": "integer", "description": "Max seconds (default 600)."},
        },
        "required": ["url"],
    },
)
async def param_discover(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    argv = ["arjun", "-u", url, "-m", str(args.get("method") or "GET"),
            "-t", str(threads(args.get("intensity")))]
    if args.get("wordlist"):
        argv += ["-w", str(args["wordlist"])]
    if args.get("headers"):
        argv += ["--headers", str(args["headers"])]
    return await run(argv, timeout=int(args.get("timeout", 600)))


@tool(
    name="commix_test",
    category="exploit",
    requires=["commix"],
    description=(
        "Test a URL/request for OS COMMAND INJECTION with commix and, if found, confirm code "
        "execution. HIGH IMPACT: it injects shell metacharacters and can execute commands on the "
        "target — only run against authorised targets, ideally after a manual indication. Mark the "
        "injection point in the URL or `data` with an asterisk (*) or let commix pick. Always runs "
        "with --batch (non-interactive). Use `level` 1-3 to widen the tests."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (mark the param to test with * or include query params)."},
            "data": {"type": "string", "description": "POST body to test (optional; sets POST)."},
            "cookie": {"type": "string", "description": "Cookie header for authenticated testing (optional)."},
            "level": {"type": "integer", "enum": [1, 2, 3], "description": "Test depth 1-3 (default 1)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 900)."},
        },
        "required": ["url"],
    },
)
async def commix_test(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    argv = ["commix", "-u", url, "--batch", "--level", str(int(args.get("level", 1)))]
    if args.get("data"):
        argv += ["--data", str(args["data"])]
    if args.get("cookie"):
        argv += ["--cookie", str(args["cookie"])]
    return await run(argv, timeout=int(args.get("timeout", 900)))


@tool(
    name="waf_detect",
    category="recon",
    requires=["wafw00f"],
    description=(
        "Fingerprint whether a Web Application Firewall sits in front of the target, and which one, "
        "with wafw00f. Quick and low-impact (a handful of requests). Knowing the WAF up front "
        "explains blocked payloads and informs evasion/encoding choices for later web tests. Set "
        "`find_all=true` to probe for every WAF signature rather than stopping at the first match."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (http(s)://host[:port])."},
            "find_all": {"type": "boolean", "description": "Detect ALL WAFs in the path, not just the first (wafw00f -a). Default false."},
            "timeout": {"type": "integer", "description": "Max seconds (default 120)."},
        },
        "required": ["url"],
    },
)
async def waf_detect(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(host_of(url))
    argv = ["wafw00f", url]
    if args.get("find_all"):
        argv += ["-a"]
    return await run(argv, timeout=int(args.get("timeout", 120)))
