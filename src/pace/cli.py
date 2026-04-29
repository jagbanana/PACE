"""Click-based command-line entry point for PACE.

Phase 0 ships only `pace --version`. Subcommands (`init`, `capture`, `search`,
`status`, `reindex`, etc.) arrive in subsequent phases per PACE Dev Plan.md.
"""

from __future__ import annotations

import click

from pace import __version__


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="PACE — Persistent AI Context Engine. Run `pace <command> --help` for details.",
)
@click.version_option(__version__, "-V", "--version", prog_name="pace")
def main() -> None:
    """Top-level command group. Subcommands are added by later phases."""


if __name__ == "__main__":
    main()
