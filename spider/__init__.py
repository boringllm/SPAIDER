"""SPAIDER — LLM-driven autonomous penetration-testing framework.

A multi-agent system where specialised agents (recon, web, network, exploitation,
post-exploitation, reporting, …) collaborate under an orchestrator to carry out an
authorised penetration test. SPAIDER keeps a human in the loop: plans can require operator
sign-off, tool execution is gated by a customisable approval policy, and the operator can
interject at any time to ask questions or redirect the engagement.

Offensive tooling runs inside a dedicated Kali container exposed to SPAIDER as an
MCP-over-HTTP server (see the `kali_server/` project), so the agents drive real tools
(nmap, nikto, gobuster, sqlmap, hydra, …) with carefully described parameters and a
selectable intensity level.
"""

__version__ = "0.1.0"
