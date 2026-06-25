"""Static output filters for the offensive tools — noise reduction for the agents.

Raw tool output is enormous and mostly boilerplate (banners, progress bars, per-cipher dumps,
INFO/DEBUG logs, legal notices...). Feeding all of it to an LLM agent wastes its context and
buries the few lines that actually matter. Each tool here gets a *purely static* filter that
keeps only the interesting discoveries (open ports, found paths, vulnerabilities, credentials,
records, parameters, ...) and drops the rest.

Design / guarantees:
  * **Static only.** No model calls — just line matching / regex. Deterministic and fast.
  * **Lossless escape hatch.** Filtering NEVER destroys data the agent can't get back: an agent
    can re-run any tool with ``raw=true`` to receive the complete unfiltered output, and the
    operator can disable filtering globally (SPAIDER Settings → Output filtering). When disabled
    or ``raw``, ``apply_filter`` is bypassed entirely and the tool output is returned verbatim.
  * **Conservative.** When unsure, keep the line. Tiny outputs (< _MIN_LINES_TO_FILTER lines) and
    error/timeout/killed results are returned untouched. A footer always tells the agent how many
    lines were hidden and how to get the full output, so a filter can never silently mislead.

ADD A FILTER FOR A NEW TOOL: write ``def _f_<x>(lines: list[str]) -> list[str]`` returning the
lines worth keeping, then register it in ``FILTERS`` at the bottom under the tool's name. If a
tool's output is already concise (or agent-generated, like run_command), leave it OUT of FILTERS
— unregistered tools pass through unchanged. See ../README.md "Add a tool" for the full recipe.
"""
from __future__ import annotations

import re
from typing import Callable

# How many non-empty body lines a tool must emit before we bother filtering. Below this the
# output is already small, so filtering risks hiding more than it helps — pass it through.
_MIN_LINES_TO_FILTER = 6

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI colour/escape sequences (many tools colour their output even when piped)."""
    return _ANSI_RE.sub("", text)


def _norm(text: str) -> str:
    """Normalise progress-bar carriage returns to newlines so `\\r`-overwritten progress lines
    (arjun, sqlmap, ...) split into separate lines we can drop individually."""
    return _strip_ansi(text).replace("\r", "\n")


# --------------------------------------------------------------------------- #
# Per-tool filters. Each takes the cleaned body lines and returns the lines to keep.
# --------------------------------------------------------------------------- #
def _f_nmap(lines: list[str]) -> list[str]:
    keep = []
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^\d+/(tcp|udp)\s+", s)
        if m:
            if " open" in s or "open|" in s:          # open / open|filtered ports only
                keep.append(ln)
        elif s.startswith(("Nmap scan report", "Host is up", "PORT ", "Service Info",
                           "OS details", "OS CPE", "Running:", "Device type",
                           "Aggressive OS guesses", "MAC Address", "|", "|_")):
            keep.append(ln)                            # report header, OS/service info, NSE scripts
    return keep


def _f_gobuster(lines: list[str]) -> list[str]:
    # gobuster -q already prints only hits: "path (Status: 301) [Size: 0] [--> /x/]".
    return [ln for ln in lines if "(Status:" in ln or re.match(r"^/\S", ln.strip())]


def _f_ffuf(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("::") or s.startswith("Progress:"):
            continue
        out.append(ln)
    return out


def _f_nikto(lines: list[str]) -> list[str]:
    noise = ("+ Target IP", "+ Target Hostname", "+ Target Port", "+ Start Time",
             "+ End Time", "+ Server: No banner", "host(s) tested", "+ Root page",
             "item(s) reported", "Nikto v", "------")
    out = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("+ "):
            continue
        if any(n in s for n in noise):
            continue
        out.append(ln)
    return out


def _f_sqlmap(lines: list[str]) -> list[str]:
    keep_kw = ("[CRITICAL]", "is vulnerable", "Parameter:", "Type:", "Title:", "Payload:",
               "available databases", "back-end DBMS", "current user", "current database",
               "banner:", "is not injectable", "all tested parameters", "might be injectable",
               "does not seem to be injectable", "WAF/IPS")
    out = []
    for ln in lines:
        s = ln.strip()
        if any(k in s for k in keep_kw):
            out.append(ln)
        elif s.startswith("[*]") and not any(x in s for x in ("starting @", "ending @", "shutting down")):
            out.append(ln)                              # e.g. "[*] dbname" under available databases
    return out


def _f_wpscan(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(("[+]", "[!]", "[i]", "|")):
            # drop pure-progress "[+] Checking..." but keep findings/details
            if s.startswith("[+]") and ("Checking" in s or "requests done" in s or "Using" in s):
                continue
            out.append(ln)
    return out


def _f_dnsrecon(lines: list[str]) -> list[str]:
    out = []
    rec = re.compile(r"\b(SOA|NS|A|AAAA|MX|TXT|CNAME|PTR|SRV|HINFO|SPF|DMARC|Found)\b")
    for ln in lines:
        s = ln.strip()
        if "Bind Version" in s or "Performing" in s or "Starting enumeration" in s:
            continue
        if rec.search(s):
            # strip the "<timestamp> INFO \t" log prefix for readability
            out.append(re.sub(r"^\S+\s+(INFO|WARNING|ERROR)\s+", "", s))
    return out


def _f_whois(lines: list[str]) -> list[str]:
    noise = ("notice", "terms of use", "by submitting", "by the following", "for more information",
             ">>>", "url of the icann", "the data in", "this listing", "please", "we reserve",
             "verisign", "register domain names")
    field = re.compile(r"^\s*[^\s:][^:]{0,40}:\s*\S")
    out = []
    for ln in lines:
        low = ln.strip().lower()
        if not low or low.startswith(("%", "#")):
            continue
        if any(low.startswith(n) for n in noise):
            continue
        if field.match(ln):
            out.append(ln.strip())
    return out


def _f_whatweb(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip()]           # already one concise line per target


def _f_enum4linux(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("[*]"):                # drop progress
            continue
        if set(s) <= set("=-_ "):                       # drop separator rules
            continue
        out.append(ln)
    return out


def _f_smbclient(lines: list[str]) -> list[str]:
    return [ln for ln in lines if "|" in ln or "Sharename" in ln or "Disk" in ln or "IPC" in ln]


def _f_sslscan(lines: list[str]) -> list[str]:
    weak = ("sslv2", "sslv3", "tlsv1.0", "tlsv1.1", "rc4", "3des", " des", "md5", "null",
            "export", "anon", " 56 bits", " 112 bits", " cbc")  # leading space: avoid "256 bits"
    out = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if not s:
            continue
        if s.endswith(":"):                             # section headers (few, give structure)
            out.append(ln); continue
        if low.startswith(("sslv", "tlsv")) and "enabled" in low:
            out.append(ln); continue                    # enabled protocols (weak ones matter)
        if "vulnerable" in low and "not vulnerable" not in low:
            out.append(ln); continue
        if s.startswith("Preferred"):
            out.append(ln); continue
        if s.startswith("Accepted") and any(w in low for w in weak):
            out.append(ln); continue                    # weak accepted ciphers only
        if any(k in low for k in ("subject:", "issuer:", "not valid", "signature algorithm",
                                  "rsa key strength", "expired", "self signed", "self-signed")):
            out.append(ln)
    return out


def _f_searchsploit(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        if set(ln.strip()) <= set("- "):               # drop the dashed table rules
            continue
        out.append(ln)
    return out


def _f_nuclei(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^\[(INF|WRN|ERR|FTL|DBG)\]", s):  # nuclei engine logs -> drop
            continue
        out.append(ln)                                  # findings: "[tmpl-id] [proto] [sev] url"
    return out


def _f_hydra(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if ("login:" in low and "password:" in low) or "valid password found" in low \
           or "valid pair" in low or s.startswith("[ERROR]") or "could not connect" in low:
            out.append(ln)
    return out


def _f_metasploit(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if s.startswith(("[+]", "[-]")):
            out.append(ln)
        elif s.startswith("[*]") and not any(x in low for x in ("starting", "stopping", "exec", "launching")):
            out.append(ln)
        elif any(k in s for k in ("Session ", "session opened", "VULNERABLE", "vulnerable",
                                  "Meterpreter", "shell session", "Command shell")):
            out.append(ln)
    return out


# ---- new API/web tools ---- #
def _f_httpx(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip()]           # one concise line per probed URL


def _f_gospider(lines: list[str]) -> list[str]:
    out, seen = [], set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("[INFO]"):
            continue
        if s.startswith("[ERROR]") and "deadline" in s:
            continue
        if s in seen:                                   # gospider repeats URLs across sources
            continue
        seen.add(s)
        out.append(ln)
    return out


_ARJUN_PROG = re.compile(r"\[!\]\s*Processing chunks:\s*\d+/\d+\s*")


def _f_arjun(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        # arjun often glues its final verdict onto the end of the progress line, so strip the
        # "[!] Processing chunks: N/M" tokens IN PLACE rather than dropping the whole line.
        s = _ARJUN_PROG.sub("", ln).strip()
        if not s or s.startswith("[*]"):
            continue
        if s.startswith("[+]") or "parameter" in s.lower() or "No parameters" in s:
            out.append(s)
    return out


def _f_commix(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if any(k in low for k in ("injectable", "vulnerable", "the value of", "payload",
                                  "command execution", "technique", "type:", "shell")):
            out.append(ln)
        elif s.startswith(("[+]", "[!]")) or "[critical]" in low:
            out.append(ln)
    return out


def _f_wafw00f(lines: list[str]) -> list[str]:
    # Drop the ASCII dog banner; keep the verdict/status lines (prefixed [*]/[+]/[-]/[~]).
    return [ln for ln in lines if ln.strip().startswith(("[*]", "[+]", "[-]", "[~]"))]


# Tool name -> filter. Tools NOT listed here pass through unchanged (already-concise or
# agent-controlled output like run_command / run_poc / write_file / read_file).
FILTERS: dict[str, Callable[[list[str]], list[str]]] = {
    "nmap_scan": _f_nmap,
    "gobuster_dir": _f_gobuster,
    "ffuf_fuzz": _f_ffuf,
    "nikto_scan": _f_nikto,
    "sqlmap_test": _f_sqlmap,
    "wpscan_scan": _f_wpscan,
    "dns_enum": _f_dnsrecon,
    "whois_lookup": _f_whois,
    "whatweb_scan": _f_whatweb,
    "enum4linux": _f_enum4linux,
    "smb_list_shares": _f_smbclient,
    "ssl_scan": _f_sslscan,
    "searchsploit": _f_searchsploit,
    "nuclei_scan": _f_nuclei,
    "hydra_bruteforce": _f_hydra,
    "metasploit_run": _f_metasploit,
    # new API/web tools
    "http_probe": _f_httpx,
    "web_crawl": _f_gospider,
    "param_discover": _f_arjun,
    "commix_test": _f_commix,
    "waf_detect": _f_wafw00f,
}


def has_filter(name: str) -> bool:
    return name in FILTERS


_HEADER_RE = re.compile(r"^\[(cmd|exit)")
# Result markers that must never be filtered (already short + critical context for the agent).
_PASSTHROUGH = ("[error]", "[unavailable]")


def apply_filter(name: str, text: str) -> str:
    """Return ``text`` reduced to its interesting lines, or unchanged when there's no filter for
    ``name`` / the output is tiny / it's an error/timeout/killed result. Always appends a footer
    telling the agent how many lines were hidden and that ``raw=true`` returns everything."""
    fn = FILTERS.get(name)
    if fn is None:
        return text
    stripped = text.lstrip()
    if stripped.startswith(_PASSTHROUGH):
        return text
    if "[KILLED BY OPERATOR" in text or "[timeout after" in text:
        return text  # partial/aborted run — show the agent exactly what happened

    # Split off the run() header ("[cmd] ...", "[exit=N]") from the tool body.
    lines = text.split("\n")
    header, body_start = [], 0
    for i, ln in enumerate(lines):
        if _HEADER_RE.match(ln):
            header.append(ln)
            body_start = i + 1
        else:
            break
    body = "\n".join(lines[body_start:])

    cleaned = _norm(body)
    body_lines = cleaned.split("\n")
    non_empty = [ln for ln in body_lines if ln.strip()]
    if len(non_empty) < _MIN_LINES_TO_FILTER:
        return text  # already concise — nothing worth filtering

    kept = fn(body_lines)
    kept = [ln for ln in kept if ln.strip()]
    hidden = len(non_empty) - len(kept)
    if hidden <= 0:
        return text  # filter kept everything — no point reformatting

    head = "\n".join(header)
    if kept:
        note = (f"[output filtered: {len(kept)} notable line(s) kept, {hidden} hidden — "
                f"re-run with raw=true for the full tool output]")
        joined = "\n".join(kept)
        return f"{head}\n{joined}\n{note}" if head else f"{joined}\n{note}"
    note = (f"[output filtered: no notable findings in {len(non_empty)} lines — "
            f"re-run with raw=true to inspect the full tool output]")
    return f"{head}\n{note}" if head else note
