# Build, package (for sharing), load, and run the pre-configured Spider Kali image.
# Windows helper. On Linux/macOS use scripts/share.sh.
#
#   .\share.ps1 build           # build spider-kali:latest from the Dockerfile
#   .\share.ps1 package         # docker save -> spider-kali-image.tar (share this file)
#   .\share.ps1 load [file]     # docker load a shared archive (default spider-kali-image.tar)
#   .\share.ps1 run             # docker compose up -d (reads .env)
#
# Override defaults with env vars: SPIDER_KALI_IMAGE, SPIDER_KALI_ARCHIVE.
param(
  [Parameter(Position = 0)][string]$Cmd,
  [Parameter(Position = 1)][string]$File
)
$ErrorActionPreference = "Stop"

$Image   = if ($env:SPIDER_KALI_IMAGE)   { $env:SPIDER_KALI_IMAGE }   else { "spider-kali:latest" }
$Archive = if ($env:SPIDER_KALI_ARCHIVE) { $env:SPIDER_KALI_ARCHIVE } else { "spider-kali-image.tar" }
$Here    = Split-Path -Parent $PSScriptRoot   # kali_server/

switch ($Cmd) {
  "build" {
    docker build -t $Image $Here
    Write-Host "Built $Image. Next: .\share.ps1 package (to share) or .\share.ps1 run (to start)."
  }
  "package" {
    Write-Host "Saving $Image -> $Archive (this can take a while for a multi-GB image)..."
    docker save -o $Archive $Image
    Write-Host "Wrote $Archive. Send this file to others (optionally compress it first, e.g. with 7-Zip)."
  }
  "load" {
    $f = if ($File) { $File } else { $Archive }
    Write-Host "Loading image from $f ..."
    docker load -i $f
    Write-Host "Loaded. Next: copy .env.example to .env, edit it, then .\share.ps1 run."
  }
  "run" {
    Push-Location $Here
    try {
      if (-not (Test-Path ".env")) { throw "No .env found - copy .env.example to .env and edit it first." }
      docker compose up -d
      docker compose ps
      Write-Host "MCP endpoint: http://<this-host>:<SPIDER_KALI_PORT>/mcp  (point Spider -> Settings -> Kali at it)"
    } finally { Pop-Location }
  }
  default {
    Write-Host "Usage: .\share.ps1 {build|package|load [file]|run}"
  }
}
