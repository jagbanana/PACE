"""Capture an entry into the right markdown file and update the index.

Phase 1 added ``working`` + ``long_term``. Phase 2 adds ``project_summary``
and ``project_note``, both of which require a project that already exists
on disk.

File layout — every captured entry within a file is a level-2 heading
(``## YYYY-MM-DD HH:MM — #tags``) followed by a blank line and the body.
This keeps Obsidian's outline view useful as the file grows.

After every write, outbound ``[[Wikilinks]]`` are re-extracted and the
``refs`` table is refreshed so reference counts stay accurate (PRD §7.1).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pace import frontmatter, wikilinks
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import LONG_TERM_DIR, PROJECTS_DIR, WORKING_MEMORY

_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def capture(
    root: Path,
    *,
    kind: str,
    content: str,
    index: Index,
    tags: list[str] | None = None,
    topic: str | None = None,
    project: str | None = None,
    note: str | None = None,
) -> Path:
    """Append ``content`` to the appropriate vault file and update the index.

    Returns the absolute path of the file that was written.

    Required extras per kind:
        working          — none
        long_term        — ``topic``
        project_summary  — ``project`` (must already exist)
        project_note     — ``project`` and ``note`` slug
    """
    target, default_title, project_name = _resolve_target(
        root, kind=kind, topic=topic, project=project, note=note
    )

    tags = _normalize_tags(tags or [])
    timestamp = datetime.now().replace(microsecond=0)

    fm, body = _load_or_init(
        target, kind=kind, title=default_title, project=project_name
    )

    new_entry = _format_entry(timestamp, tags, content)
    new_body = _append_entry(body, new_entry)
    fm["date_modified"] = now_iso()
    file_tags = sorted(set(fm.get("tags") or []) | set(tags))
    fm["tags"] = file_tags

    atomic_write_text(target, frontmatter.dump(fm, new_body))

    rel_path = target.relative_to(root).as_posix()
    fid = index.upsert_file(
        path=rel_path,
        kind=kind,
        project=project_name,
        title=str(fm.get("title") or default_title),
        body=new_body,
        aliases=list(fm.get("aliases") or []),
        tags=file_tags,
        date_created=str(fm.get("date_created") or now_iso()),
        date_modified=str(fm.get("date_modified")),
    )

    _refresh_wikilink_refs(fid, new_body, index)
    return target


# ---- Target resolution ------------------------------------------------


def _resolve_target(
    root: Path,
    *,
    kind: str,
    topic: str | None,
    project: str | None,
    note: str | None,
) -> tuple[Path, str, str | None]:
    """Decide which file to append to. Returns (path, default_title, project)."""
    if kind == "working":
        return root / WORKING_MEMORY, "Working Memory", None

    if kind == "long_term":
        if not topic:
            raise ValueError("long_term capture requires --topic")
        slug = _slugify(topic)
        return root / LONG_TERM_DIR / f"{slug}.md", _humanize(topic), None

    if kind == "project_summary":
        if not project:
            raise ValueError("project_summary capture requires --project")
        target = root / PROJECTS_DIR / project / "summary.md"
        if not target.is_file():
            raise FileNotFoundError(
                f"Project {project!r} does not exist. Create it with "
                "`pace project create` first."
            )
        return target, _humanize(project), project

    if kind == "project_note":
        if not project:
            raise ValueError("project_note capture requires --project")
        if not note:
            raise ValueError("project_note capture requires --note")
        notes_dir = root / PROJECTS_DIR / project / "notes"
        if not notes_dir.is_dir():
            raise FileNotFoundError(
                f"Project {project!r} does not exist. Create it with "
                "`pace project create` first."
            )
        slug = _slugify(note)
        return notes_dir / f"{slug}.md", _humanize(note), project

    raise ValueError(
        f"Unknown capture kind {kind!r}. "
        "Expected: working, long_term, project_summary, project_note."
    )


# ---- File helpers ------------------------------------------------------


def _load_or_init(
    target: Path,
    *,
    kind: str,
    title: str,
    project: str | None,
) -> tuple[dict, str]:
    """Return (frontmatter, body) for ``target``, creating defaults if absent."""
    if target.exists():
        text = target.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
        fm.setdefault("title", title)
        fm.setdefault("kind", kind)
        fm.setdefault("date_created", now_iso())
        fm.setdefault("tags", [])
        if project is not None:
            fm.setdefault("project", project)
        return fm, body

    target.parent.mkdir(parents=True, exist_ok=True)
    fm: dict = {
        "title": title,
        "kind": kind,
        "date_created": now_iso(),
        "date_modified": now_iso(),
        "tags": [],
    }
    if project is not None:
        fm["project"] = project
    return fm, ""


def _append_entry(body: str, entry: str) -> str:
    """Append ``entry`` to ``body`` separated by a blank line."""
    body = body.rstrip()
    if body:
        return f"{body}\n\n{entry}\n"
    return f"{entry}\n"


def _format_entry(timestamp: datetime, tags: list[str], content: str) -> str:
    header_tags = " ".join(tags)
    suffix = f" — {header_tags}" if header_tags else ""
    heading = f"## {timestamp.strftime('%Y-%m-%d %H:%M')}{suffix}"
    return f"{heading}\n\n{content.strip()}"


# ---- Refs --------------------------------------------------------------


def _refresh_wikilink_refs(file_id: int, body: str, index: Index) -> None:
    """Re-record outbound wikilink refs for ``file_id`` based on ``body``."""
    index.clear_wikilink_refs_from(file_id)
    paths_to_ids = index.all_paths_with_ids()
    for link in wikilinks.extract(body):
        target_id = wikilinks.resolve(link.target, paths_to_ids)
        if target_id is None or target_id == file_id:
            continue
        index.record_ref(
            source_id=file_id,
            target_id=target_id,
            ref_type="wikilink",
        )


# ---- Tag and slug normalization ---------------------------------------


def _normalize_tags(tags: list[str]) -> list[str]:
    """Ensure every tag begins with ``#`` and contains no whitespace."""
    cleaned: list[str] = []
    for raw in tags:
        t = raw.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t}"
        t = re.sub(r"\s+", "-", t)
        cleaned.append(t)
    seen: set[str] = set()
    out: list[str] = []
    for t in cleaned:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _slugify(topic: str) -> str:
    s = _NON_ALNUM_RE.sub("-", topic).strip("-").lower()
    if not s:
        raise ValueError(f"Topic {topic!r} produced an empty slug.")
    return s


def _humanize(topic: str) -> str:
    return _NON_ALNUM_RE.sub(" ", topic).strip().title()
