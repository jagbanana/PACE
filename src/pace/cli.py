"""Click-based command-line entry point for PACE.

Phase 1 surface: ``init``, ``status``, ``capture``, ``search``, ``reindex``.
Project, MCP, compaction, and review commands arrive in subsequent phases.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click

from pace import __version__
from pace import vault as vault_ops
from pace.capture import capture as capture_entry
from pace.index import Index
from pace.paths import (
    INDEX_DB,
    VaultNotFoundError,
    find_vault_root,
    is_initialized,
    require_vault_root,
)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="PACE — Persistent AI Context Engine. Run `pace <command> --help` for details.",
)
@click.version_option(__version__, "-V", "--version", prog_name="pace")
def main() -> None:
    """Top-level command group; subcommands are registered below."""


# ---- init --------------------------------------------------------------


@main.command()
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Vault root to initialize. Defaults to the current directory.",
)
def init(root: Path | None) -> None:
    """Scaffold an empty PACE vault. Idempotent — safe to re-run."""
    target = (root or Path.cwd()).resolve()
    target.mkdir(parents=True, exist_ok=True)
    result = vault_ops.init(target)

    if result.already_initialized and not result.created_dirs and not result.created_files:
        click.echo(f"Vault already initialized at {result.root}.")
        return

    click.echo(f"Initialized PACE vault at {result.root}.")
    if result.created_dirs:
        click.echo("  Created directories:")
        for d in result.created_dirs:
            click.echo(f"    + {d}/")
    if result.created_files:
        click.echo("  Created files:")
        for f in result.created_files:
            click.echo(f"    + {f}")


# ---- status ------------------------------------------------------------


@main.command()
def status() -> None:
    """Report initialization state, file counts, and last-task timestamps."""
    root = find_vault_root()
    if root is None:
        click.echo("PACE: no initialized vault found from this directory.")
        click.echo("Run `pace init` to create one here.")
        raise SystemExit(1)

    click.echo(f"Vault root: {root}")
    click.echo(f"Initialized: {'yes' if is_initialized(root) else 'no'}")

    with _open_index(root) as idx:
        counts = idx.count_by_kind()
        total = sum(counts.values())
        click.echo(f"Files indexed: {total}")
        for kind in ("working", "long_term", "project_summary", "project_note", "archived"):
            click.echo(f"  {kind:>16}: {counts.get(kind, 0)}")

        last_compact = idx.get_config("last_compact") or "never"
        last_review = idx.get_config("last_review") or "never"
        click.echo(f"Last compaction: {last_compact}")
        click.echo(f"Last review:     {last_review}")


# ---- capture -----------------------------------------------------------


@main.command()
@click.option(
    "--kind",
    type=click.Choice(["working", "long_term"]),
    required=True,
    help="Where to store the entry. Phase 1 supports working and long_term.",
)
@click.option(
    "--topic",
    type=str,
    default=None,
    help="Required for --kind long_term. Becomes long_term/<topic>.md.",
)
@click.option(
    "--tag",
    "tags",
    type=str,
    multiple=True,
    help="Tag for the entry. May be passed multiple times. Leading # is optional.",
)
@click.argument("content", type=str)
def capture(kind: str, topic: str | None, tags: tuple[str, ...], content: str) -> None:
    """Append CONTENT as a new entry in the chosen file."""
    if kind == "long_term" and not topic:
        raise click.UsageError("--topic is required when --kind=long_term.")

    root = require_vault_root()
    with _open_index(root) as idx:
        path = capture_entry(
            root,
            kind=kind,
            content=content,
            tags=list(tags),
            topic=topic,
            index=idx,
        )

    rel = path.relative_to(root)
    click.echo(f"Captured to {rel}")


# ---- search ------------------------------------------------------------


@main.command()
@click.option(
    "--scope",
    type=click.Choice(["memory", "projects", "all"]),
    default=None,
    help="Restrict the search. Default: memory + active project files.",
)
@click.option(
    "--project",
    type=str,
    default=None,
    help="Restrict to a single project's files.",
)
@click.option("--limit", type=int, default=10, show_default=True)
@click.argument("query", type=str)
def search(scope: str | None, project: str | None, limit: int, query: str) -> None:
    """Search the vault index using FTS5."""
    root = require_vault_root()
    with _open_index(root) as idx:
        hits = idx.search(query, scope=scope, project=project, limit=limit)

    if not hits:
        click.echo("No results.")
        return

    for hit in hits:
        header = f"{hit.path}  [{hit.kind}]"
        if hit.project:
            header += f"  ({hit.project})"
        click.echo(header)
        click.echo(f"  {hit.title}")
        click.echo(f"  {hit.snippet}")
        click.echo("")


# ---- reindex -----------------------------------------------------------


@main.command()
def reindex() -> None:
    """Rebuild the FTS5 index from the markdown on disk."""
    root = require_vault_root()
    with _open_index(root) as idx:
        result = vault_ops.reindex(root, idx)
    click.echo(
        f"Reindex complete: {result.indexed} indexed, "
        f"{result.removed} removed, {result.skipped} skipped."
    )


# ---- helpers -----------------------------------------------------------


@contextmanager
def _open_index(root: Path) -> Iterator[Index]:
    db = root / INDEX_DB
    idx = Index(db)
    try:
        yield idx
    finally:
        idx.close()


# Convert VaultNotFoundError into a friendly Click message globally.
def _wrap_vault_errors() -> None:
    original = main.invoke

    def invoke(ctx: click.Context):
        try:
            return original(ctx)
        except VaultNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

    main.invoke = invoke  # type: ignore[method-assign]


_wrap_vault_errors()


if __name__ == "__main__":
    main()
