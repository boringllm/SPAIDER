# Web Application Testing Skill
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
