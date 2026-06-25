# SPAIDER Kali MCP server — a self-contained Kali image with the offensive tools + this MCP
# server, pre-configured so it can be built ONCE and shared. Recipients only install the
# SPAIDER client and point it at this container; they don't rebuild anything.
#
# Build once:     docker build -t spider-kali ./kali_server      (or: scripts/share.sh build)
# Run:            docker compose -f kali_server/docker-compose.yml up -d
# Share it:       scripts/share.sh package   ->  spider-kali-image.tar.gz   (docker save+gzip)
#   recipient:    scripts/share.sh load spider-kali-image.tar.gz  &&  compose up -d
#
# Then set SPAIDER's config: "kali": {"enabled": true, "url": "http://<host>:8765/mcp"}.
FROM kalilinux/kali-rolling

LABEL org.opencontainers.image.title="SPAIDER Kali MCP server" \
      org.opencontainers.image.description="Kali offensive toolchain + SPAIDER MCP-over-HTTP server" \
      org.opencontainers.image.source="https://github.com/your-org/spider"

ENV DEBIAN_FRONTEND=noninteractive \
    SPIDER_KALI_WORKDIR=/root/spider \
    PYTHONUNBUFFERED=1

# --- Offensive toolchain backing the registered tools -----------------------------------
# Every binary named in a tool's `requires=[...]` is installed here so the whole toolset is
# "available" out of the box. Tools that are still missing are reported cleanly at runtime
# rather than crashing, so you can trim this list to slim the image if you don't need them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        # recon
        nmap dnsrecon whois whatweb \
        # web
        nikto gobuster ffuf sqlmap wpscan nuclei \
        # api / web app (httpx prober, crawler, param discovery, cmd-injection, WAF fingerprint)
        httpx-toolkit gospider arjun commix wafw00f \
        # network / enum
        enum4linux-ng smbclient snmp \
        sslscan hydra \
        # exploit
        exploitdb metasploit-framework \
    && rm -rf /var/lib/apt/lists/*

# --- PoC/helper runtime (for kali__run_poc and kali__run_command) -----------------------
# Interpreters + common network utilities so PoCs/exploits written by the agent run without
# extra installs. Trim these too if you only run dedicated tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget netcat-traditional iputils-ping \
        perl ruby php-cli nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- Wordlists (gobuster / ffuf / hydra need these) -------------------------------------
# Pre-installed so directory/credential tooling works immediately. This is the bulk of the
# image size — remove this stage if you'll supply your own wordlists.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wordlists seclists \
    && rm -rf /var/lib/apt/lists/* \
    && [ -f /usr/share/wordlists/rockyou.txt.gz ] && gunzip -kf /usr/share/wordlists/rockyou.txt.gz || true

# --- Pre-warm tool data so first use needs no network -----------------------------------
# Best-effort (|| true): fetch nuclei templates and build the Metasploit module cache at
# BUILD time, so the shared image is genuinely "ready" offline.
RUN nuclei -update-templates 2>/dev/null || true
RUN msfconsole -q -x "version; exit" 2>/dev/null || true

# --- The MCP server ----------------------------------------------------------------------
WORKDIR /opt/spider
COPY requirements.txt /opt/spider/kali_server/requirements.txt
# Bump --build-arg PIP_CACHEBUST=<anything-new> to force a clean dependency reinstall without
# busting the (slow) apt/nuclei/msf layers above — e.g. if a cached pip layer got corrupted.
ARG PIP_CACHEBUST=1
RUN pip3 install --no-cache-dir --break-system-packages -r /opt/spider/kali_server/requirements.txt
COPY . /opt/spider/kali_server

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz').status==200 else 1)" || exit 1
CMD ["python3", "-m", "kali_server.run", "--host", "0.0.0.0", "--port", "8765"]
