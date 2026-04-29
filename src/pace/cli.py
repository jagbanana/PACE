"""Click-based command-line entry point for PACE.

Phase 1 surface: ``init``, ``status``, ``capture``, ``search``, ``reindex``.
Phase 2 adds the ``project`` command group and project-aware ``capture``.
MCP, compaction, and review commands arrive in subsequent phases.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click

# PACE writes UTF-8 to disk and emits UTF-8 (em-dash, arrow, snippet markers)
# from the CLI. Windows defaults stdout to cp1252, which raises
# UnicodeEncodeError on chars like '→'. Reconfigure to UTF-8 with a replace
# fallback so unrenderable chars become '?' instead of crashing.
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

from pace import __version__
from pace import projects as project_ops
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
    if result.git_initialized:
        click.echo("  Initialized git repository (branch: main).")


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
    type=click.Choice(["working", "long_term", "project_summary", "project_note"]),
    required=True,
    help="Where to store the entry.",
)
@click.option(
    "--topic",
    type=str,
    default=None,
    help="Required for --kind long_term. Becomes long_term/<topic>.md.",
)
@click.option(
    "--project",
    type=str,
    default=None,
    help="Required for --kind project_summary or project_note.",
)
@click.option(
    "--note",
    type=str,
    default=None,
    help="Required for --kind project_note. Becomes projects/<project>/notes/<note>.md.",
)
@click.option(
    "--tag",
    "tags",
    type=str,
    multiple=True,
    help="Tag for the entry. May be passed multiple times. Leading # is optional.",
)
@click.argument("content", type=str)
def capture(
    kind: str,
    topic: str | None,
    project: str | None,
    note: str | None,
    tags: tuple[str, ...],
    content: str,
) -> None:
    """Append CONTENT as a new entry in the chosen file."""
    if kind == "long_term" and not topic:
        raise click.UsageError("--topic is required when --kind=long_term.")
    if kind in {"project_summary", "project_note"} and not project:
        raise click.UsageError(f"--project is required when --kind={kind}.")
    if kind == "project_note" and not note:
        raise click.UsageError("--note is required when --kind=project_note.")

    root = require_vault_root()
    with _open_index(root) as idx:
        try:
            path = capture_entry(
                root,
                kind=kind,
                content=content,
                tags=list(tags),
                topic=topic,
                project=project,
                note=note,
                index=idx,
            )
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

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


# ---- project group -----------------------------------------------------


@main.group("project")
def project_group() -> None:
    """Manage projects: list, create, load, rename, alias."""


@project_group.command("list")
def project_list() -> None:
    """Print all projects with their last-modified timestamps and aliases."""
    root = require_vault_root()
    projects = project_ops.list_projects(root)
    if not projects:
        click.echo("No projects yet. Create one with `pace project create <name>`.")
        return
    for proj in projects:
        aliases = ", ".join(proj.aliases) if proj.aliases else "(none)"
        click.echo(f"{proj.name}")
        click.echo(f"  title:    {proj.title}")
        click.echo(f"  modified: {proj.date_modified}")
        click.echo(f"  aliases:  {aliases}")
        click.echo("")


@project_group.command("create")
@click.option(
    "--alias",
    "aliases",
    multiple=True,
    help="Add an alias the model can match against. Repeat for multiple.",
)
@click.option(
    "--title",
    type=str,
    default=None,
    help="Display title (defaults to a humanized version of NAME).",
)
@click.argument("name", type=str)
def project_create(name: str, aliases: tuple[str, ...], title: str | None) -> None:
    """Create a new project with an empty summary."""
    root = require_vault_root()
    with _open_index(root) as idx:
        try:
            proj = project_ops.create_project(
                root, name, aliases=list(aliases), title=title, index=idx
            )
        except (FileExistsError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"Created project {proj.name} at projects/{proj.name}/")
    if proj.aliases:
        click.echo(f"  aliases: {', '.join(proj.aliases)}")


@project_group.command("load")
@click.argument("name_or_alias", type=str)
def project_load(name_or_alias: str) -> None:
    """Resolve a project by name/alias and print its summary."""
    root = require_vault_root()
    with _open_index(root) as idx:
        result = project_ops.load_project(root, name_or_alias, index=idx)
    if result is None:
        raise click.ClickException(f"No project matched {name_or_alias!r}.")
    proj, body = result
    click.echo(f"# {proj.title}  ({proj.name})")
    if proj.aliases:
        click.echo(f"aliases: {', '.join(proj.aliases)}")
    click.echo("")
    click.echo(body or "(empty summary)")


@project_group.command("rename")
@click.argument("old_name", type=str)
@click.argument("new_name", type=str)
def project_rename(old_name: str, new_name: str) -> None:
    """Rename a project; rewrites wikilinks across the vault."""
    root = require_vault_root()
    with _open_index(root) as idx:
        try:
            proj = project_ops.rename_project(root, old_name, new_name, index=idx)
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"Renamed {old_name} → {proj.name}")


@project_group.group("alias")
def project_alias_group() -> None:
    """Manage aliases on a project."""


@project_alias_group.command("add")
@click.argument("name", type=str)
@click.argument("alias", type=str)
def project_alias_add(name: str, alias: str) -> None:
    """Add an alias to a project."""
    root = require_vault_root()
    with _open_index(root) as idx:
        try:
            proj = project_ops.add_alias(root, name, alias, index=idx)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"{proj.name} aliases: {', '.join(proj.aliases) or '(none)'}")


@project_alias_group.command("remove")
@click.argument("name", type=str)
@click.argument("alias", type=str)
def project_alias_remove(name: str, alias: str) -> None:
    """Remove an alias from a project."""
    root = require_vault_root()
    with _open_index(root) as idx:
        try:
            proj = project_ops.remove_alias(root, name, alias, index=idx)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"{proj.name} aliases: {', '.join(proj.aliases) or '(none)'}")


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
