"""Execution Mode (v0.4.0): settings, per-project overrides, runbooks,
template stamping, `pace upgrade`, and the doctor drift check.

The behavioral contract itself lives in prose (CLAUDE.md's gated
"Execution Mode" section); these tests pin the plumbing that gates it —
config parsing, pace_status surfacing, project frontmatter, and the
upgrade path that carries the new template into pre-existing vaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pace import doctor as doctor_ops
from pace import projects
from pace import settings as pace_settings
from pace import vault as vault_ops
from pace.index import Index
from pace.mcp_server import pace_load_project, pace_status
from pace.onboarding import (
    CLAUDE_MD_TEMPLATE,
    CLAUDE_MD_TEMPLATE_VERSION,
    template_version_of,
)


@pytest.fixture
def mcp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a vault and point the MCP tools at it via PACE_ROOT."""
    vault_ops.init(tmp_path)
    monkeypatch.setenv("PACE_ROOT", str(tmp_path))
    return tmp_path


def _write_config(root: Path, body: str) -> None:
    cfg = root / "system" / "pace_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body, encoding="utf-8")


# ---- Settings ----------------------------------------------------------


def test_execution_defaults_off(tmp_path: Path) -> None:
    s = pace_settings.load(tmp_path)
    assert s.execution_enabled is False
    assert s.execution_default_mode == pace_settings.DEFAULT_EXECUTION_MODE


def test_execution_yaml_overrides(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "execution:\n  enabled: true\n  default_mode: edit_verify_commit\n",
    )
    s = pace_settings.load(tmp_path)
    assert s.execution_enabled is True
    assert s.execution_default_mode == "edit_verify_commit"


def test_execution_invalid_mode_falls_back_to_default(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "execution:\n  enabled: true\n  default_mode: yolo\n",
    )
    s = pace_settings.load(tmp_path)
    assert s.execution_default_mode == pace_settings.DEFAULT_EXECUTION_MODE


def test_coerce_execution_mode_normalizes_case_and_whitespace() -> None:
    assert pace_settings.coerce_execution_mode(" Draft ", None) == "draft"
    assert pace_settings.coerce_execution_mode("nope", None) is None
    assert pace_settings.coerce_execution_mode(42, "draft") == "draft"


# ---- pace_status surfacing ---------------------------------------------


def test_status_execution_disabled_is_compact(mcp_vault: Path) -> None:
    result = pace_status()
    assert result["execution"] == {"enabled": False}


def test_status_execution_enabled_carries_mode(mcp_vault: Path) -> None:
    _write_config(
        mcp_vault,
        "execution:\n  enabled: true\n  default_mode: edit_verify_commit_push\n",
    )
    result = pace_status()
    assert result["execution"] == {
        "enabled": True,
        "default_mode": "edit_verify_commit_push",
    }


def test_status_uninitialized_has_execution_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PACE_ROOT", str(tmp_path / "uninit"))
    result = pace_status()
    assert result["execution"] == {"enabled": False}


# ---- Per-project overrides & runbooks -----------------------------------


def test_set_execution_mode_roundtrip(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    proj = projects.set_execution_mode(
        vault, "Alpha", "edit_verify_commit", index=index
    )
    assert proj.execution_mode == "edit_verify_commit"

    # Persisted: a fresh resolve reads it back from frontmatter.
    reloaded = projects.resolve(vault, "Alpha", index)
    assert reloaded is not None
    assert reloaded.execution_mode == "edit_verify_commit"

    cleared = projects.set_execution_mode(vault, "Alpha", None, index=index)
    assert cleared.execution_mode is None
    text = (vault / "projects" / "Alpha" / "summary.md").read_text(
        encoding="utf-8"
    )
    assert "execution_mode" not in text


def test_set_execution_mode_rejects_unknown(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    with pytest.raises(ValueError, match="yolo"):
        projects.set_execution_mode(vault, "Alpha", "yolo", index=index)


def test_invalid_frontmatter_mode_degrades_to_none(
    vault: Path, index: Index
) -> None:
    projects.create_project(vault, "Alpha", index=index)
    summary = vault / "projects" / "Alpha" / "summary.md"
    text = summary.read_text(encoding="utf-8")
    summary.write_text(
        text.replace("---\n", "---\nexecution_mode: bogus\n", 1),
        encoding="utf-8",
    )
    proj = projects.resolve(vault, "Alpha", index)
    assert proj is not None
    assert proj.execution_mode is None


def test_load_project_returns_runbook_body(vault: Path, index: Index) -> None:
    projects.create_project(vault, "Alpha", index=index)
    runbook = vault / "projects" / "Alpha" / "runbook.md"
    runbook.write_text(
        "## Checks\n- npm run lint\n- npm test\n", encoding="utf-8"
    )
    result = projects.load_project(vault, "Alpha", index=index)
    assert result is not None
    assert result.runbook is not None
    assert "npm run lint" in result.runbook


def test_mcp_load_project_surfaces_runbook_and_mode(mcp_vault: Path) -> None:
    idx = Index(mcp_vault / "system" / "pace_index.db")
    try:
        projects.create_project(mcp_vault, "Alpha", index=idx)
        projects.set_execution_mode(mcp_vault, "Alpha", "draft", index=idx)
    finally:
        idx.close()
    (mcp_vault / "projects" / "Alpha" / "runbook.md").write_text(
        "Deploy: never on Fridays.", encoding="utf-8"
    )

    result = pace_load_project(name="Alpha")
    assert result["project"]["execution_mode"] == "draft"
    assert "never on Fridays" in result["runbook"]


def test_mcp_load_project_runbook_null_when_absent(mcp_vault: Path) -> None:
    idx = Index(mcp_vault / "system" / "pace_index.db")
    try:
        projects.create_project(mcp_vault, "Alpha", index=idx)
    finally:
        idx.close()
    result = pace_load_project(name="Alpha")
    assert result["runbook"] is None
    assert result["project"]["execution_mode"] is None


# ---- Template stamp & content -------------------------------------------


def test_template_carries_current_version_stamp() -> None:
    assert template_version_of(CLAUDE_MD_TEMPLATE) == CLAUDE_MD_TEMPLATE_VERSION


def test_template_version_of_unstamped_is_none() -> None:
    assert template_version_of("# Hand-written CLAUDE.md\n") is None


def test_template_has_gated_execution_section() -> None:
    assert "## Execution Mode" in CLAUDE_MD_TEMPLATE
    # The gate must be explicit in both directions.
    assert "execution.enabled: true" in CLAUDE_MD_TEMPLATE
    assert "ignore this entire section" in CLAUDE_MD_TEMPLATE
    # The four modes and the always-explicit boundary.
    for mode in pace_settings.EXECUTION_MODES:
        assert f"`{mode}`" in CLAUDE_MD_TEMPLATE
    assert "explicit approval" in CLAUDE_MD_TEMPLATE
    # Delivery-loop anchors.
    assert "Inspect first" in CLAUDE_MD_TEMPLATE
    assert "Gate completion on evidence" in CLAUDE_MD_TEMPLATE
    assert "runbook.md" in CLAUDE_MD_TEMPLATE


def test_template_has_untrusted_content_boundary() -> None:
    assert "data, not instructions" in CLAUDE_MD_TEMPLATE


# ---- pace upgrade --------------------------------------------------------


def test_upgrade_refreshes_stale_claude_md_with_backup(vault: Path) -> None:
    claude = vault / "CLAUDE.md"
    claude.write_text("# Old template, customized by hand\n", encoding="utf-8")

    result = vault_ops.upgrade(vault)

    assert "CLAUDE.md" in result.updated
    assert claude.read_text(encoding="utf-8") == CLAUDE_MD_TEMPLATE
    assert result.backup_dir is not None
    backup = vault / result.backup_dir / "CLAUDE.md"
    assert backup.read_text(encoding="utf-8") == (
        "# Old template, customized by hand\n"
    )


def test_upgrade_is_idempotent(vault: Path) -> None:
    first = vault_ops.upgrade(vault)
    second = vault_ops.upgrade(vault)
    assert second.updated == []
    assert second.backup_dir is None
    assert sorted(second.unchanged) == sorted(
        [*first.updated, *first.unchanged]
    )


def test_upgrade_recreates_missing_prompt_files(vault: Path) -> None:
    compact = vault / "system" / "prompts" / "compact.md"
    compact.unlink()
    result = vault_ops.upgrade(vault)
    assert "system/prompts/compact.md" in result.updated
    assert compact.is_file()


def test_upgrade_leaves_user_state_alone(vault: Path) -> None:
    cfg = vault / "system" / "pace_config.yaml"
    before = cfg.read_text(encoding="utf-8")
    wm = vault / "memories" / "working_memory.md"
    wm_before = wm.read_text(encoding="utf-8")

    vault_ops.upgrade(vault)

    assert cfg.read_text(encoding="utf-8") == before
    assert wm.read_text(encoding="utf-8") == wm_before


# ---- doctor: template drift ---------------------------------------------


def test_doctor_flags_unstamped_claude_md(vault: Path) -> None:
    (vault / "CLAUDE.md").write_text("# Hand-rolled\n", encoding="utf-8")
    issues = doctor_ops.check_claude_md_template(vault)
    assert len(issues) == 1
    assert issues[0].code == "claude-md-outdated"
    assert "pace upgrade" in (issues[0].fix_hint or "")


def test_doctor_flags_older_stamp(vault: Path) -> None:
    (vault / "CLAUDE.md").write_text(
        "<!-- pace-template-version: 1 -->\n# Old\n", encoding="utf-8"
    )
    issues = doctor_ops.check_claude_md_template(vault)
    assert len(issues) == 1
    assert "v1" in issues[0].message


def test_doctor_quiet_on_current_or_newer_stamp(vault: Path) -> None:
    assert doctor_ops.check_claude_md_template(vault) == []
    (vault / "CLAUDE.md").write_text(
        f"<!-- pace-template-version: {CLAUDE_MD_TEMPLATE_VERSION + 1} -->\n",
        encoding="utf-8",
    )
    assert doctor_ops.check_claude_md_template(vault) == []


def test_doctor_quiet_when_claude_md_missing(vault: Path) -> None:
    (vault / "CLAUDE.md").unlink()
    assert doctor_ops.check_claude_md_template(vault) == []


# ---- CLI: pace upgrade & pace project mode -------------------------------


def _cli_env(tmp_path: Path) -> dict[str, str]:
    import os

    return {**os.environ, "PACE_ROOT": str(tmp_path)}


def test_cli_upgrade_and_project_mode(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from pace.cli import main

    runner = CliRunner()
    env = _cli_env(tmp_path)
    runner.invoke(main, ["init", "--root", str(tmp_path)], env=env)

    # Simulate a pre-0.4 vault and upgrade it.
    (tmp_path / "CLAUDE.md").write_text("# old\n", encoding="utf-8")
    up = runner.invoke(main, ["upgrade"], env=env, catch_exceptions=False)
    assert up.exit_code == 0
    assert "CLAUDE.md" in up.output
    assert "system/backups" in up.output

    again = runner.invoke(main, ["upgrade"], env=env, catch_exceptions=False)
    assert again.exit_code == 0
    assert "Already up to date" in again.output

    runner.invoke(
        main, ["project", "create", "Alpha"], env=env, catch_exceptions=False
    )
    mode = runner.invoke(
        main,
        ["project", "mode", "Alpha", "edit_verify_commit"],
        env=env,
        catch_exceptions=False,
    )
    assert mode.exit_code == 0
    assert "edit_verify_commit" in mode.output

    load = runner.invoke(
        main, ["project", "load", "Alpha"], env=env, catch_exceptions=False
    )
    assert "execution_mode: edit_verify_commit" in load.output

    cleared = runner.invoke(
        main,
        ["project", "mode", "Alpha", "--clear"],
        env=env,
        catch_exceptions=False,
    )
    assert cleared.exit_code == 0
    assert "vault default" in cleared.output


def test_cli_project_mode_requires_exactly_one_of_mode_or_clear(
    tmp_path: Path,
) -> None:
    from click.testing import CliRunner

    from pace.cli import main

    runner = CliRunner()
    env = _cli_env(tmp_path)
    runner.invoke(main, ["init", "--root", str(tmp_path)], env=env)
    runner.invoke(
        main, ["project", "create", "Alpha"], env=env, catch_exceptions=False
    )

    neither = runner.invoke(main, ["project", "mode", "Alpha"], env=env)
    assert neither.exit_code != 0

    both = runner.invoke(
        main, ["project", "mode", "Alpha", "draft", "--clear"], env=env
    )
    assert both.exit_code != 0
