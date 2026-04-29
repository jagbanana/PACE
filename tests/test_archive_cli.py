"""``pace archive <path>`` CLI command."""

from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from pace.cli import main


def _env(tmp_path: Path) -> dict[str, str]:
    return {**os.environ, "PACE_ROOT": str(tmp_path)}


def _run(runner: CliRunner, *args: str, env: dict[str, str] | None = None):
    return runner.invoke(main, list(args), env=env, catch_exceptions=False)


def test_archive_moves_long_term_file(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))
    _run(
        runner,
        "capture",
        "--kind",
        "long_term",
        "--topic",
        "vendors",
        "--tag",
        "business",
        "Acme is preferred.",
        env=env,
    )

    src = tmp_path / "memories" / "long_term" / "vendors.md"
    assert src.is_file()

    result = _run(runner, "archive", str(src), env=env)
    assert result.exit_code == 0
    assert "Archived:" in result.output

    assert not src.exists()
    assert (tmp_path / "memories" / "archived" / "vendors.md").is_file()


def test_archive_rejects_path_outside_vault(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))

    outsider = tmp_path.parent / "outsider.md"
    outsider.write_text("# outside\n", encoding="utf-8")

    result = runner.invoke(main, ["archive", str(outsider)], env=env)
    assert result.exit_code != 0
    assert "outside the vault root" in result.output.lower()


def test_archive_rejects_existing_target(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))
    _run(
        runner,
        "capture",
        "--kind",
        "long_term",
        "--topic",
        "vendors",
        "Acme is preferred.",
        env=env,
    )

    # Pre-populate archived/vendors.md so the archive call collides.
    (tmp_path / "memories" / "archived").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memories" / "archived" / "vendors.md").write_text(
        "existing\n", encoding="utf-8"
    )

    src = tmp_path / "memories" / "long_term" / "vendors.md"
    result = runner.invoke(main, ["archive", str(src)], env=env)
    assert result.exit_code != 0
    assert "already exists" in result.output.lower()


def test_archive_rejects_non_markdown(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env(tmp_path)
    _run(runner, "init", "--root", str(tmp_path))

    other = tmp_path / "memories" / "notes.txt"
    other.write_text("not markdown", encoding="utf-8")

    result = runner.invoke(main, ["archive", str(other)], env=env)
    assert result.exit_code != 0
    assert "markdown" in result.output.lower()
