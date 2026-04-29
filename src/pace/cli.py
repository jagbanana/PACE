"""Click-based command-line entry point for PACE.

Phase 1 surface: ``init``, ``status``, ``capture``, ``search``, ``reindex``.
Phase 2 adds the ``project`` command group and project-aware ``capture``.
Phase 5 adds ``compact`` and ``review`` (each with ``--plan`` / ``--apply``)
plus a process-wide lock at ``system/.pace.lock`` so they can't overlap.
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

import json
import shutil
from datetime import datetime

from pace import __version__
from pace import compact as compact_ops
from pace import doctor as doctor_ops
from pace import frontmatter as fm_parser
from pace import projects as project_ops
from pace import review as review_ops
from pace import vault as vault_ops
from pace.capture import capture as capture_entry
from pace.index import Index, now_iso
from pace.lockfile import PaceLockBusy, acquire_pace_lock
from pace.paths import (
    ARCHIVED_DIR,
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
    """Report initialization state, counts, last-task timestamps, and health."""
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

        report = doctor_ops.run_all(root, idx)
        if report.healthy:
            click.echo("Health: clean.")
        else:
            click.echo(f"Health: {len(report.errors)} error(s), {len(report.warnings)} warning(s).")
            for issue in report.errors + report.warnings:
                click.echo(f"  [{issue.severity}] {issue.code}: {issue.message}")
            click.echo("Run `pace doctor` for detail and fix hints.")


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


# ---- compact -----------------------------------------------------------


@main.command()
@click.option("--plan", "plan_mode", is_flag=True, help="Generate a compaction plan as JSON.")
@click.option(
    "--apply",
    "apply_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Apply the approvals in the given plan file.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="(--plan only) Write plan JSON to this path. Default: system/logs/.",
)
def compact(plan_mode: bool, apply_path: Path | None, out_path: Path | None) -> None:
    """Run daily compaction (PRD §6.3). Use --plan to generate, --apply to execute."""
    _check_plan_apply_args(plan_mode, apply_path)
    root = require_vault_root()

    try:
        with acquire_pace_lock(root), _open_index(root) as idx:
            if plan_mode:
                plan = compact_ops.plan_compaction(root, idx)
                target = _resolve_plan_out_path(root, out_path, kind="compact")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
                click.echo(f"Plan written to {target}")
                click.echo(
                    f"  candidates: {len(plan['candidates'])}; "
                    f"projects with activity: "
                    f"{len(plan['active_projects_with_activity'])}"
                )
            else:
                assert apply_path is not None
                plan = json.loads(apply_path.read_text(encoding="utf-8"))
                result = compact_ops.apply_compaction(root, idx, plan)
                click.echo(
                    f"Applied: {result.promoted} promoted, "
                    f"{result.skipped} skipped."
                )
                if result.log_path:
                    click.echo(f"  log: {result.log_path.relative_to(root)}")
    except PaceLockBusy as exc:
        raise click.ClickException(str(exc)) from exc


# ---- review ------------------------------------------------------------


@main.command()
@click.option("--plan", "plan_mode", is_flag=True, help="Generate a review plan as JSON.")
@click.option(
    "--apply",
    "apply_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Apply the approvals + weekly synthesis in the given plan file.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="(--plan only) Write plan JSON to this path. Default: system/logs/.",
)
def review(plan_mode: bool, apply_path: Path | None, out_path: Path | None) -> None:
    """Run weekly deep review (PRD §6.4). Use --plan to generate, --apply to execute."""
    _check_plan_apply_args(plan_mode, apply_path)
    root = require_vault_root()

    try:
        with acquire_pace_lock(root), _open_index(root) as idx:
            if plan_mode:
                plan = review_ops.plan_review(root, idx)
                target = _resolve_plan_out_path(root, out_path, kind="review")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
                click.echo(f"Plan written to {target}")
                click.echo(
                    f"  archival candidates: {len(plan['candidates'])}; "
                    f"broken wikilinks: {len(plan['broken_wikilinks'])}"
                )
            else:
                assert apply_path is not None
                plan = json.loads(apply_path.read_text(encoding="utf-8"))
                result = review_ops.apply_review(root, idx, plan)
                click.echo(
                    f"Applied: {result.archived} archived, "
                    f"{result.skipped} skipped, "
                    f"weekly note {'written' if result.weekly_note_written else 'skipped'}."
                )
                if result.log_path:
                    click.echo(f"  log: {result.log_path.relative_to(root)}")
    except PaceLockBusy as exc:
        raise click.ClickException(str(exc)) from exc


# ---- doctor ------------------------------------------------------------


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
def doctor(as_json: bool) -> None:
    """Run vault health checks (PRD §6.7). Never auto-fixes — surfaces only."""
    root = require_vault_root()
    with _open_index(root) as idx:
        report = doctor_ops.run_all(root, idx)

    if as_json:
        payload = {
            "root": str(report.root),
            "healthy": report.healthy,
            "issues": [doctor_ops.issue_to_dict(i) for i in report.issues],
        }
        click.echo(json.dumps(payload, indent=2))
        if not report.healthy:
            raise SystemExit(1)
        return

    click.echo(f"Vault: {report.root}")
    if report.healthy:
        click.echo("All checks pass.")
        return

    click.echo(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s).")
    for issue in report.errors + report.warnings:
        click.echo("")
        click.echo(f"[{issue.severity}] {issue.code}: {issue.message}")
        if issue.detail:
            click.echo(f"  detail: {issue.detail}")
        if issue.fix_hint:
            click.echo(f"  fix:    {issue.fix_hint}")
    raise SystemExit(1 if report.errors else 0)


# ---- archive -----------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(path_type=Path))
def archive(path: Path) -> None:
    """Manually archive a markdown file: move to memories/archived/ and re-index."""
    root = require_vault_root()
    src = (path if path.is_absolute() else root / path).resolve()

    if not src.is_file():
        raise click.ClickException(f"File not found: {path}")
    if src.suffix != ".md":
        raise click.ClickException("Only markdown files can be archived.")
    try:
        rel_src = src.relative_to(root).as_posix()
    except ValueError as exc:
        raise click.ClickException(
            f"{src} is outside the vault root {root}; refusing to archive."
        ) from exc

    archived_root = root / ARCHIVED_DIR
    archived_root.mkdir(parents=True, exist_ok=True)
    dest = archived_root / src.name
    if dest.exists():
        raise click.ClickException(
            f"Archive target {dest.relative_to(root).as_posix()} already exists; "
            "rename or remove it first."
        )

    # Move on disk, update the index in one shot. Atomic in spirit: if
    # the rename fails, we never touched the index. If the index update
    # fails after rename, `pace reindex` will recover.
    shutil.move(str(src), str(dest))

    text = dest.read_text(encoding="utf-8")
    fm, body = fm_parser.parse(text)
    rel_dest = dest.relative_to(root).as_posix()

    with _open_index(root) as idx:
        idx.delete_file(rel_src)
        idx.upsert_file(
            path=rel_dest,
            kind="archived",
            title=str(fm.get("title") or dest.stem),
            body=body,
            date_created=str(fm.get("date_created", now_iso())),
            date_modified=str(fm.get("date_modified", now_iso())),
            tags=list(fm.get("tags") or []),
        )

    click.echo(f"Archived: {rel_src} → {rel_dest}")


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


def _check_plan_apply_args(plan_mode: bool, apply_path: Path | None) -> None:
    """Enforce that exactly one of --plan / --apply is provided."""
    if plan_mode and apply_path:
        raise click.UsageError("--plan and --apply are mutually exclusive.")
    if not plan_mode and apply_path is None:
        raise click.UsageError("Specify --plan to generate or --apply <file> to execute.")


def _resolve_plan_out_path(root: Path, out: Path | None, *, kind: str) -> Path:
    """Default plan files land in ``system/logs/<kind>-plan-<stamp>.json``."""
    if out is not None:
        return out
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return root / "system" / "logs" / f"{kind}-plan-{stamp}.json"


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
