# Network Testing Skill
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
