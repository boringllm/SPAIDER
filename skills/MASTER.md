# Spider Agent Skills — Master Index

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
