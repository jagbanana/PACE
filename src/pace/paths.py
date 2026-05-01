"""Vault path resolution.

A *vault* is a directory containing the runtime PACE structure
(``memories/``, ``projects/``, ``system/``). PACE supports **multiple
vaults on the same machine** — each in its own folder, each with its
own per-vault ``.mcp.json`` baking ``PACE_ROOT`` into the MCP server's
environment.

The vault root for the current process is found by this resolution
chain (first hit wins):

1. ``PACE_ROOT`` env var — set by every initialized vault's per-vault
   ``.mcp.json``. Strongest signal; if it points at an initialized
   vault, that's the answer.
2. ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` env var (Cowork userConfig).
3. **Walk up from cwd** looking for ``system/pace_index.db``. This
   binds the MCP server to whatever folder Claude Code opened —
   essential for multi-vault: a session opened in folder *A* must
   never accidentally resolve to vault *B*.
4. The per-user config file (``%APPDATA%\\pace\\config.json`` on
   Windows, ``~/.config/pace/config.json`` elsewhere). Used **only by
   the CLI** as a fallback when invoked from a folder that isn't
   itself part of any vault. The MCP server skips this step (passes
   ``use_user_config=False``); otherwise opening a brand-new folder
   to set up a *second* vault would resolve to whichever vault
   happens to be the current default.

For ``pace init`` (which creates a new vault) the caller passes the
target directory explicitly — vault detection isn't used.
"""

from __future__ import annotations

from pathlib import Path

from pace import config as pace_config


class VaultNotFoundError(RuntimeError):
    """Raised when a command requires an initialized vault but none is found."""


# Path components, relative to the vault root.
SYSTEM_DIR = "system"
INDEX_DB = "system/pace_index.db"
LOGS_DIR = "system/logs"
LOCKFILE = "system/.pace.lock"
MEMORIES_DIR = "memories"
WORKING_MEMORY = "memories/working_memory.md"
LONG_TERM_DIR = "memories/long_term"
ARCHIVED_DIR = "memories/archived"
PROJECTS_DIR = "projects"
FOLLOWUPS_DIR = "followups"
FOLLOWUPS_DONE_DIR = "followups/done"


def find_vault_root(
    start: Path | None = None, *, use_user_config: bool = True
) -> Path | None:
    """Return the vault root for the current process, or ``None``.

    Resolution order (first hit wins):

    1. ``PACE_ROOT`` env var (the strongest signal; per-vault
       ``.mcp.json`` files set this on every Claude Code session).
    2. ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` env var.
    3. Walk up from ``start`` (or cwd) looking for
       ``system/pace_index.db``.
    4. Per-user config file (``%APPDATA%\\pace\\config.json`` etc.) —
       skipped when ``use_user_config=False``.

    Args:
        start: starting directory for the cwd walk-up.
        use_user_config: when ``False``, skip step 4. The MCP server
            passes ``False`` so multi-vault sessions stay strictly
            bound to the folder Claude Code opened. The CLI uses the
            default (``True``) so power users can run ``pace status``
            from anywhere and still hit their vault.

    For env-var matches (steps 1 & 2) and user-config matches (step 4),
    the candidate is only returned if it points at an *initialized*
    vault; otherwise we keep looking instead of silently using a stale
    pointer.
    """
    for path in _explicit_overrides():
        return path if (path / INDEX_DB).is_file() else None

    cur = (start or Path.cwd()).resolve()
    for path in [cur, *cur.parents]:
        if (path / INDEX_DB).is_file():
            return path

    if use_user_config:
        cfg_root = pace_config.resolve_vault_root(use_user_config=True)
        if cfg_root is not None:
            return cfg_root if (cfg_root / INDEX_DB).is_file() else None

    return None


def _explicit_overrides():
    """Yield env-var-derived vault roots in priority order, if any.

    Mirrors the env-var portion of :func:`pace.config.resolve_vault_root`
    but is used here so the cwd walk-up can run before the user-config
    fallback without duplicating env-var logic.
    """
    cfg_root = pace_config.resolve_vault_root(use_user_config=False)
    if cfg_root is not None:
        yield cfg_root


def require_vault_root(start: Path | None = None) -> Path:
    """Like :func:`find_vault_root` but raise if no vault is found."""
    root = find_vault_root(start)
    if root is None:
        raise VaultNotFoundError(
            "No initialized PACE vault found. Run `pace init` to create one."
        )
    return root


def is_initialized(root: Path) -> bool:
    """Return True if ``root`` looks like an initialized vault."""
    return (root / INDEX_DB).is_file()
