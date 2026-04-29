"""Vault path resolution.

A *vault* is a directory containing the runtime PACE structure
(``memories/``, ``projects/``, ``system/``). The vault root is found by
the following resolution chain (first hit wins):

1. ``PACE_ROOT`` env var (handled by :func:`pace.config.resolve_vault_root`).
2. ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` env var (set by Cowork when the
   plugin's userConfig is filled at install time).
3. The per-user config file written by ``pace init``.
4. Walking up from the current working directory looking for
   ``system/pace_index.db`` (legacy / Claude-Code workflow).

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


def find_vault_root(start: Path | None = None) -> Path | None:
    """Return the vault root for the current process, or ``None``.

    Resolution order:

    1. If :func:`pace.config.resolve_vault_root` returns a path — meaning
       the user/admin has explicitly designated a vault via env var or
       config file — that's the authoritative answer. Return it iff it
       points at an initialized vault; never silently fall through to a
       different folder when an explicit override is set.
    2. Walk up from ``start`` (or cwd) looking for
       ``system/pace_index.db``. Used only when there's no explicit
       override — preserves the original Claude-Code workflow where the
       user opens the vault folder directly.
    """
    explicit = pace_config.resolve_vault_root()
    if explicit is not None:
        return explicit if (explicit / INDEX_DB).is_file() else None

    cur = (start or Path.cwd()).resolve()
    for path in [cur, *cur.parents]:
        if (path / INDEX_DB).is_file():
            return path
    return None


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
