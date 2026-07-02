"""Atomic write: rename retry-with-backoff (PRD §7.3).

On Windows a sync/AV/indexer process can briefly hold the temp or
destination file, making ``os.replace`` fail transiently. The write
must retry rather than lose a capture/compaction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import io


def test_atomic_write_basic(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    io.atomic_write_text(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"
    # No stray temp left behind.
    assert not target.with_name(target.name + ".tmp").exists()


def test_atomic_write_normalizes_to_lf(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    io.atomic_write_text(target, "a\nb\n")
    assert b"\r\n" not in target.read_bytes()


def test_atomic_write_retries_transient_replace_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail the rename twice, then succeed — content must land intact."""
    target = tmp_path / "note.md"
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky(self: Path, dst) -> None:  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Access is denied")
        real_replace(self, dst)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)  # keep it fast

    io.atomic_write_text(target, "durable")
    assert target.read_text(encoding="utf-8") == "durable"
    assert calls["n"] == 3  # two failures + one success


def test_atomic_write_reraises_when_replace_keeps_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "note.md"

    def always_fail(self: Path, dst) -> None:  # type: ignore[no-untyped-def]
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "replace", always_fail)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(PermissionError):
        io.atomic_write_text(target, "x")
    # The fsynced temp survives so content isn't lost on total failure.
    assert target.with_name(target.name + ".tmp").is_file()


def test_atomic_write_gives_up_after_bounded_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry count is bounded — it doesn't loop forever on a stuck file."""
    calls = {"n": 0}

    def always_fail(self: Path, dst) -> None:  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "replace", always_fail)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    with pytest.raises(PermissionError):
        io.atomic_write_text(tmp_path / "note.md", "x")
    assert calls["n"] == io._REPLACE_ATTEMPTS
