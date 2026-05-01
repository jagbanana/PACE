"""Per-user vault location config.

PACE supports **multiple vaults on the same machine**, each living in
its own folder. The resolution chain that picks "which vault are we
talking to right now" runs in :func:`pace.paths.find_vault_root`; this
module owns the env-var + persisted-config pieces of it.

Pieces this module contributes (in priority order, first hit wins):

1. ``PACE_ROOT`` env var — strongest signal. Each initialized vault's
   per-vault ``.mcp.json`` bakes ``PACE_ROOT`` into the MCP server's
   environment, so opening that folder in Claude Code always pins the
   server to that vault.
2. ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` env var — Cowork sets this when
   the user fills in the ``userConfig`` field at install time.
3. ``vault_root`` field in the user config file
   (``%APPDATA%\\pace\\config.json`` on Windows,
   ``~/.config/pace/config.json`` elsewhere) — a "default vault" used
   only by the CLI when invoked from a folder that isn't itself a
   vault. The MCP server **does not** consult this file (see
   :func:`pace.paths.find_vault_root`); it would otherwise leak vault
   identity across folders.

The MCP server passes ``use_user_config=False`` to keep multi-vault
sessions strictly bound to the folder Claude Code opened.
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


def resolve_vault_root(*, use_user_config: bool = True) -> Path | None:
    """Return the vault root per the resolution order documented above.

    Args:
        use_user_config: When ``False``, skip the ``%APPDATA%`` /
            ``~/.config`` config file. The MCP server passes ``False``
            so that a session opened in folder *A* never resolves to
            vault *B* just because *B* was the most-recently-initialized
            vault on this machine. The CLI keeps the default ``True``
            so ``pace status`` from any directory still works.

    Returns ``None`` when no signal points at a vault. Callers that
    require a vault treat this as "uninitialized" and surface that to
    the model (or the user, in CLI invocations).
    """
    for key in (_ENV_PACE_ROOT, _ENV_PLUGIN_OPTION):
        raw = os.environ.get(key)
        if raw:
            candidate = Path(raw).expanduser().resolve()
            return candidate

    if use_user_config:
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


def set_vault_root_if_unset(root: Path) -> tuple[Path, bool]:
    """Write ``root`` as the default vault **only if no default is set**.

    Multi-vault use: when the user runs ``pace init`` to create a
    *second* vault, we don't want that init to overwrite the
    user-config pointer to their *first* vault — doing so would
    break ``pace status`` invocations in unrelated folders that were
    relying on the original default.

    Returns ``(config_path, wrote)`` so callers can tell whether the
    file was actually changed.
    """
    target_path = user_config_path()
    existing = read_config() or {}
    if existing.get("vault_root"):
        return target_path, False
    return set_vault_root(root), True


def set_vault_root(root: Path) -> Path:
    """Persist ``root`` as the user's vault location.

    Writes ``vault_root`` to the per-user config file, creating
    parent dirs as needed. Returns the config-file path so callers
    can mention it in user-facing output.

    For first-time use this captures the new vault as the CLI's
    default. Subsequent ``pace init`` calls should use
    :func:`set_vault_root_if_unset` instead so a second vault doesn't
    silently steal the first vault's slot in the user config.
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
