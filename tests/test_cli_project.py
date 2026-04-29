"""End-to-end CLI tests for the `pace project` command group."""

from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from pace.cli import main


def _env(tmp_path: Path) -> dict[str, str]:
    return {**os.environ, "PACE_ROOT": str(tmp_path)}


def _run(runner: CliRunner, *args: str, env: dict[str, str] | None = None):
    return runner.invoke(main, list(args), env=env, catch_exceptions=False)


def test_project_create_list_load(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))

    create = _run(
        runner, "project", "create", "Alpha", "--alias", "alpha-effort", env=env
    )
    assert create.exit_code == 0
    assert "Created project Alpha" in create.output

    listed = _run(runner, "project", "list", env=env)
    assert listed.exit_code == 0
    assert "Alpha" in listed.output
    assert "alpha-effort" in listed.output

    capture = _run(
        runner,
        "capture",
        "--kind",
        "project_summary",
        "--project",
        "Alpha",
        "Kickoff scheduled for Monday.",
        env=env,
    )
    assert capture.exit_code == 0

    load = _run(runner, "project", "load", "alpha-effort", env=env)
    assert load.exit_code == 0
    assert "Kickoff scheduled" in load.output


def test_project_load_unknown_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))

    result = runner.invoke(main, ["project", "load", "Ghost"], env=env)
    assert result.exit_code != 0
    assert "no project matched" in result.output.lower()


def test_project_alias_add_remove(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))
    _run(runner, "project", "create", "Alpha", env=env)

    added = _run(runner, "project", "alias", "add", "Alpha", "ae", env=env)
    assert added.exit_code == 0
    assert "ae" in added.output

    removed = _run(runner, "project", "alias", "remove", "Alpha", "ae", env=env)
    assert removed.exit_code == 0
    assert "(none)" in removed.output


def test_project_rename_via_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))
    _run(runner, "project", "create", "Alpha", env=env)

    result = _run(runner, "project", "rename", "Alpha", "Beta", env=env)
    assert result.exit_code == 0
    assert "Renamed Alpha" in result.output
    assert (tmp_path / "projects" / "Beta" / "summary.md").is_file()
