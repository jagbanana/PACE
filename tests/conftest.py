"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pace import vault as vault_ops
from pace.index import Index
from pace.paths import INDEX_DB


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """An initialized empty vault rooted at a tmp directory."""
    vault_ops.init(tmp_path)
    return tmp_path


@pytest.fixture
def index(vault: Path) -> Iterator[Index]:
    """Open Index for the vault fixture, closed after the test."""
    idx = Index(vault / INDEX_DB)
    try:
        yield idx
    finally:
        idx.close()
