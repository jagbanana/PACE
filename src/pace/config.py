"""Per-user vault location config.

When PACE runs as a Cowork plugin, the MCP server is launched once
globally and has no out-of-band way to know which folder is the user's
vault. This module is the resolution-of-record:

Resolution order (first hit wins):

1. ``PACE_ROOT`` env var — manual escape hatch, takes precedence so
   the developer/user can always override.
2. ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` env var — Cowork sets this if
   the user filled in the ``userConfig`` field at install time.
3. ``vault_root`` field in the user config file
   (``%APPDATA%\\pace\\config.json`` on Windows,
   ``~/.config/pace/config.json`` elsewhere) — written by
   ``pace_init`` so onboarding only has to ask once.
4. ``None`` — server returns ``initialized: false`` and the SKILL
   walks the user through ``pace_init(root=...)``.

The CLI and MCP write the same file via :func:`set_vault_root`, so
power users running ``pace init`` and Cowork-driven model invocations
end up in the same state.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "config.json"

_ENV_PACE_ROOT = "PACE_ROOT"
_ENV_PLUGIN_OPTION = "CLAUDE_PLUGIN_OPTION_VAULT_ROOT"


@dataclass(frozen=True)
class ConfigLocation:
    """Where the per-user config lives plus how it was resolved."""

    path: Path
    source: str  # 'env' | 'platform-default'


# ---- Public API ------------------------------------------------------


def user_config_path() -> Path:
    """Return the per-user config-file path for this OS.

    Honors ``XDG_CONFIG_HOME`` on POSIX. Uses ``%APPDATA%`` on Windows
    (falling back to ``~/AppData/Roaming``). The directory isn't
    created here — :func:`set_vault_root` does that on write.
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "pace" / CONFIG_FILENAME

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "pace" / CONFIG_FILENAME


def resolve_vault_root() -> Path | None:
    """Return the vault root per the resolution order documented above.

    Returns ``None`` when no signal points at a vault. Callers that
    require a vault (the MCP server's tool functions) treat this as
    "uninitialized" and surface that to the model.
    """
    for key in (_ENV_PACE_ROOT, _ENV_PLUGIN_OPTION):
        raw = os.environ.get(key)
        if raw:
            candidate = Path(raw).expanduser().resolve()
            return candidate

    cfg = read_config()
    if cfg and cfg.get("vault_root"):
        return Path(cfg["vault_root"]).expanduser().resolve()

    return None


def read_config() -> dict | None:
    """Return the parsed config dict, or ``None`` if absent / unreadable."""
    path = user_config_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Corrupt or unreadable config shouldn't crash startup; treat as
        # absent and let onboarding rewrite it.
        return None


def set_vault_root(root: Path) -> Path:
    """Persist ``root`` as the user's vault location.

    Writes ``vault_root`` to the per-user config file, creating
    parent dirs as needed. Returns the config-file path so callers
    can mention it in user-facing output.
    """
    target_path = user_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_config() or {}
    existing["vault_root"] = str(Path(root).expanduser().resolve())

    # Atomic write so a crash mid-write doesn't leave invalid JSON.
    tmp = target_path.with_name(target_path.name + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target_path)
    return target_path


def clear_vault_root() -> bool:
    """Remove ``vault_root`` from the config (used by tests). Returns
    True when something was actually removed."""
    cfg = read_config()
    if not cfg or "vault_root" not in cfg:
        return False
    cfg.pop("vault_root", None)
    target_path = user_config_path()
    if cfg:
        tmp = target_path.with_name(target_path.name + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        tmp.replace(target_path)
    else:
        target_path.unlink(missing_ok=True)
    return True
