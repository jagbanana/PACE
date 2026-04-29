"""Per-user vault-config resolution and round-trip."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pace import config as pace_config

# ---- user_config_path ------------------------------------------------


def test_user_config_path_uses_appdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-specific path resolution.")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    path = pace_config.user_config_path()
    assert path == tmp_path / "Roaming" / "pace" / "config.json"


def test_user_config_path_honors_xdg_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX-specific path resolution.")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path = pace_config.user_config_path()
    assert path == tmp_path / "xdg" / "pace" / "config.json"


# ---- resolve_vault_root ----------------------------------------------


def test_resolve_returns_none_when_no_signal(tmp_path: Path) -> None:
    # The autouse _isolate_user_config fixture has unset PACE_ROOT and
    # CLAUDE_PLUGIN_OPTION_VAULT_ROOT and pointed the config dir at a
    # fresh tmp_path with no config file written yet.
    assert pace_config.resolve_vault_root() is None


def test_pace_root_env_var_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PACE_ROOT is the explicit override and beats every other source."""
    pace_config.set_vault_root(tmp_path / "config-default")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VAULT_ROOT", str(tmp_path / "plugin"))
    monkeypatch.setenv("PACE_ROOT", str(tmp_path / "explicit"))

    resolved = pace_config.resolve_vault_root()
    assert resolved == (tmp_path / "explicit").resolve()


def test_plugin_option_env_var_beats_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PACE_ROOT is unset, the Cowork-injected env var wins."""
    pace_config.set_vault_root(tmp_path / "config-default")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_VAULT_ROOT", str(tmp_path / "plugin"))

    resolved = pace_config.resolve_vault_root()
    assert resolved == (tmp_path / "plugin").resolve()


def test_falls_back_to_config_file(tmp_path: Path) -> None:
    pace_config.set_vault_root(tmp_path / "from-config")
    resolved = pace_config.resolve_vault_root()
    assert resolved == (tmp_path / "from-config").resolve()


def test_corrupt_config_treated_as_absent(tmp_path: Path) -> None:
    """Corrupt config doesn't crash startup — onboarding rewrites it."""
    cfg_path = pace_config.user_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("not valid json {", encoding="utf-8")
    assert pace_config.resolve_vault_root() is None


# ---- set_vault_root --------------------------------------------------


def test_set_vault_root_writes_atomic(tmp_path: Path) -> None:
    target = tmp_path / "vault"
    config_path = pace_config.set_vault_root(target)

    assert config_path.is_file()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["vault_root"] == str(target.resolve())


def test_set_vault_root_preserves_other_fields(tmp_path: Path) -> None:
    """Future fields in the config file shouldn't be clobbered by writes."""
    cfg_path = pace_config.user_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"existing_field": "preserved", "vault_root": "/old"}),
        encoding="utf-8",
    )

    pace_config.set_vault_root(tmp_path / "new")

    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert payload["existing_field"] == "preserved"
    assert payload["vault_root"] == str((tmp_path / "new").resolve())


def test_clear_vault_root_removes_field(tmp_path: Path) -> None:
    pace_config.set_vault_root(tmp_path / "vault")
    assert pace_config.clear_vault_root() is True
    # Subsequent resolve should return None.
    assert pace_config.resolve_vault_root() is None


# ---- vault.init writes the config ------------------------------------


def test_vault_init_records_vault_path_in_user_config(tmp_path: Path) -> None:
    """``pace init`` must persist the vault path to the per-user config so
    a later plugin-spawned MCP server can find the vault without an env
    var."""
    from pace import vault as vault_ops

    vault_root = tmp_path / "my-vault"
    result = vault_ops.init(vault_root)

    assert result.user_config_path is not None
    assert result.user_config_path.is_file()

    # Resolution finds it without any env var set.
    resolved = pace_config.resolve_vault_root()
    assert resolved == vault_root.resolve()
