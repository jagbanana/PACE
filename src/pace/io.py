"""I/O helpers, kept tiny.

Atomic write semantics matter for OneDrive: a half-written file mid-sync
can produce a ``* (Conflicted Copy *).md``. Writing to a temp file in the
same directory and renaming over the target avoids that.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# The rename step can transiently fail on Windows when OneDrive, Windows
# Defender, or the Search indexer briefly holds the temp or destination
# file (``PermissionError`` / ``WinError 5`` / sharing violations). PRD
# §7.3 calls for retry-with-backoff on vault writes; these constants
# implement it. Worst-case total wait ≈ 0.75s before giving up.
_REPLACE_ATTEMPTS = 5
_REPLACE_BASE_DELAY_S = 0.05


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically.

    The file is first written to ``<path>.tmp`` in the same directory, fsynced,
    and then renamed over the destination. The same-directory invariant matters
    — ``Path.replace`` is only atomic on the same filesystem.

    The final rename is retried with backoff: on Windows a sync/AV/indexer
    process can hold the file open for a few hundred milliseconds, and a
    single ``os.replace`` would otherwise fail the whole write (losing a
    capture or compaction). The temp file's contents are already fsynced,
    so retrying the rename is safe.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # Always normalize to LF on disk; downstream tools (git, Obsidian) cope
    # better than with mixed endings.
    with open(tmp, "w", encoding=encoding, newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    _replace_with_retry(tmp, path)


def _replace_with_retry(tmp: Path, path: Path) -> None:
    """Rename ``tmp`` over ``path``, retrying transient OS errors with backoff.

    Re-raises the last error if every attempt fails, leaving the fsynced
    temp file in place (its content is intact for post-mortem / next write).
    """
    delay = _REPLACE_BASE_DELAY_S
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except OSError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay *= 2
