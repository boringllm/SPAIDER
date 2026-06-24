"""Static-output-filter tests for the Kali tools.

Each case feeds a representative RAW tool output (several captured live from the tools in the
container; the rest canonical samples) through ``_filters.apply_filter`` and asserts that the
interesting discoveries SURVIVE and the noise is DROPPED. This is the "try them all so the filter
doesn't hinder output quality" check. Run: ``python kali_server/tests/test_filters.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kali_server.tools._filters import apply_filter  # noqa: E402

_passed = 0
_failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}  {detail}")


def case(tool: str, body: str, keep: list[str], drop: list[str]) -> None:
    """Wrap body in a run() header, filter it, and assert keep/drop substrings."""
    raw = f"[cmd] {tool} ...\n[exit=0]\n{body}"
    out = apply_filter(tool, raw)
    for k in keep:
        check(f"{tool}: keeps {k!r}", k in out, f"\n--- got ---\n{out}\n-----------")
    for d in drop:
        check(f"{tool}: drops {d!r}", d not in out, f"\n--- got ---\n{out}\n-----------")


# --- real captured outputs (from the live container) --------------------------------------- #
NMAP = """Starting Nmap 7.99 ( https://nmap.org ) at 2026-06-24 16:03 +0000
Nmap scan report for localhost (127.0.0.1)
Host is up (0.0000020s latency).
Not shown: 99 closed tcp ports (reset)
PORT     STATE SERVICE VERSION
22/tcp   open  ssh     OpenSSH 8.2p1
8000/tcp open  http    SimpleHTTPServer 0.6 (Python 3.13.14)
Service detection performed. Please report any incorrect results at https://nmap.org/submit/ .
Nmap done: 1 IP address (1 host up) scanned in 6.18 seconds"""

WAFW00F = """                   ______
                  /      \\
                 (  Woof! )
                  \\  ____/
                  ,,
~ WAFW00F : v2.4.2 ~
    The Web Application Firewall Fingerprinting Toolkit
[*] Checking http://127.0.0.1:8000
[+] Generic Detection results:
[-] No WAF detected by the generic detection
[~] Number of requests: 7"""

SSLSCAN = """  SSL/TLS Protocols:
SSLv2     disabled
SSLv3     disabled
TLSv1.0   enabled
TLSv1.1   enabled
TLSv1.2   enabled
TLSv1.3   enabled
  Heartbleed:
TLSv1.3 not vulnerable to heartbleed
TLSv1.2 not vulnerable to heartbleed
  Supported Server Cipher(s):
Preferred TLSv1.3  128 bits  TLS_AES_128_GCM_SHA256
Accepted  TLSv1.3  256 bits  TLS_AES_256_GCM_SHA384
Accepted  TLSv1.2  128 bits  AES128-SHA
Accepted  TLSv1.2  256 bits  AES256-GCM-SHA384"""

DNSRECON = """2026-06-24T16:05:26 INFO Starting enumeration for domain: example.com
2026-06-24T16:05:26 INFO std: Performing General Enumeration against: example.com...
2026-06-24T16:05:26 ERROR No answer for DNSSEC query for example.com
2026-06-24T16:05:26 INFO 	 SOA elliott.ns.cloudflare.com 172.64.35.228
2026-06-24T16:05:26 INFO 	 NS hera.ns.cloudflare.com 108.162.192.162
2026-06-24T16:05:26 INFO 	 Bind Version for 172.64.35.228 "2026.6.0"
2026-06-24T16:05:26 INFO 	 A example.com 23.215.0.136
2026-06-24T16:05:26 INFO 	 MX example.com 0 ."""

WHOIS = """   Domain Name: EXAMPLE.COM
   Registrar: RESERVED-Internet Assigned Numbers Authority
   Updated Date: 2026-01-16T18:26:50Z
   Creation Date: 1995-08-14T04:00:00Z
   Name Server: ELLIOTT.NS.CLOUDFLARE.COM
   Name Server: HERA.NS.CLOUDFLARE.COM
   DNSSEC: signedDelegation
>>> Last update of whois database: 2026-06-24T16:05:16Z <<<
NOTICE: The expiration date displayed in this record is the date the
registrar's sponsorship of the domain name registration in the registry is
TERMS OF USE: You are not authorized to access or query our Whois
database through the use of electronic processes that are high-volume and"""

ARJUN = ("\x1b[92m    _\x1b[0m\n"
         "\x1b[1;97m[*]\x1b[0m Scanning 0/1: http://127.0.0.1:8000/\n"
         "\x1b[1;97m[*]\x1b[0m Probing the target for stability\n"
         "\x1b[1;32m[+]\x1b[0m Extracted 1 parameter from response for testing: user\n"
         # arjun overwrites a single progress line with \r — represent that faithfully so the
         # filter's \r-normalisation + token-strip is exercised. Final verdict glued onto the last.
         + "".join(f"\x1b[1;93m[!]\x1b[0m Processing chunks: {i}/103   \r" for i in range(1, 104))
         + "\x1b[1;32m[+]\x1b[0m Parameters found: id, page")

SEARCHSPLOIT = """---------------------------------------------- ---------------------------------
 Exploit Title                                |  Path
---------------------------------------------- ---------------------------------
vsftpd 2.3.4 - Backdoor Command Execution     | unix/remote/49757.py
vsftpd 2.3.4 - Backdoor Command Execution (Me | unix/remote/17491.rb
---------------------------------------------- ---------------------------------
Shellcodes: No Results"""

NUCLEI = """[INF] nuclei-templates are not installed, please update
[ERR] failed to load provider keys got EOF
[INF] Nuclei Engine Version: v3.8.0
[INF] Templates loaded for current scan: 5000
[INF] Running httpx on target
[CVE-2021-26855] [http] [critical] https://host/owa/
[exposed-git] [http] [medium] https://host/.git/config"""

# --- canonical representative outputs ------------------------------------------------------ #
SQLMAP = """[*] starting @ 12:00:00 /2024-01-01/
[12:00:01] [INFO] testing connection to the target URL
[12:00:02] [INFO] testing if the target URL content is stable
[12:00:05] [INFO] GET parameter 'id' appears to be 'AND boolean-based blind' injectable
[12:00:10] [INFO] the back-end DBMS is MySQL
sqlmap identified the following injection point(s):
Parameter: id (GET)
    Type: boolean-based blind
    Title: AND boolean-based blind - WHERE or HAVING clause
    Payload: id=1 AND 1234=1234
available databases [2]:
[*] information_schema
[*] shop
[*] ending @ 12:00:12"""

HYDRA = """Hydra v9.5 starting at 2024-01-01
[DATA] max 4 tasks per 1 server, overall 4 tasks, 100 login tries
[DATA] attacking ssh://10.0.0.5:22/
[STATUS] 100.00 tries/min, 100 tries in 00:01h
[22][ssh] host: 10.0.0.5   login: root   password: toor
1 of 1 target successfully completed, 1 valid password found
Hydra finished at 2024-01-01"""

METASPLOIT = """[*] Starting persistent handler(s)...
RHOSTS => 10.0.0.5
[*] 10.0.0.5:445 - Using auxiliary/scanner/smb/smb_ms17_010
[+] 10.0.0.5:445 - Host is likely VULNERABLE to MS17-010! - Windows 7
[*] 10.0.0.5:445 - Scanned 1 of 1 hosts (100% complete)
[*] Auxiliary module execution completed"""

ENUM4LINUX = """ENUM4LINUX - next generation
 ==========================
 |    Target Information    |
 ==========================
[*] Target ........... 10.0.0.5
[*] Username ......... ''
[+] Found 3 users:
administrator (RID 500)
guest (RID 501)
[+] Enumerating shares
ADMIN$  Disk  Remote Admin"""

SMBCLIENT = """WARNING: The "syslog" option is deprecated
Anonymous login successful
Sharename       Type      Comment
Disk|ADMIN$|Remote Admin
Disk|backups|World readable backup share
IPC|IPC$|Remote IPC
Reconnecting with SMB1 for workgroup listing.
Unable to connect with SMB1 -- no workgroup available"""

WPSCAN = """_______________________________________________________________
WordPress Security Scanner by the WPScan Team
_______________________________________________________________
[+] URL: http://blog.tld/ [10.0.0.5]
[+] Started: Mon Jan 1
[i] Plugin(s) Identified:
[+] akismet
 | Version: 4.0 (80% confidence)
[!] Title: Akismet <= 4.0 - Cross-Site Scripting (XSS)
 | Fixed in: 4.1
[+] Checking Plugin Versions (via Passive and Aggressive Methods)
[+] Finished: Mon Jan 1"""

COMMIX = """[*] Checking connection to the target URL... [ SUCCEED ]
[*] Setting the GET parameter 'addr' for tests.
[*] Performing heuristic basic checks.
[+] The GET parameter 'addr' seems injectable via (results-based) classic command injection technique.
    Payload: ;echo COMMIXTEST
[!] Note: Do you want a Pseudo-Terminal shell?"""

NIKTO = """- Nikto v2.5.0
+ Target IP:          10.0.0.5
+ Target Hostname:    blog.tld
+ Target Port:        80
+ Start Time:         2024-01-01
+ Server: Apache/2.4.49
+ /admin/: Admin login page/section found.
+ OSVDB-3233: /icons/README: Apache default file found.
+ 7860 requests: 0 error(s) and 2 item(s) reported on remote host
+ End Time:           2024-01-01"""

GOSPIDER = """[INFO] Start crawling: http://host
[url] - [code-200] - http://host/
[href] - http://host/api/v1/users
[form] - http://host/login
[javascript] - http://host/static/app.js
[url] - [code-200] - http://host/
[linkfinder] - http://host/api/v1/orders"""


def main() -> int:
    print("== Kali output-filter tests ==")
    case("nmap_scan", NMAP,
         keep=["22/tcp   open  ssh", "8000/tcp open  http", "Nmap scan report", "Host is up"],
         drop=["Starting Nmap", "Not shown", "Service detection performed", "Nmap done"])
    case("waf_detect", WAFW00F,
         keep=["[*] Checking", "Generic Detection", "No WAF detected", "[~] Number"],
         drop=["Woof!", "Fingerprinting Toolkit"])
    case("ssl_scan", SSLSCAN,
         keep=["TLSv1.0   enabled", "TLSv1.1   enabled", "Heartbleed:", "Preferred TLSv1.3"],
         drop=["SSLv2     disabled", "not vulnerable to heartbleed", "AES256-GCM-SHA384"])
    case("dns_enum", DNSRECON,
         keep=["SOA elliott.ns.cloudflare.com", "NS hera.ns.cloudflare.com", "A example.com 23.215.0.136"],
         drop=["Bind Version", "Performing General", "Starting enumeration"])
    case("whois_lookup", WHOIS,
         keep=["Domain Name: EXAMPLE.COM", "Name Server: ELLIOTT", "Creation Date"],
         drop=["TERMS OF USE", "NOTICE:", ">>> Last update"])
    case("param_discover", ARJUN,
         keep=["Extracted 1 parameter", "Parameters found: id, page"],
         drop=["Processing chunks", "Scanning 0/1", "Probing the target"])
    case("searchsploit", SEARCHSPLOIT,
         keep=["49757.py", "17491.rb", "Exploit Title"],
         drop=["---------------------------------------------- ------"])
    case("nuclei_scan", NUCLEI,
         keep=["[CVE-2021-26855]", "[exposed-git]"],
         drop=["[INF]", "[ERR]", "Templates loaded"])
    case("sqlmap_test", SQLMAP,
         keep=["Parameter: id (GET)", "Payload: id=1 AND 1234=1234", "back-end DBMS is MySQL",
               "available databases [2]", "[*] shop"],
         drop=["testing connection to the target URL", "starting @", "ending @"])
    case("hydra_bruteforce", HYDRA,
         keep=["login: root   password: toor", "1 valid password found"],
         drop=["[STATUS] 100.00", "[DATA] max 4 tasks", "Hydra v9.5 starting"])
    case("metasploit_run", METASPLOIT,
         keep=["VULNERABLE to MS17-010", "Using auxiliary/scanner/smb"],
         drop=["Starting persistent handler", "execution completed"])
    case("enum4linux", ENUM4LINUX,
         keep=["Found 3 users", "administrator (RID 500)", "ADMIN$  Disk  Remote Admin"],
         drop=["[*] Target", "[*] Username"])
    case("smb_list_shares", SMBCLIENT,
         keep=["Disk|backups|World readable backup share", "Disk|ADMIN$"],
         drop=["Reconnecting with SMB1", "syslog", "Anonymous login successful"])
    case("wpscan_scan", WPSCAN,
         keep=["Akismet <= 4.0 - Cross-Site Scripting (XSS)", "[+] akismet", "Version: 4.0"],
         drop=["WordPress Security Scanner by the WPScan Team", "[+] Checking Plugin Versions"])
    case("commix_test", COMMIX,
         keep=["seems injectable via (results-based) classic command injection", "Payload: ;echo COMMIXTEST"],
         drop=["Checking connection to the target URL", "Performing heuristic basic checks"])
    case("nikto_scan", NIKTO,
         keep=["/admin/: Admin login page/section found.", "OSVDB-3233", "Server: Apache/2.4.49"],
         drop=["Target IP:", "Start Time:", "item(s) reported"])
    case("web_crawl", GOSPIDER,
         keep=["http://host/api/v1/users", "http://host/login", "http://host/api/v1/orders"],
         drop=["[INFO] Start crawling"])

    # raw=true bypasses filtering entirely (agent escape hatch)
    filtered = apply_filter("nmap_scan", f"[cmd] x\n[exit=0]\n{NMAP}")
    full = "[cmd] x\n[exit=0]\n" + NMAP
    check("filter footer present when filtered", "[output filtered:" in filtered)
    check("unknown tool passes through unchanged", apply_filter("not_a_tool", full) == full)

    # registry wiring: raw flag + global toggle both bypass filtering.
    from kali_server.registry import _maybe_filter
    from kali_server.tools._procs import CURRENT_META
    CURRENT_META.set({"filter": True})
    check("registry filters by default", "[output filtered:" in _maybe_filter("nmap_scan", full, raw=False))
    check("raw=true bypasses at registry", _maybe_filter("nmap_scan", full, raw=True) == full)
    CURRENT_META.set({"filter": False})
    check("global toggle off bypasses", _maybe_filter("nmap_scan", full, raw=False) == full)
    CURRENT_META.set({})

    print(f"\n== {_passed}/{_passed + _failed} checks passed ==")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
