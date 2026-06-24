"""Network & infrastructure service tools (category: enum/network).

Deep service enumeration for SMB/LDAP/SNMP/TLS etc. Mostly read-only enumeration, but it
touches the services directly — stay in scope and respect intensity."""
from __future__ import annotations

from ..registry import tool
from ._common import check_scope, host_of, require_arg, run


@tool(
    name="enum4linux",
    category="enum",
    requires=["enum4linux-ng"],
    description=(
        "Enumerate a Windows/Samba host over SMB/RPC with enum4linux-ng: shares, users, "
        "groups, password policy, OS info, and null-session checks. Read-only enumeration. "
        "Provide `username`/`password` for an authenticated run, or leave blank for an "
        "anonymous/null session."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target host/IP."},
            "username": {"type": "string", "description": "Username for authenticated enum (optional)."},
            "password": {"type": "string", "description": "Password (optional)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 600)."},
        },
        "required": ["target"],
    },
)
async def enum4linux(args: dict) -> str:
    target = host_of(require_arg(args, "target"))
    check_scope(target)
    argv = ["enum4linux-ng", "-A"]
    if args.get("username"):
        argv += ["-u", str(args["username"]), "-p", str(args.get("password", ""))]
    argv += [target]
    return await run(argv, timeout=int(args.get("timeout", 600)))


@tool(
    name="smb_list_shares",
    category="enum",
    requires=["smbclient"],
    description=(
        "List SMB shares on a host with smbclient. Use anonymous (default) or supply "
        "`username`/`password`. Read-only. Good for spotting world-readable shares."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target host/IP."},
            "username": {"type": "string", "description": "Username (optional; default anonymous)."},
            "password": {"type": "string", "description": "Password (optional)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 120)."},
        },
        "required": ["target"],
    },
)
async def smb_list_shares(args: dict) -> str:
    target = host_of(require_arg(args, "target"))
    check_scope(target)
    argv = ["smbclient", "-L", f"//{target}/", "-g"]
    if args.get("username"):
        argv += ["-U", f"{args['username']}%{args.get('password','')}"]
    else:
        argv += ["-N"]
    return await run(argv, timeout=int(args.get("timeout", 120)))


@tool(
    name="snmp_enum",
    category="enum",
    requires=["snmpwalk"],
    description=(
        "Walk SNMP on a host (snmpwalk) using a community string (default 'public'). Can "
        "reveal interfaces, processes, routes, installed software, and sometimes credentials. "
        "Read-only. SNMP v1/v2c only here."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Target host/IP."},
            "community": {"type": "string", "description": "Community string (default 'public')."},
            "oid": {"type": "string", "description": "Base OID to walk (optional; default whole tree)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 300)."},
        },
        "required": ["target"],
    },
)
async def snmp_enum(args: dict) -> str:
    target = host_of(require_arg(args, "target"))
    check_scope(target)
    argv = ["snmpwalk", "-v2c", "-c", str(args.get("community") or "public"), target]
    if args.get("oid"):
        argv += [str(args["oid"])]
    return await run(argv, timeout=int(args.get("timeout", 300)))


@tool(
    name="ssl_scan",
    category="enum",
    requires=["sslscan"],
    description=(
        "Inspect a TLS service with sslscan: supported protocols/ciphers, certificate "
        "details, and weak/deprecated configuration (SSLv3, weak ciphers, expiry, "
        "Heartbleed). Read-only. Give host:port (default 443)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "host or host:port (default port 443)."},
            "timeout": {"type": "integer", "description": "Max seconds (default 120)."},
        },
        "required": ["target"],
    },
)
async def ssl_scan(args: dict) -> str:
    target = require_arg(args, "target")
    check_scope(target)
    return await run(["sslscan", "--no-colour", target], timeout=int(args.get("timeout", 120)))
