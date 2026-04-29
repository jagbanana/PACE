"""Build-script tests: stage + zip end-to-end.

The plugin ships its own Python source under ``server/`` so ``uvx
--from ${CLAUDE_PLUGIN_ROOT}/server pace-mcp`` works without any PyPI
publish. These tests prove the build script actually places that source
into the zip — without them, a refactor that breaks the staging step
would produce a quietly-broken plugin.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from scripts import build_plugin

REPO_ROOT = build_plugin.REPO_ROOT


@pytest.fixture
def built_plugin(tmp_path: Path) -> Path:
    """Run the actual build into ``tmp_path`` and return the zip path."""
    out = tmp_path / "pace-memory.plugin"
    return build_plugin.build(out)


def _zip_names(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def _read_zip_text(zip_path: Path, arcname: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(arcname) as fh:
            return io.TextIOWrapper(fh, encoding="utf-8").read()


# ---- Staging step ----------------------------------------------------


def test_stage_creates_server_dir_with_runtime_files(tmp_path: Path) -> None:
    """``stage_server_source`` must produce a self-contained Python
    project (pyproject + src + LICENSE + README) so uvx can resolve it.

    Caller owns the target dir; we use ``tmp_path`` so we never touch
    the in-tree ``plugin/`` directory or OneDrive."""
    server = build_plugin.stage_server_source(tmp_path / "stage")
    assert (server / "pyproject.toml").is_file()
    assert (server / "LICENSE").is_file()
    assert (server / "README.md").is_file()
    assert (server / "src" / "pace" / "__init__.py").is_file()
    assert (server / "src" / "pace" / "mcp_server.py").is_file()


def test_stage_excludes_pycache(tmp_path: Path) -> None:
    """Caches should never end up in the bundled source."""
    server = build_plugin.stage_server_source(tmp_path / "stage")
    for path in server.rglob("*"):
        assert "__pycache__" not in path.parts, (
            f"unexpected __pycache__ in {path}"
        )


# ---- Built zip -------------------------------------------------------


def test_zip_contains_bundled_server_source(built_plugin: Path) -> None:
    names = _zip_names(built_plugin)
    # Spot-check the entry points uvx will actually need.
    assert "server/pyproject.toml" in names
    assert "server/src/pace/__init__.py" in names
    assert "server/src/pace/mcp_server.py" in names
    assert "server/src/pace/cli.py" in names
    assert "server/LICENSE" in names
    assert "server/README.md" in names


def test_zip_contains_skill_and_prompts(built_plugin: Path) -> None:
    """Sanity: the non-server bits the previous tests covered are still
    bundled — staging shouldn't have displaced them."""
    names = _zip_names(built_plugin)
    assert ".claude-plugin/plugin.json" in names
    assert ".mcp.json" in names
    assert "skills/pace-memory/SKILL.md" in names
    assert "system-prompts/compact.md" in names
    assert "system-prompts/review.md" in names


def test_zip_does_not_contain_caches_or_dev_artifacts(built_plugin: Path) -> None:
    names = _zip_names(built_plugin)
    for name in names:
        assert "__pycache__" not in name
        assert ".pytest_cache" not in name
        assert ".ruff_cache" not in name
        assert not name.endswith(".pyc")


def test_zip_pyproject_declares_pace_mcp_entry_point(built_plugin: Path) -> None:
    """uvx looks up ``[project.scripts]`` to find ``pace-mcp``. If
    pyproject's entry points don't survive the staging copy, the plugin
    is broken."""
    pyproject_text = _read_zip_text(built_plugin, "server/pyproject.toml")
    # Loose match — just confirm the entry point name and module are
    # referenced. Full TOML parsing would import tomllib, which is
    # already 3.11+, but the substring check is enough as a tripwire.
    assert "pace-mcp" in pyproject_text
    assert "pace.mcp_server:main" in pyproject_text


def test_zip_mcp_json_points_at_bundled_server(built_plugin: Path) -> None:
    """The .mcp.json shipped in the zip must reference the bundled path
    — not the old PyPI form. End-to-end check that the build matches the
    static test in test_plugin_package.py."""
    payload = json.loads(_read_zip_text(built_plugin, ".mcp.json"))
    args = payload["mcpServers"]["pace"]["args"]
    assert "${CLAUDE_PLUGIN_ROOT}/server" in args
    assert "pace-mcp" in args
