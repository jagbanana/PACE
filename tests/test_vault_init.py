"""``pace init`` scaffolding behavior."""

from __future__ import annotations

from pathlib import Path

from pace import vault as vault_ops
from pace.paths import (
    ARCHIVED_DIR,
    INDEX_DB,
    LONG_TERM_DIR,
    PROJECTS_DIR,
    SYSTEM_DIR,
    WORKING_MEMORY,
    is_initialized,
)


def test_init_creates_expected_tree(tmp_path: Path) -> None:
    result = vault_ops.init(tmp_path)
    assert result.root == tmp_path.resolve()
    assert is_initialized(tmp_path)
    for rel in (LONG_TERM_DIR, ARCHIVED_DIR, PROJECTS_DIR, SYSTEM_DIR):
        assert (tmp_path / rel).is_dir()
    assert (tmp_path / WORKING_MEMORY).is_file()
    assert (tmp_path / INDEX_DB).is_file()
    assert (tmp_path / ".gitignore").is_file()


def test_init_is_idempotent(tmp_path: Path) -> None:
    first = vault_ops.init(tmp_path)
    assert first.created_files  # something was created on the first run

    second = vault_ops.init(tmp_path)
    assert second.already_initialized
    assert second.created_dirs == []
    assert second.created_files == []


def test_init_does_not_clobber_existing_working_memory(tmp_path: Path) -> None:
    vault_ops.init(tmp_path)
    wm = tmp_path / WORKING_MEMORY
    sentinel = "## sentinel entry — keep me\n\nUser-entered text.\n"
    existing = wm.read_text(encoding="utf-8") + sentinel
    wm.write_text(existing, encoding="utf-8")

    vault_ops.init(tmp_path)  # second init must be a no-op for existing files
    assert sentinel in wm.read_text(encoding="utf-8")
