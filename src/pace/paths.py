"""Vault path resolution.

A *vault* is a directory containing the runtime PACE structure
(``memories/``, ``projects/``, ``system/``). The vault root is found by:

1. The ``PACE_ROOT`` environment variable, if set.
2. Walking up from the current working directory looking for
   ``system/pace_index.db``.

For ``pace init`` (which creates a new vault) the caller passes the
target directory explicitly — vault detection isn't used.
"""

from __future__ import annotations

import os
from pathlib import Path


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


def find_vault_root(start: Path | None = None) -> Path | None:
    """Return the vault root containing ``start``, or ``None`` if not found.

    Resolution order: ``PACE_ROOT`` env var → walk up from ``start`` (or cwd)
    looking for ``system/pace_index.db``.
    """
    env = os.environ.get("PACE_ROOT")
    if env:
        candidate = Path(env).expanduser().resolve()
        if (candidate / INDEX_DB).is_file():
            return candidate
        # PACE_ROOT pointing at an uninitialized dir is still a useful answer
        # for `pace init`, but for command resolution we report not-found.
        return None

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
