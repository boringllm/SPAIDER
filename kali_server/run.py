"""Entry point for the SPAIDER Kali MCP server. Run this INSIDE your Kali container.

    python -m kali_server.run --host 0.0.0.0 --port 8765

Then point SPAIDER's config `kali.url` at  http://<kali-host>:8765/mcp

Environment variables:
    SPIDER_KALI_TOKEN        require this bearer token on every request (recommended)
    SPIDER_SCOPE             comma-separated hosts/CIDRs; tools refuse targets outside it
    SPIDER_KALI_WORKDIR      working dir for the generic terminal/file tools (default /root/spider)
    SPIDER_KALI_MAX_PARALLEL max tool subprocesses running at once across all sessions (default 8;
                             0 = unlimited). Excess tool calls queue so the container isn't swamped.
"""
from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="SPAIDER Kali MCP server")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    print(f"SPAIDER Kali MCP server -> http://{args.host}:{args.port}/mcp  (status page at / )", flush=True)
    uvicorn.run("kali_server.server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
