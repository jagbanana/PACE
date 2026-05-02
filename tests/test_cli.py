"""End-to-end CLI tests using Click's CliRunner.

These exercise the same code paths as the unit tests but through the
public CLI surface — guarding against regressions where the modules
work but the CLI wiring drifts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from pace.cli import main
from pace.paths import WORKING_MEMORY


def _run(runner: CliRunner, *args: str, env: dict[str, str] | None = None):
    return runner.invoke(main, list(args), env=env, catch_exceptions=False)


def test_init_status_capture_search_round_trip(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {**os.environ, "PACE_ROOT": str(tmp_path)}

    init = _run(runner, "init", "--root", str(tmp_path))
    assert init.exit_code == 0
    assert "Initialized PACE vault" in init.output

    cap = _run(
        runner,
        "capture",
        "--kind",
        "working",
        "--tag",
        "decision",
        "Pricing for Q3 will hold steady.",
        env=env,
    )
    assert cap.exit_code == 0
    assert "Captured to" in cap.output

    status = _run(runner, "status", env=env)
    assert status.exit_code == 0
    assert "Files indexed: 1" in status.output

    found = _run(runner, "search", "Q3 pricing", env=env)
    assert found.exit_code == 0
    assert WORKING_MEMORY in found.output

    missing = _run(runner, "search", "nonexistent xyzzy", env=env)
    assert missing.exit_code == 0
    assert "No results." in missing.output


def test_status_without_vault_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {**os.environ, "PACE_ROOT": str(tmp_path / "nonexistent")}
    result = runner.invoke(main, ["status"], env=env)
    assert result.exit_code == 1
    assert "no initialized vault" in result.output.lower()


def test_init_with_plugin_root_writes_persistent_bin_to_mcp_config(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: ``pace init --root <vault> --plugin-root <plugin>``
    must run ``uv tool install`` (mocked here) and embed the absolute
    path to the installed ``pace-mcp.exe`` in ``.mcp.json``. This is
    the v0.3.4 fix that gives Claude Code's MCP launcher a sub-100ms
    spawn instead of the 5–30s ``uvx --from`` rebuild it can't tolerate."""
    runner = CliRunner()
    plugin_root = tmp_path / "fake-plugin"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (plugin_root / "server").mkdir()
    (plugin_root / "server" / "pyproject.toml").write_text("", encoding="utf-8")
    vault_root = tmp_path / "vault"

    fake_bin = tmp_path / "fake-bin" / "pace-mcp.exe"
    fake_bin.parent.mkdir()
    fake_bin.touch()

    from pace import vault as vault_ops

    monkeypatch.setattr(
        vault_ops,
        "_resolve_persistent_pace_mcp",
        lambda: str(fake_bin),
    )

    result = _run(
        runner,
        "init",
        "--root",
        str(vault_root),
        "--plugin-root",
        str(plugin_root),
    )
    assert result.exit_code == 0
    assert "Initialized PACE vault" in result.output

    payload = json.loads((vault_root / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == str(fake_bin)
    assert server["args"] == []
    assert server["env"]["PACE_ROOT"] == str(vault_root.resolve())


def _make_fake_plugin_install(parent: Path) -> Path:
    """Create a directory that looks like a Claude Code plugin install:
    parent/<marketplace>/pace-memory/{.claude-plugin/plugin.json, server/pyproject.toml}."""
    plugin_root = parent / "fake-marketplace" / "pace-memory"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "pace-memory"}', encoding="utf-8"
    )
    (plugin_root / "server").mkdir()
    (plugin_root / "server" / "pyproject.toml").write_text("", encoding="utf-8")
    return plugin_root


def test_bootstrap_command_installs_then_inits_with_plugin_root(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: ``pace bootstrap <path> --plugin-root <plugin>``
    runs the persistent install, scaffolds the vault, and writes a
    `.mcp.json` pointing at the resolved persistent pace-mcp binary.
    Both subprocess calls are mocked so the test runs offline."""
    runner = CliRunner()
    plugin_root = _make_fake_plugin_install(tmp_path / "plugins-root")
    fake_bin = tmp_path / "fake-bin" / "pace-mcp.exe"
    fake_bin.parent.mkdir()
    fake_bin.touch()

    from pace import vault as vault_ops

    install_calls: list[Path] = []

    def fake_install(pr: Path) -> None:
        install_calls.append(pr)

    monkeypatch.setattr(vault_ops, "install_pace_persistently", fake_install)
    monkeypatch.setattr(
        vault_ops, "_resolve_persistent_pace_mcp", lambda: str(fake_bin)
    )

    vault_path = tmp_path / "Bob"
    result = _run(
        runner,
        "bootstrap",
        str(vault_path),
        "--plugin-root",
        str(plugin_root),
    )
    assert result.exit_code == 0, result.output
    assert "Vault ready" in result.output

    # `uv tool install` was invoked exactly once, against the right plugin.
    assert install_calls == [plugin_root]

    # And the project .mcp.json points at the persistent binary.
    payload = json.loads((vault_path / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == str(fake_bin)
    assert server["args"] == []
    assert server["env"]["PACE_ROOT"] == str(vault_path.resolve())


def test_bootstrap_command_auto_discovers_plugin_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Without --plugin-root, the command searches under
    ~/.claude/plugins/marketplaces/*/pace-memory/. Mock HOME so the
    test is hermetic."""
    runner = CliRunner()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    plugins_marketplaces = fake_home / ".claude" / "plugins" / "marketplaces"
    plugin_root = _make_fake_plugin_install(plugins_marketplaces)

    from pace import vault as vault_ops

    monkeypatch.setattr("pace.vault.Path.home", lambda: fake_home)
    monkeypatch.setattr(vault_ops, "install_pace_persistently", lambda _pr: None)
    fake_bin = tmp_path / "fake-bin" / "pace-mcp.exe"
    fake_bin.parent.mkdir()
    fake_bin.touch()
    monkeypatch.setattr(
        vault_ops, "_resolve_persistent_pace_mcp", lambda: str(fake_bin)
    )

    vault_path = tmp_path / "Carla"
    result = _run(runner, "bootstrap", str(vault_path))
    assert result.exit_code == 0, result.output
    assert str(plugin_root.resolve()) in result.output


def test_bootstrap_command_errors_when_plugin_not_found(
    tmp_path: Path, monkeypatch
) -> None:
    """If neither --plugin-root nor auto-discovery finds the plugin,
    the command must fail with a clear error rather than scaffolding
    a half-vault."""
    runner = CliRunner()
    fake_home = tmp_path / "home-without-plugin"
    fake_home.mkdir()
    monkeypatch.setattr("pace.vault.Path.home", lambda: fake_home)

    vault_path = tmp_path / "Ada"
    result = _run(runner, "bootstrap", str(vault_path))
    assert result.exit_code != 0
    assert "Could not auto-discover" in result.output
    # No partial vault scaffolding on failure.
    assert not vault_path.exists() or not (vault_path / ".mcp.json").exists()


def test_capture_long_term_requires_topic(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {**os.environ, "PACE_ROOT": str(tmp_path)}
    _run(runner, "init", "--root", str(tmp_path))

    result = runner.invoke(
        main,
        ["capture", "--kind", "long_term", "A fact"],
        env=env,
    )
    assert result.exit_code != 0
    assert "topic" in result.output.lower()
