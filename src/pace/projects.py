"""Project lifecycle: list, create, load, rename, alias.

Per PRD §6.5 every project carries an ``aliases`` frontmatter field; the
model uses these for natural-language matching when the user refers to a
project informally. Resolution order in :func:`resolve` is exact directory
name → alias → FTS5 fuzzy match.

Per PRD §6.6.b every successful :func:`load_project` records a
``project_load`` row in the ``refs`` table — that's the signal that drives
weekly retention decisions.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pace import frontmatter, wikilinks
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import PROJECTS_DIR

# Project directory names: alphanumerics, underscore, hyphen. Conservative on
# purpose — we want filesystems and wikilinks to behave consistently.
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class Project:
    """Lightweight handle for a project's on-disk and frontmatter state."""

    name: str
    root_dir: Path
    summary_path: Path
    notes_dir: Path
    title: str
    aliases: list[str]
    date_created: str
    date_modified: str

    @property
    def summary_relpath(self) -> str:
        return f"{PROJECTS_DIR}/{self.name}/summary.md"


# ---- Listing & resolution ---------------------------------------------


def list_projects(root: Path) -> list[Project]:
    """Return every project under ``projects/`` ordered by name.

    Reads frontmatter from disk so the result is correct even before a
    reindex has caught up. Projects without a ``summary.md`` are skipped
    — they're not yet first-class.
    """
    base = root / PROJECTS_DIR
    if not base.is_dir():
        return []
    out: list[Project] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        proj = _load_project_from_disk(root, child.name)
        if proj is not None:
            out.append(proj)
    return out


def resolve(root: Path, name_or_alias: str, index: Index) -> Project | None:
    """Map a free-form name to a :class:`Project`, or ``None`` if unknown.

    Order: exact directory match → alias frontmatter match → FTS5 fuzzy
    match against project_summary content, titles, and aliases.
    """
    if not name_or_alias:
        return None

    # 1. Exact directory match.
    if _PROJECT_NAME_RE.match(name_or_alias):
        proj = _load_project_from_disk(root, name_or_alias)
        if proj is not None:
            return proj

    # 2. Alias match (case-insensitive).
    needle = name_or_alias.strip().lower()
    for proj in list_projects(root):
        if any(a.strip().lower() == needle for a in proj.aliases):
            return proj
        # Also match title for friendlier resolution: "Project Alpha" → Alpha.
        if proj.title.strip().lower() == needle:
            return proj

    # 3. FTS5 fuzzy across project_summary text. Pick the first hit whose
    # project we can still load from disk (defends against stale indexes).
    try:
        hits = index.search(name_or_alias, scope="projects", limit=5)
    except Exception:
        # FTS5 syntax errors on user input shouldn't crash resolution.
        hits = []
    for hit in hits:
        if hit.kind == "project_summary" and hit.project:
            proj = _load_project_from_disk(root, hit.project)
            if proj is not None:
                return proj

    return None


# ---- Mutations --------------------------------------------------------


def create_project(
    root: Path,
    name: str,
    *,
    index: Index,
    aliases: list[str] | None = None,
    title: str | None = None,
) -> Project:
    """Create a new project directory with an empty ``summary.md``."""
    if not _PROJECT_NAME_RE.match(name):
        raise ValueError(
            f"Project name {name!r} must start with a letter or digit and "
            "contain only letters, digits, underscores, and hyphens."
        )

    project_dir = root / PROJECTS_DIR / name
    if project_dir.exists():
        raise FileExistsError(f"Project {name!r} already exists at {project_dir}.")

    project_dir.mkdir(parents=True)
    notes_dir = project_dir / "notes"
    notes_dir.mkdir()

    fm = {
        "title": title or _humanize(name),
        "kind": "project_summary",
        "date_created": now_iso(),
        "date_modified": now_iso(),
        "aliases": _normalize_aliases(aliases or []),
        "tags": [],
    }
    summary_path = project_dir / "summary.md"
    atomic_write_text(summary_path, frontmatter.dump(fm, ""))

    rel = f"{PROJECTS_DIR}/{name}/summary.md"
    index.upsert_file(
        path=rel,
        kind="project_summary",
        project=name,
        title=str(fm["title"]),
        body="",
        aliases=list(fm["aliases"]),
        tags=[],
        date_created=str(fm["date_created"]),
        date_modified=str(fm["date_modified"]),
    )

    return _project_from_fm(root, name, fm)


def load_project(
    root: Path,
    name_or_alias: str,
    *,
    index: Index,
) -> tuple[Project, str] | None:
    """Resolve, read ``summary.md``, and record a ``project_load`` ref.

    Returns ``(project, summary_body)`` on success or ``None`` if no
    project matched. The ``project_load`` row is *only* recorded on a
    successful resolve — failed lookups don't pollute reference counts.
    """
    proj = resolve(root, name_or_alias, index)
    if proj is None:
        return None

    text = proj.summary_path.read_text(encoding="utf-8")
    _, body = frontmatter.parse(text)

    target_id = index.get_id(proj.summary_relpath)
    if target_id is not None:
        index.record_ref(target_id=target_id, ref_type="project_load")

    return proj, body


def add_alias(root: Path, name: str, alias: str, *, index: Index) -> Project:
    """Add ``alias`` to a project's frontmatter and re-index."""
    proj = _require_project(root, name)
    aliases = _normalize_aliases([*proj.aliases, alias])
    return _rewrite_summary_aliases(root, proj, aliases, index=index)


def remove_alias(root: Path, name: str, alias: str, *, index: Index) -> Project:
    """Remove ``alias`` from a project's frontmatter and re-index."""
    proj = _require_project(root, name)
    needle = alias.strip().lower()
    aliases = [a for a in proj.aliases if a.strip().lower() != needle]
    return _rewrite_summary_aliases(root, proj, aliases, index=index)


def rename_project(
    root: Path,
    old_name: str,
    new_name: str,
    *,
    index: Index,
) -> Project:
    """Rename a project on disk and rewrite every wikilink that references it.

    Steps:
        1. Validate the new name is well-formed and unused.
        2. Rename the directory on disk.
        3. Rewrite ``[[Old]]`` and ``[[projects/Old/...]]`` wikilinks across
           every markdown file in the vault.
        4. Re-index every file that changed (capture & vault.reindex layers
           can both be used; here we do a targeted re-import).
    """
    if old_name == new_name:
        return _require_project(root, old_name)
    if not _PROJECT_NAME_RE.match(new_name):
        raise ValueError(
            f"New name {new_name!r} must start with alnum and contain only "
            "letters, digits, underscores, and hyphens."
        )

    old_dir = root / PROJECTS_DIR / old_name
    new_dir = root / PROJECTS_DIR / new_name
    if not old_dir.is_dir():
        raise FileNotFoundError(f"Project {old_name!r} not found at {old_dir}.")
    if new_dir.exists():
        raise FileExistsError(f"Project {new_name!r} already exists at {new_dir}.")

    # Step 1: collect old paths before moving so we can drop them from the
    # index (the FTS5 path keys won't match the new locations).
    old_paths = [
        f"{PROJECTS_DIR}/{old_name}/{p.relative_to(old_dir).as_posix()}"
        for p in old_dir.rglob("*.md")
        if p.is_file()
    ]

    # Capture whether the title was auto-derived so we can keep it in sync.
    old_proj = _require_project(root, old_name)
    title_was_auto = old_proj.title == _humanize(old_name)

    # Step 2: move directory.
    shutil.move(str(old_dir), str(new_dir))

    # If the title was the auto-derived form, refresh it to match the new name
    # so `pace project list` and the model see a coherent display name.
    if title_was_auto:
        new_summary = new_dir / "summary.md"
        text = new_summary.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
        fm["title"] = _humanize(new_name)
        fm["date_modified"] = now_iso()
        atomic_write_text(new_summary, frontmatter.dump(fm, body))

    # Step 3: rewrite wikilinks across the whole vault.
    mapping = {
        old_name: new_name,
        f"{PROJECTS_DIR}/{old_name}/": f"{PROJECTS_DIR}/{new_name}/",
    }
    rewritten_files: list[Path] = []
    for md in _walk_vault_markdown(root):
        text = md.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
        new_body, count = wikilinks.rewrite(body, mapping)
        if count > 0:
            fm["date_modified"] = now_iso()
            atomic_write_text(md, frontmatter.dump(fm, new_body))
            rewritten_files.append(md)

    # Step 4: drop old index rows; re-import the renamed project's files
    # plus any rewritten files so the index is in sync without a full reindex.
    for op in old_paths:
        index.delete_file(op)
    for path in [*new_dir.rglob("*.md"), *rewritten_files]:
        if path.is_file():
            _reimport_file(root, path, index=index)

    return _require_project(root, new_name)


# ---- Internals --------------------------------------------------------


def _require_project(root: Path, name: str) -> Project:
    proj = _load_project_from_disk(root, name)
    if proj is None:
        raise FileNotFoundError(f"Project {name!r} not found.")
    return proj


def _load_project_from_disk(root: Path, name: str) -> Project | None:
    project_dir = root / PROJECTS_DIR / name
    summary = project_dir / "summary.md"
    if not summary.is_file():
        return None
    fm, _ = frontmatter.parse(summary.read_text(encoding="utf-8"))
    return _project_from_fm(root, name, fm)


def _project_from_fm(root: Path, name: str, fm: dict) -> Project:
    project_dir = root / PROJECTS_DIR / name
    return Project(
        name=name,
        root_dir=project_dir,
        summary_path=project_dir / "summary.md",
        notes_dir=project_dir / "notes",
        title=str(fm.get("title") or _humanize(name)),
        aliases=list(fm.get("aliases") or []),
        date_created=str(fm.get("date_created") or now_iso()),
        date_modified=str(fm.get("date_modified") or now_iso()),
    )


def _rewrite_summary_aliases(
    root: Path,
    proj: Project,
    aliases: list[str],
    *,
    index: Index,
) -> Project:
    aliases = _normalize_aliases(aliases)
    text = proj.summary_path.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    fm["aliases"] = aliases
    fm["date_modified"] = now_iso()
    atomic_write_text(proj.summary_path, frontmatter.dump(fm, body))

    index.upsert_file(
        path=proj.summary_relpath,
        kind="project_summary",
        project=proj.name,
        title=str(fm.get("title") or proj.title),
        body=body,
        aliases=aliases,
        tags=list(fm.get("tags") or []),
        date_created=str(fm.get("date_created") or proj.date_created),
        date_modified=str(fm.get("date_modified")),
    )
    return _project_from_fm(root, proj.name, fm)


def _reimport_file(root: Path, md: Path, *, index: Index) -> None:
    """Re-index a single file from disk. Called by rename to keep refs current."""
    rel = md.relative_to(root).as_posix()
    fm, body = frontmatter.parse(md.read_text(encoding="utf-8"))

    kind = _kind_from_path(rel)
    if kind is None:
        return
    project = _project_from_path(rel)

    fid = index.upsert_file(
        path=rel,
        kind=kind,
        project=project,
        title=str(fm.get("title") or _humanize(Path(rel).stem)),
        body=body,
        aliases=list(fm.get("aliases") or []),
        tags=list(fm.get("tags") or []),
        date_created=str(fm.get("date_created") or now_iso()),
        date_modified=str(fm.get("date_modified") or now_iso()),
    )

    # Refresh wikilink refs originating at this file.
    index.clear_wikilink_refs_from(fid)
    paths_to_ids = index.all_paths_with_ids()
    for link in wikilinks.extract(body):
        target_id = wikilinks.resolve(link.target, paths_to_ids)
        if target_id is not None and target_id != fid:
            index.record_ref(
                source_id=fid,
                target_id=target_id,
                ref_type="wikilink",
            )


def _walk_vault_markdown(root: Path):
    for sub in ("memories", PROJECTS_DIR):
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if path.is_file():
                yield path


def _kind_from_path(rel: str) -> str | None:
    parts = rel.split("/")
    if rel == "memories/working_memory.md":
        return "working"
    if parts[:2] == ["memories", "long_term"]:
        return "long_term"
    if parts[:2] == ["memories", "archived"]:
        return "archived"
    if len(parts) >= 3 and parts[0] == PROJECTS_DIR:
        if parts[-1] == "summary.md" and len(parts) == 3:
            return "project_summary"
        if "notes" in parts:
            return "project_note"
    return None


def _project_from_path(rel: str) -> str | None:
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == PROJECTS_DIR:
        return parts[1]
    return None


def _normalize_aliases(aliases: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        a = raw.strip()
        if not a:
            continue
        key = a.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _humanize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", name).strip().title()
