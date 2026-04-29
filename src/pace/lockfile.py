"""Cross-process lock guarding maintenance runs.

Per PRD §7.3, daily compaction and weekly review must never overlap —
they can produce conflicting writes against ``working_memory.md`` and
the long-term store. A single advisory lock at ``system/.pace.lock``
serializes them; capture/search aren't gated by this lock since they
are short single-file writes that SQLite WAL mode handles cleanly.

The lock is non-blocking: if held, ``acquire_pace_lock`` raises
:class:`PaceLockBusy` immediately. Callers (CLI, scheduled tasks)
surface that to the user/log rather than waiting indefinitely.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import portalocker

from pace.paths import LOCKFILE


class PaceLockBusy(RuntimeError):
    """Another PACE maintenance task already holds the lock."""


@contextmanager
def acquire_pace_lock(root: Path) -> Iterator[Path]:
    """Hold the vault's ``system/.pace.lock`` for the duration of the block.

    Yields the lock path. Raises :class:`PaceLockBusy` if the lock is
    already held — schedulers can catch this and retry on the next slot.
    """
    lock_path = root / LOCKFILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open in append mode so the file is created if missing without
    # truncating any state another holder may have written.
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        try:
            portalocker.lock(
                fh,
                portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
            )
        except portalocker.LockException as exc:
            raise PaceLockBusy(
                f"Another PACE maintenance task already holds {lock_path}."
            ) from exc
        try:
            yield lock_path
        finally:
            portalocker.unlock(fh)
    finally:
        fh.close()
