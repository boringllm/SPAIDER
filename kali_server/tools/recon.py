"""Reconnaissance & discovery tools (category: recon/enum).

These map the attack surface. They are comparatively low-impact, but `nmap` with service/
version/OS detection and scripts is still active scanning — respect the intensity setting.
"""
from __future__ import annotations

from ..registry import tool
from ._common import check_scope, host_of, nmap_timing, require_arg, run

# Reusable intensity schema fragment.
_INTENSITY = {
    "type": "string",
    "enum": ["passive", "stealth", "normal", "aggressive", "insane"],
    "description": "Loudness/speed. passive/stealth = slow & quiet (nmap -T1/-T2), "
                   "normal = -T3, aggressive = -T4, insane = -T5. Use the session default "
                   "unless you have a reason to change it.",
}


@tool(
    name="nmap_scan",
    category="recon",
    requires=["nmap"],
    description=(
        "Run an nmap scan against one or more in-scope hosts/networks. The single most "
        "important recon tool — choose the mode carefully, it controls how loud and how "
        "deep the scan is:\n"
        "- mode='ping'        : host discovery only (-sn), no port scan. Fast, quiet.\n"
        "- mode='quick'       : top 100 TCP ports (-F). Good first look.\n"
        "- mode='full'        : all 65535 TCP ports (-p-). Thorough but slow/loud.\n"
        "- mode='service'     : version + default scripts on the given ports (-sV -sC). "
        "Use AFTER you know which ports are open.\n"
        "- mode='udp'         : top UDP ports (-sU --top-ports). Slow.\n"
        "`ports` overrides the port selection (e.g. '22,80,443' or '1-1000'). `extra` lets "
        "you append raw nmap flags (e.g. '--script vuln' or '-O' for OS detection) when you "
        "really need them — use sparingly and stay in scope. Intensity maps to the -T timing "
        "template. NEVER scan hosts outside the agreed scope."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Host, IP, hostname, or CIDR (in scope). Multiple allowed, space-separated."},
            "mode": {"type": "string", "enum": ["ping", "quick", "full", "service", "udp"],
                      "description": "Scan profile (see tool description). Default 'quick'."},
            "ports": {"type": "string", "description": "Explicit port spec (e.g. '80,443' or '1-1000'). Overrides mode's default ports."},
            "extra": {"type": "string", "description": "Extra raw nmap flags appended verbatim (advanced; e.g. '--script ssl-enum-ciphers')."},
            "intensity": _INTENSITY,
            "timeout": {"type": "integer", "description": "Max seconds (default 600; full/udp scans are slow)."},
        },
        "required": ["target"],
    },
)
async def nmap_scan(args: dict) -> str:
    target = require_arg(args, "target")
    for t in target.split():
        check_scope(t)
    mode = (args.get("mode") or "quick").lower()
    timing = nmap_timing(args.get("intensity"))
    timeout = int(args.get("timeout", 600))

    argv = ["nmap", timing]
    if mode == "ping":
        argv += ["-sn"]
    elif mode == "quick":
        argv += ["-F"]
    elif mode == "full":
        argv += ["-p-"]
    elif mode == "service":
        argv += ["-sV", "-sC"]
    elif mode == "udp":
        argv += ["-sU", "--top-ports", "50"]
    else:
        raise ValueError(f"unknown mode '{mode}'")
    if args.get("ports") and mode != "ping":
        argv += ["-p", str(args["ports"])]
    if args.get("extra"):
        argv += str(args["extra"]).split()
    argv += target.split()
    return await run(argv, timeout=timeout)


@tool(
    name="dns_enum",
    category="recon",
    requires=["dnsrecon"],
    description=(
        "Enumerate DNS records for a domain (A/AAAA/MX/NS/SOA/TXT and, when permitted, a "
        "zone transfer and brute-force of common subdomains). Passive-leaning OSINT, but a "
        "subdomain brute-force generates DNS traffic. Use `do_brute=true` to attempt "
        "subdomain brute-forcing with the built-in wordlist."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Target domain (e.g. example.com)."},
            "do_brute": {"type": "boolean", "description": "Also brute-force common subdomains (louder). Default false."},
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["domain"],
    },
)
async def dns_enum(args: dict) -> str:
    domain = require_arg(args, "domain")
    check_scope(domain)
    argv = ["dnsrecon", "-d", domain]
    if args.get("do_brute"):
        argv += ["-t", "brt"]
    else:
        argv += ["-t", "std"]
    return await run(argv, timeout=int(args.get("timeout", 300)))


@tool(
    name="whois_lookup",
    category="recon",
    requires=["whois"],
    description="WHOIS lookup for a domain or IP (registrar, org, contacts, netblock). Passive.",
    input_schema={
        "type": "object",
        "properties": {"target": {"type": "string", "description": "Domain or IP."}},
        "required": ["target"],
    },
)
async def whois_lookup(args: dict) -> str:
    target = host_of(require_arg(args, "target"))
    return await run(["whois", target], timeout=int(args.get("timeout", 60)))


@tool(
    name="whatweb_scan",
    category="recon",
    requires=["whatweb"],
    description=(
        "Fingerprint a web target with WhatWeb: server, CMS, frameworks, JS libraries, "
        "analytics, and versions. `aggression` 1=stealthy single request (default), 3=more "
        "probing, 4=heavy. Higher aggression sends more requests."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (http(s)://host[:port][/path])."},
            "aggression": {"type": "integer", "enum": [1, 3, 4], "description": "WhatWeb aggression level (1/3/4). Default 1."},
            "timeout": {"type": "integer", "description": "Max seconds (default 120)."},
        },
        "required": ["url"],
    },
)
async def whatweb_scan(args: dict) -> str:
    url = require_arg(args, "url")
    check_scope(url)
    level = int(args.get("aggression", 1))
    return await run(["whatweb", f"-a{level}", "--color=never", url], timeout=int(args.get("timeout", 120)))
