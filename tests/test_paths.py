"""Vault path resolution — including multi-vault behavior (v0.3.0+).

The resolution chain in :func:`pace.paths.find_vault_root` is the heart
of multi-vault: get it wrong and a session opened in folder *A* leaks
into vault *B*. These tests cover each step of the chain in isolation,
plus the realistic two-vault scenarios that motivated the change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import config as pace_config
from pace import paths
from pace import vault as vault_ops


def _init(root: Path) -> Path:
    """Init a vault at ``root`` and return the resolved path."""
    vault_ops.init(root)
    return root.resolve()


# ---- Single-vault baselines ------------------------------------------


def test_pace_root_env_pins_session_to_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strongest signal: per-vault .mcp.json sets PACE_ROOT, and that
    must beat both cwd walk-up and the user-config fallback."""
    pinned = _init(tmp_path / "pinned")
    decoy = _init(tmp_path / "decoy")
    pace_config.set_vault_root(decoy)

    monkeypatch.setenv("PACE_ROOT", str(pinned))
    # Walk-up from inside the decoy folder — env still wins.
    monkeypatch.chdir(decoy)

    assert paths.find_vault_root() == pinned


def test_pace_root_env_pointing_at_uninitialized_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale env override (folder isn't a vault) must not silently fall
    through to a different vault — the user expects the env override to
    be authoritative."""
    pace_config.set_vault_root(_init(tmp_path / "real"))
    monkeypatch.setenv("PACE_ROOT", str(tmp_path / "not-a-vault"))
    assert paths.find_vault_root() is None


def test_cwd_walkup_finds_vault_when_in_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standard Claude-Code workflow: open a vault folder, the MCP server
    walks up from its cwd and finds system/pace_index.db."""
    vault_root = _init(tmp_path / "my-vault")
    sub = vault_root / "memories"  # vault.init created this
    monkeypatch.chdir(sub)
    assert paths.find_vault_root() == vault_root


# ---- Multi-vault: cwd walk-up beats user config ----------------------


def test_cwd_walkup_beats_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the user has Misa as their default and opens Bob in Claude
    Code, find_vault_root must return Bob (cwd) — not Misa (config)."""
    misa = _init(tmp_path / "misa")
    bob = _init(tmp_path / "bob")
    pace_config.set_vault_root(misa)

    monkeypatch.chdir(bob)
    assert paths.find_vault_root() == bob


def test_user_config_used_only_when_cwd_has_no_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 4 of the chain: cwd doesn't sit inside any vault, so the
    user-config pointer is the last resort. CLI invocations from the
    user's home dir or random project folders rely on this."""
    misa = _init(tmp_path / "misa")
    pace_config.set_vault_root(misa)

    orphan = tmp_path / "unrelated-project"
    orphan.mkdir()
    monkeypatch.chdir(orphan)
    assert paths.find_vault_root() == misa


# ---- The MCP-server case: use_user_config=False ----------------------


def test_mcp_server_skips_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the multi-vault feature: when a brand-new
    folder is opened in Claude Code (no ``.mcp.json`` yet, not under any
    existing vault), the MCP server must report ``initialized: false``
    so onboarding kicks in *here* instead of resolving to whatever the
    user-config pointer happens to hold."""
    misa = _init(tmp_path / "misa")
    pace_config.set_vault_root(misa)

    fresh = tmp_path / "bob-to-be"
    fresh.mkdir()
    monkeypatch.chdir(fresh)

    # CLI default still finds Misa (use_user_config=True).
    assert paths.find_vault_root() == misa
    # MCP server (use_user_config=False) sees no vault here — exactly
    # what onboarding needs to fire in the right folder.
    assert paths.find_vault_root(use_user_config=False) is None


def test_mcp_server_finds_initialized_vault_via_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MCP server still finds initialized vaults via cwd — just not
    the user-config fallback."""
    misa = _init(tmp_path / "misa")
    bob = _init(tmp_path / "bob")
    pace_config.set_vault_root(misa)

    monkeypatch.chdir(bob)
    assert paths.find_vault_root(use_user_config=False) == bob
