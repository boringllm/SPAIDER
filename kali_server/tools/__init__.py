"""Importing this package registers every Kali tool with the registry.

To add a new tool: create/extend a module here, decorate your async handler with
``@tool(...)`` from ``kali_server.registry``, and import the module below so it loads."""
from . import access, api_web, network, recon, terminal, web  # noqa: F401  (import for side effects)

__all__ = ["recon", "web", "api_web", "network", "access", "terminal"]
