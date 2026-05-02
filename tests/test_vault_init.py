"""``pace init`` scaffolding behavior."""

from __future__ import annotations

import json
import sys
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


# ---- .mcp.json shape: plugin-context vs dev-context ------------------


def _make_plugin_layout(tmp_path: Path) -> Path:
    """Mock a plugin install layout: plugin_root/.claude-plugin/plugin.json
    + plugin_root/server/. Returns the plugin_root path."""
    plugin_root = tmp_path / "fake-plugin"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (plugin_root / "server").mkdir()
    return plugin_root


def test_detect_plugin_root_finds_manifest_when_inside_plugin(
    tmp_path: Path,
) -> None:
    """When pace is bundled inside a Claude Code plugin
    (plugin_root/server/src/pace/__init__.py), walking up from a path
    deep inside the source tree finds .claude-plugin/plugin.json at
    the plugin root."""
    plugin_root = _make_plugin_layout(tmp_path)
    deep = plugin_root / "server" / "src" / "pace" / "__init__.py"
    deep.parent.mkdir(parents=True)
    deep.touch()

    found = vault_ops._detect_plugin_root(deep)
    assert found == plugin_root


def test_detect_plugin_root_returns_none_for_non_plugin_layout(
    tmp_path: Path,
) -> None:
    """A regular venv install / dev checkout has no .claude-plugin
    directly above pace.__file__; detection must return None so the
    caller falls back to embedding sys.executable in .mcp.json."""
    src = tmp_path / "src" / "pace" / "__init__.py"
    src.parent.mkdir(parents=True)
    src.touch()

    assert vault_ops._detect_plugin_root(src) is None


def test_build_mcp_config_uses_persistent_bin_when_provided(
    tmp_path: Path,
) -> None:
    """Best-path shape: when ``pace_mcp_bin`` is the absolute path
    to a ``pace-mcp.exe`` shim from ``uv tool install``, the
    project ``.mcp.json`` invokes it directly with no args.
    Sub-100ms launches and survives ``uv cache clean``."""
    vault_root = tmp_path / "vault"
    fake_bin = tmp_path / "pace-mcp.exe"

    cfg = vault_ops._build_mcp_config(
        vault_root, plugin_root=None, pace_mcp_bin=str(fake_bin)
    )
    server = cfg["mcpServers"]["pace"]
    assert server["command"] == str(fake_bin)
    assert server["args"] == []
    assert server["env"]["PACE_ROOT"] == str(vault_root)


def test_build_mcp_config_falls_back_to_uvx_when_install_unavailable(
    tmp_path: Path,
) -> None:
    """Fallback: if persistent install failed, the project
    ``.mcp.json`` still uses ``uvx --from <plugin>/server`` so the
    vault is functional (slow first launch but works)."""
    plugin_root = tmp_path / "fake-plugin"
    plugin_root.mkdir()
    vault_root = tmp_path / "vault"

    cfg = vault_ops._build_mcp_config(
        vault_root, plugin_root=plugin_root, pace_mcp_bin=None
    )
    server = cfg["mcpServers"]["pace"]
    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        str(plugin_root / "server"),
        "pace-mcp",
    ]
    assert server["env"]["PACE_ROOT"] == str(vault_root)


def test_build_mcp_config_uses_sys_executable_in_dev_context(
    tmp_path: Path,
) -> None:
    """When no plugin context is detected (dev/CLI invocation), the
    current Python is stable and embedding it directly is correct."""
    vault_root = tmp_path / "vault"
    cfg = vault_ops._build_mcp_config(
        vault_root, plugin_root=None, pace_mcp_bin=None
    )
    server = cfg["mcpServers"]["pace"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "pace.mcp_server"]
    assert server["env"]["PACE_ROOT"] == str(vault_root)


def test_init_uses_persistent_bin_when_resolved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """End-to-end happy path: pace init looks up the persistent
    pace-mcp install (mocked) and writes a `.mcp.json` with the
    absolute path to that binary. The bootstrap caller is
    responsible for having run `uv tool install` first; pace init
    only resolves, never installs (avoids Windows file-lock errors
    when pace init is itself running from the install)."""
    plugin_root = _make_plugin_layout(tmp_path)
    fake_bin = tmp_path / "fake-bin" / "pace-mcp.exe"
    fake_bin.parent.mkdir()
    fake_bin.touch()

    monkeypatch.setattr(
        vault_ops,
        "_resolve_persistent_pace_mcp",
        lambda: str(fake_bin),
    )

    vault_root = tmp_path / "vault"
    vault_ops.init(vault_root, plugin_root=plugin_root)

    payload = json.loads((vault_root / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == str(fake_bin)
    assert server["args"] == []
    assert server["env"]["PACE_ROOT"] == str(vault_root.resolve())


def test_init_falls_back_to_uvx_when_no_persistent_install(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """If no persistent pace-mcp install exists yet (caller didn't
    run `uv tool install` before pace init), init must NOT explode
    — it should warn, fall back to the uvx --from shape, and finish
    scaffolding the vault. The vault is still usable; just slow on
    first MCP launch until a manual `uv tool install` and
    re-init succeeds."""
    plugin_root = _make_plugin_layout(tmp_path)
    monkeypatch.setattr(
        vault_ops, "_resolve_persistent_pace_mcp", lambda: None
    )

    vault_root = tmp_path / "vault"
    vault_ops.init(vault_root, plugin_root=plugin_root)

    payload = json.loads((vault_root / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["pace"]
    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        str(plugin_root.resolve() / "server"),
        "pace-mcp",
    ]


def test_resolve_persistent_pace_mcp_uses_uv_tool_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Critical: must ask `uv tool dir --bin` for the install root,
    NOT use PATH-based discovery. PATH would find the ephemeral
    uvx-cache `pace-mcp` (since `pace init` is often launched via
    uvx, which prepends its cache to PATH) — that path disappears
    on `uv cache clean`."""
    import subprocess

    persistent_bin_dir = tmp_path / "persistent-bin"
    persistent_bin_dir.mkdir()
    bin_name = "pace-mcp.exe" if sys.platform == "win32" else "pace-mcp"
    persistent_bin = persistent_bin_dir / bin_name
    persistent_bin.touch()

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:4] == ["uv", "tool", "dir", "--bin"]:
            return subprocess.CompletedProcess(
                cmd, 0, str(persistent_bin_dir) + "\n", ""
            )
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    monkeypatch.setattr(vault_ops.subprocess, "run", fake_run)

    result = vault_ops._resolve_persistent_pace_mcp()

    # Asked uv directly; did not consult PATH.
    assert calls == [["uv", "tool", "dir", "--bin"]]
    # And returned the persistent path.
    assert result == str(persistent_bin)


def test_resolve_persistent_pace_mcp_returns_none_if_not_installed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """If `uv tool dir --bin` returns a directory but pace-mcp isn't
    in it, the caller is expected to fall back to the uvx form
    rather than embed a non-existent path."""
    import subprocess

    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, str(empty_bin_dir) + "\n", ""
        )

    monkeypatch.setattr(vault_ops.subprocess, "run", fake_run)

    assert vault_ops._resolve_persistent_pace_mcp() is None


def test_resolve_persistent_pace_mcp_returns_none_if_uv_missing(
    monkeypatch,
) -> None:
    """If `uv` itself isn't installed, lookup must return None
    cleanly — never raise — so init can still scaffold the vault
    via the uvx fallback."""
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("uv not found")

    monkeypatch.setattr(vault_ops.subprocess, "run", fake_run)

    assert vault_ops._resolve_persistent_pace_mcp() is None
