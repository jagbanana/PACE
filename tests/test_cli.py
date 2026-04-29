"""End-to-end CLI tests using Click's CliRunner.

These exercise the same code paths as the unit tests but through the
public CLI surface — guarding against regressions where the modules
work but the CLI wiring drifts.
"""

from __future__ import annotations

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
