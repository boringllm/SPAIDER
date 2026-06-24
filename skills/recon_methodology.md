# Recon Methodology Skill
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
