"""Agent skills: optional markdown playbooks that augment an agent's system prompt.

Skills live as plain `.md` files in the `skills/` folder (next to the package, or
beside the exe when frozen). A `MASTER.md` index describes what each skill teaches.
The user edits skill files directly in the folder — the UI only lists them and lets
you choose, per agent, which skills to load. Selected skills are appended to that
agent's system prompt at spawn time. Skills are optional; an agent may load none."""
from __future__ import annotations

from pathlib import Path

from . import config as cfg_mod

SKILLS_DIR = cfg_mod.BASE_DIR / "skills"
MASTER_FILE = "MASTER.md"


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return ""


def _first_blockquote(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">"):
            return s.lstrip(">").strip()
    return ""


def list_skills() -> list[dict]:
    """Available skills: {name, title, description}. `name` is the file stem."""
    ensure_scaffold()
    out: list[dict] = []
    for p in sorted(SKILLS_DIR.glob("*.md")):
        if p.name == MASTER_FILE:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        out.append({
            "name": p.stem,
            "title": _first_heading(text) or p.stem,
            "description": _first_blockquote(text),
        })
    return out


MODES = ("always", "optional", "never")


def resolve_skill_modes(cfg: dict, role: str) -> dict[str, str]:
    """Per-skill load mode for a role: 'always' (static), 'optional' (the agent may load
    it on demand), or 'never'. Accepts the modern dict form ``{skill: mode}`` and the
    legacy list form (listed = always, others = optional). Unspecified skills default to
    'optional' so agents can pull in any relevant skill unless told otherwise."""
    available = [s["name"] for s in list_skills()]
    raw = (cfg.get("agent_skills", {}) or {}).get(role)
    modes: dict[str, str] = {}
    if isinstance(raw, dict):
        for s in available:
            m = raw.get(s, "optional")
            modes[s] = m if m in MODES else "optional"
    elif isinstance(raw, list):
        for s in available:
            modes[s] = "always" if s in raw else "optional"
    else:
        defaults = cfg_mod.DEFAULT_AGENT_SKILLS.get(role, [])
        for s in available:
            modes[s] = "always" if s in defaults else "optional"
    return modes


def read_skill(name: str) -> str:
    p = SKILLS_DIR / f"{name}.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def master() -> str:
    p = SKILLS_DIR / MASTER_FILE
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def skill_text_for(names: list[str] | None) -> str:
    """Concatenated content of the named skills (skipping missing/empty ones)."""
    parts: list[str] = []
    for n in names or []:
        t = read_skill(n).strip()
        if t:
            parts.append(t)
    return "\n\n---\n\n".join(parts)


def ensure_scaffold() -> None:
    """Create the skills folder, master index, and default skill files if missing.
    Never overwrites an existing file, so user edits in the folder are preserved."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    master_path = SKILLS_DIR / MASTER_FILE
    if not master_path.exists():
        master_path.write_text(_MASTER, encoding="utf-8")
    for name, body in _DEFAULT_SKILLS.items():
        p = SKILLS_DIR / f"{name}.md"
        if not p.exists():
            p.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Default skill content (seed only — edit the files in skills/ to customise).
# --------------------------------------------------------------------------- #
_MASTER = """# SPAIDER Agent Skills — Master Index

Skills are optional markdown playbooks that augment an agent's system prompt with concrete
penetration-testing methodology. Assign skills to agents in **Settings → Agents & skills**.
Each skill is one `.md` file in this folder; **edit the files directly here** to change what a
skill teaches (the UI does not edit skill bodies, only selects them).

A skill file starts with an `# H1 Title` and a `> one-line description` (shown in the UI),
followed by the guidance body that gets appended to the agent's prompt.

## Available skills

- **pentest_orchestration.md** — Planning, scoping, sign-off and delegation for the pentest lead.
- **recon_methodology.md** — Methodical reconnaissance and attack-surface mapping.
- **web_app_testing.md** — OWASP-style web application testing methodology.
- **network_testing.md** — Network/infrastructure service testing methodology.
- **exploitation.md** — Safe, evidence-driven exploitation of validated findings.
- **post_exploitation.md** — Scoped post-exploitation: privesc, looting, lateral assessment.
- **pentest_reporting.md** — Structuring a clear, evidence-driven pentest report.

To add a skill: drop a new `<name>.md` here, give it an H1 + `>` description, then select it for
the relevant agents in Settings.
"""

_DEFAULT_SKILLS = {
    "pentest_orchestration": """# Pentest Orchestration Skill
> Planning, scoping, sign-off and delegation for the pentest lead.

When driving an engagement:
- Restate the scope and rules of engagement in one line, then call `update_plan` with a
  concrete, ordered plan (recon -> enumeration -> vuln analysis -> exploitation ->
  post-exploitation -> reporting). The operator may need to APPROVE the plan — write it for a
  human to review, and act on the approval/rejection result `update_plan` returns.
- Decompose before delegating. Each `spawn_agent` call carries ONE narrow task, an explicit
  `done_when`, and the `context` the sub-agent needs. Never hand over the whole engagement.
- Typical pipeline: recon (map surface) -> web_app/network (find & confirm issues) ->
  exploitation (only validated, in-scope findings) -> post_exploit (scoped). Keep exploitation
  gated behind validated findings.
- Narrate every meaningful step with `notify_user`, and watch your inbox for operator
  interjections — treat them as authoritative within scope and re-plan if the direction changes.
- Stop when the goal is met or no productive next step remains; commission the report.
""",
    "recon_methodology": """# Recon Methodology Skill
> Methodical reconnaissance and attack-surface mapping.

Work outside-in and quiet-to-loud:
1. Passive first: WHOIS, DNS records, certificate transparency, and technology fingerprints —
   no/low traffic to the target.
2. Host discovery: identify which in-scope hosts are live (nmap ping/-sn) before port scanning.
3. Port & service scan: start with a quick top-ports scan, then targeted `-sV -sC` on the open
   ports. Reserve full (`-p-`) and UDP scans for when they're justified — they are slow and loud.
4. Content/subdomain enumeration on web hosts; fingerprint web tech (whatweb).
- Honour the intensity setting (it maps to nmap -T timing and thread/rate caps). Don't go loud
  by default.
- Write a clear attack-surface map to `memory/` (hosts, ports, services, versions, web tech,
  candidate entry points) and `store_finding` for notable exposures (status='candidate').
- Do NOT exploit — your job is to enumerate and hand a clean map to the other agents.
""",
    "web_app_testing": """# Web Application Testing Skill
> OWASP-style web application testing methodology.

Map first, then test each class deliberately:
- Map the app: crawl/enumerate endpoints, parameters, and forms (browser_open, gobuster/ffuf);
  fingerprint the stack (whatweb / wpscan for WordPress).
- Authentication & sessions: weak credentials, session fixation, missing logout/expiry, JWT/
  cookie flaws.
- Access control / IDOR: change identifiers and roles; verify enforcement server-side.
- Injection: SQLi (sqlmap — start detection-only at low level/risk, escalate only if needed and
  authorised), command/template/XXE injection, and reflected/stored/DOM XSS.
- Also: SSRF, file upload/inclusion, open redirects, CORS misconfig, and exposed secrets/configs.
- Use `http_request` as your repeater to prove issues with exact request/response pairs. Respect
  the intensity (it caps tool threads/rate). A validated finding needs a clean reproduction —
  capture it. Escalate intrusive tests via `ask_parent`.
""",
    "network_testing": """# Network Testing Skill
> Network/infrastructure service testing methodology.

For each in-scope host/service:
- Enumerate deeply by protocol: SMB/RPC (enum4linux, share listing), LDAP, SNMP (snmpwalk with
  common community strings), RDP, databases, mail, and any custom services.
- Check transport security (sslscan) for weak protocols/ciphers and certificate issues.
- Look for default/weak credentials and dangerous misconfigurations; identify known-vulnerable
  service versions (searchsploit on the version strings).
- Credential attacks (hydra) are HIGH IMPACT and noisy and can lock accounts — only with explicit
  authorisation, small targeted lists, and a low intensity. Escalate via `ask_parent` first.
- Capture command output as evidence and record issues with `store_finding`.
""",
    "exploitation": """# Exploitation Skill
> Safe, evidence-driven exploitation of validated findings.

Turn validated findings into demonstrated impact, carefully:
- Only target findings already validated and in scope. Re-read the finding for the exact
  preconditions before acting.
- Prefer the least-destructive path that proves impact (a shell, data read, auth bypass).
  Search for a known exploit (searchsploit/nuclei) before crafting one.
- For Metasploit, run a `check`/scanner module before ever choosing `run`; set RHOSTS to the
  in-scope target only.
- NEVER run a DoS-style or data-destroying exploit, or anything that could damage the target,
  without explicit operator approval — escalate via `ask_parent` first.
- Capture proof: exact module/command, options, and the resulting access/output. Update the
  finding to 'validated' with confirmed impact, or report clearly if exploitation failed.
""",
    "post_exploitation": """# Post-Exploitation Skill
> Scoped post-exploitation: privesc, looting, lateral assessment.

After access is obtained (your brief will include the access details):
- Enumerate locally: users, privileges, running services, scheduled tasks, interesting files,
  stored credentials, and OS/patch level. Use automated checks where available.
- Assess privilege escalation paths and document them with evidence (don't necessarily execute a
  destabilising escalation — proving the path is often enough).
- Assess lateral-movement potential (reachable hosts, reused creds) but do NOT pivot to
  out-of-scope hosts.
- Do NOT exfiltrate real sensitive data, destroy anything, or establish persistence unless the
  rules of engagement explicitly authorise it — escalate via `ask_parent` when unsure.
- Document what an attacker could reach and record findings with evidence.
""",
    "pentest_reporting": """# Pentest Reporting Skill
> Structuring a clear, evidence-driven pentest report.

Write for the operator, grounded strictly in the session data:
- If a template was provided, follow its headings exactly. Otherwise use: Executive Summary,
  Scope & Rules of Engagement, Methodology, Findings, and Conclusion / overall risk.
- For each finding give: title, severity (and CVSS if known), affected asset (host/port/URL/
  parameter), a plain-language description, concrete evidence/PoC (exact request/response or
  command output), business impact, and actionable remediation.
- Separate validated findings from unconfirmed candidates; never present a candidate as proven.
- Pull full detail with the read tools (`read_finding`, workspace `memory/`/`findings/`) — do not
  invent results. Quote evidence rather than paraphrasing it away.
- Keep it skimmable: a short executive summary up top, technical detail below. Match length/tone
  to any audience the operator specified.
""",
}
