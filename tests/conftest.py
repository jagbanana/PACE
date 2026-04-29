"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pace import vault as vault_ops
from pace.index import Index
from pace.paths import INDEX_DB


@pytest.fixture(autouse=True)
def _isolate_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redirect ``%APPDATA%`` / ``XDG_CONFIG_HOME`` so vault.init's call to
    ``pace.config.set_vault_root`` doesn't pollute the developer's real
    user-config file. Each test session gets its own config dir.

    Also unset ``PACE_ROOT`` and ``CLAUDE_PLUGIN_OPTION_VAULT_ROOT`` by
    default so explicit-override tests start from a clean slate.
    """
    config_home = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("APPDATA", str(config_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("PACE_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_VAULT_ROOT", raising=False)


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
