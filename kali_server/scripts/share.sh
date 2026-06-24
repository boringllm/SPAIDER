#!/usr/bin/env bash
# Build, package (for sharing), load, and run the pre-configured Spider Kali image.
# Linux/macOS helper. On Windows use scripts/share.ps1.
#
#   ./share.sh build               # build spider-kali:latest from the Dockerfile
#   ./share.sh package             # docker save + gzip -> spider-kali-image.tar.gz (share this)
#   ./share.sh load [file]         # docker load a shared archive (default spider-kali-image.tar.gz)
#   ./share.sh run                 # docker compose up -d (reads .env)
#
# Override defaults with env vars: SPIDER_KALI_IMAGE, SPIDER_KALI_ARCHIVE.
set -euo pipefail

IMAGE="${SPIDER_KALI_IMAGE:-spider-kali:latest}"
ARCHIVE="${SPIDER_KALI_ARCHIVE:-spider-kali-image.tar.gz}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # kali_server/

case "${1:-}" in
  build)
    docker build -t "$IMAGE" "$HERE"
    echo "Built $IMAGE. Next: ./share.sh package  (to share)  or  ./share.sh run  (to start)."
    ;;
  package)
    echo "Saving $IMAGE -> $ARCHIVE (this can take a while for a multi-GB image)..."
    docker save "$IMAGE" | gzip > "$ARCHIVE"
    echo "Wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1)). Send this single file to others."
    ;;
  load)
    f="${2:-$ARCHIVE}"
    echo "Loading image from $f ..."
    gunzip -c "$f" | docker load
    echo "Loaded. Next: cp .env.example .env && edit it, then ./share.sh run."
    ;;
  run)
    cd "$HERE"
    [ -f .env ] || { echo "No .env found — copy .env.example to .env and edit it first."; exit 1; }
    docker compose up -d
    docker compose ps
    echo "MCP endpoint: http://<this-host>:\${SPIDER_KALI_PORT:-8765}/mcp  (point Spider → Settings → Kali at it)"
    ;;
  *)
    echo "Usage: $0 {build|package|load [file]|run}"; exit 1 ;;
esac
