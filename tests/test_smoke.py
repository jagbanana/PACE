"""Smoke tests — ensure Phase 0 wiring works end to end."""

from __future__ import annotations

from click.testing import CliRunner

import pace
from pace.cli import main


def test_package_has_version() -> None:
    assert isinstance(pace.__version__, str)
    assert pace.__version__.count(".") >= 2


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert pace.__version__ in result.output


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "PACE" in result.output
