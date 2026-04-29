"""Lockfile contention — daily and weekly maintenance must not overlap."""

from __future__ import annotations

from pathlib import Path

import pytest

from pace.lockfile import PaceLockBusy, acquire_pace_lock
from pace.paths import LOCKFILE


def test_lock_creates_lockfile_on_first_acquire(tmp_path: Path) -> None:
    with acquire_pace_lock(tmp_path) as lock_path:
        assert lock_path == tmp_path / LOCKFILE
        assert lock_path.is_file()


def test_concurrent_acquire_raises_pace_lock_busy(tmp_path: Path) -> None:
    """A second acquire while the first is held must fail fast — schedulers
    catch this and retry on the next slot rather than wait."""
    with acquire_pace_lock(tmp_path):
        with pytest.raises(PaceLockBusy):
            with acquire_pace_lock(tmp_path):
                pass


def test_lock_released_after_block(tmp_path: Path) -> None:
    """After the with-block exits, the lock is releasable to a new caller."""
    with acquire_pace_lock(tmp_path):
        pass
    # Should re-acquire cleanly.
    with acquire_pace_lock(tmp_path):
        pass
