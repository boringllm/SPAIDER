# Spider Kali MCP server

A small **MCP-over-HTTP** server that runs **inside your Kali container** and exposes Kali's
offensive tools to Spider as callable functions. Spider's agents (recon / web_app / network /
exploitation / post_exploit) connect to it and drive real tools — with carefully described
parameters and a single **intensity** knob that maps to each tool's real flags.

```
Spider (host)  ──MCP/HTTP──►  kali_server (in Kali)  ──subprocess──►  nmap / nikto / sqlmap / hydra / …
```

## Why a server (and not just SSH)?
Each tool is wrapped as a **typed function** with a JSON schema and a detailed description, so
the LLM agents know exactly which parameters exist and what each one does (these tools have very
different blast radius). Every tool also declares an approval **category** (recon / enum / web /
exploit / bruteforce / …) that travels to Spider so the operator's tool-approval policy can gate
the dangerous ones. And the **intensity** (passive → insane) is translated per-tool into safe vs.
loud flags (nmap `-T1`..`-T5`, thread counts, request rates, hydra parallelism).

## Run it (one command)
The image is **pre-configured** — all the tools, interpreters, and wordlists are baked in — so you
just pull and run it. A published build is on Docker Hub:

```bash
docker pull sungyongkim98/spider-kali:latest      # ~1.9 GB download, no build needed
```

Then run it with the compose file (settings come from a `.env` file, never from the image):
```bash
cd kali_server
cp .env.example .env            # then edit: set SPIDER_KALI_TOKEN and SPIDER_SCOPE
docker compose up -d            # pulls the published image (or builds locally if you changed it)
```
`docker compose ps` shows it healthy; open `http://<kali-host>:8765/` for a status page listing every
tool and whether its binary is installed.

> First build downloads Kali + the toolchain (several GB, many minutes). You only do this **once** —
> see "Build once & share" below to distribute the result.

### Build once & share (others only install the Spider client)
Build the image on one machine, hand the result to teammates as a single file, and they run it
without rebuilding. The `scripts/share.sh` (Linux/macOS) / `scripts/share.ps1` (Windows) helpers wrap
the Docker commands:
```bash
# On the machine that builds it:
scripts/share.sh build          # docker build -t spider-kali:latest
scripts/share.sh package        # -> spider-kali-image.tar.gz  (docker save + gzip)

# Send spider-kali-image.tar.gz to a teammate. On their machine:
scripts/share.sh load spider-kali-image.tar.gz   # docker load (no rebuild, works offline)
cp .env.example .env             # set their token/scope
scripts/share.sh run             # docker compose up -d
```
(Windows: `scripts\share.ps1 build|package|load|run`.) Alternatively push to a registry once
(`docker tag spider-kali ghcr.io/you/spider-kali && docker push …`) and teammates `docker pull` it.

Teammates need **only Docker + this loaded image + the Spider client** — no Kali install, no apt
downloads. They point Spider → Settings → Kali at `http://<their-docker-host>:8765/mcp` and go.

### In an existing Kali box (no Docker)
```bash
pip install -r kali_server/requirements.txt
python -m kali_server.run --host 0.0.0.0 --port 8765
```

## Point Spider at it
In Spider's **Settings → Kali** (or `config/config.json`):
```json
"kali": { "enabled": true, "url": "http://<kali-host>:8765/mcp",
          "assign_roles": ["recon","web_app","network","exploitation","post_exploit"] }
```
Spider connects on session start; the Kali tools then appear to those agents as
`kali__nmap_scan`, `kali__sqlmap_test`, etc.

## Safety / configuration (environment variables)
| Variable | Effect |
|---|---|
| `SPIDER_KALI_TOKEN` | If set, every `/mcp` request must send `Authorization: Bearer <token>`. |
| `SPIDER_SCOPE` | Comma-separated hosts/CIDRs. Tools **refuse** targets outside it (server-side backstop). |
| `SPIDER_KALI_WORKDIR` | Working dir for the generic terminal/file tools (default `/root/spider`). |

> Run this only on an isolated lab/engagement network. It executes real offensive tools. The
> server is a backstop — Spider also keeps agents in scope via prompts and the approval policy.

## Running-process monitor
Every command a tool launches is tracked in a registry (`tools/_procs.py`), tagged with which Spider
session/agent/tool started it (Spider sends this in the JSON-RPC `_meta`). This powers Spider's
**Running in Kali** panel: the operator can see live processes, **kill** a runaway one (e.g. an
enumeration scan overloading the target), and stopping a session kills all of that session's
processes. Commands run in their own process group (`start_new_session=True`) so a kill takes down
the whole tool tree; the compose file runs an init (`init: true`) so killed processes are reaped.
Control ops (`__list_processes__` / `__kill_process__` / `__kill_session__`) are operator-only — they
are **not** in `tools/list`, so agents never see them.

## Reaching a target on the operator's own host
Tools run *inside* the container, where `127.0.0.1` is the container itself. To hit a target on the
**operator's host loopback**, use `host.docker.internal` (the compose file maps it via `extra_hosts`
so it works on Linux too). Spider detects a localhost target and tells the agents this automatically.

## Tools included
| Category | Tools |
|---|---|
| recon | `nmap_scan`, `dns_enum`, `whois_lookup`, `whatweb_scan` |
| web | `nikto_scan`, `gobuster_dir`, `ffuf_fuzz`, `sqlmap_test`, `wpscan_scan` |
| enum / network | `enum4linux`, `smb_list_shares`, `snmp_enum`, `ssl_scan` |
| exploit | `searchsploit`, `nuclei_scan`, `metasploit_run`, `run_poc` (write + run a PoC in Kali) |
| bruteforce | `hydra_bruteforce` |
| shell / filesystem | `run_command`, `write_file`, `read_file` |

## Add your own tool
Create or extend a module in `kali_server/tools/`, decorate an async handler, and import the
module in `tools/__init__.py`:

```python
from ..registry import tool
from ._common import check_scope, require_arg, run, threads

@tool(
    name="my_scanner",
    category="enum",
    requires=["mytool"],         # Kali binaries it needs
    description="What it does and what each parameter changes (be precise about impact).",
    input_schema={"type": "object",
                  "properties": {"target": {"type": "string", "description": "..."}},
                  "required": ["target"]},
)
async def my_scanner(args: dict) -> str:
    target = require_arg(args, "target")
    check_scope(target)
    return await run(["mytool", "-t", str(threads(args.get("intensity"))), target])
```
It then appears to Spider automatically (with its category and availability) on the next connect.
