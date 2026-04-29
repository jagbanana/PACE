"""I/O helpers, kept tiny.

Atomic write semantics matter for OneDrive: a half-written file mid-sync
can produce a ``* (Conflicted Copy *).md``. Writing to a temp file in the
same directory and renaming over the target avoids that.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically.

    The file is first written to ``<path>.tmp`` in the same directory, fsynced,
    and then renamed over the destination. The same-directory invariant matters
    — ``Path.replace`` is only atomic on the same filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # Always normalize to LF on disk; downstream tools (git, Obsidian) cope
    # better than with mixed endings.
    with open(tmp, "w", encoding=encoding, newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
