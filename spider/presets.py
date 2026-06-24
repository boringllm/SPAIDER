"""Model parameter presets: named, reusable model configurations stored separately
from the main config (`config/model_presets.json`).

A preset is a snapshot of a model config's tunable fields (provider, model, base_url,
sampling/thinking params, timeouts, etc.). From the UI you can save an agent's current
parameters as a preset, apply a preset to any agent, edit it (apply -> change -> re-save),
and delete it. Applying a preset copies its fields into that agent's model config; the
agent still keeps its own per-agent settings unless overwritten."""
from __future__ import annotations

import json

from . import config as cfg_mod

PRESETS_FILE = cfg_mod.CONFIG_DIR / "model_presets.json"


def _allowed_fields() -> set[str]:
    """The set of model-config keys a preset may contain (mirrors _default_model_config),
    so upsert can strip anything that isn't a real tunable field."""
    return set(cfg_mod._default_model_config("orchestrator").keys())


def load_presets() -> dict[str, dict]:
    """Read all saved presets ({name: params}) from config/model_presets.json (empty if
    missing or unparseable)."""
    if PRESETS_FILE.exists():
        try:
            data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
            return data.get("presets", {}) if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_presets(presets: dict[str, dict]) -> None:
    """Write the full preset map back to config/model_presets.json."""
    cfg_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")


def upsert_preset(name: str, params: dict) -> dict[str, dict]:
    """Create or overwrite a named preset, keeping only valid model-config fields, then
    save. Returns the updated preset map."""
    name = (name or "").strip()
    if not name:
        raise ValueError("preset name is required")
    allowed = _allowed_fields()
    presets = load_presets()
    presets[name] = {k: v for k, v in (params or {}).items() if k in allowed}
    save_presets(presets)
    return presets


def delete_preset(name: str) -> dict[str, dict]:
    """Remove a preset by name (no-op if absent) and save. Returns the updated map."""
    presets = load_presets()
    presets.pop(name, None)
    save_presets(presets)
    return presets
