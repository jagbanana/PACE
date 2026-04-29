"""Capture an entry into the right markdown file and update the index.

Phase 1 supports ``kind`` ∈ {``working``, ``long_term``}. Project-scoped
captures (``project_summary``, ``project_note``) land in Phase 2.

File layout — every captured entry within a file is a level-2 heading
(``## YYYY-MM-DD HH:MM — #tags``) followed by a blank line and the body.
This keeps Obsidian's outline view useful as the file grows.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pace import frontmatter
from pace.index import Index, now_iso
from pace.io import atomic_write_text
from pace.paths import LONG_TERM_DIR, WORKING_MEMORY

_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def capture(
    root: Path,
    *,
    kind: str,
    content: str,
    index: Index,
    tags: list[str] | None = None,
    topic: str | None = None,
) -> Path:
    """Append ``content`` to the appropriate vault file and update the index.

    Returns the absolute path of the file that was written.
    """
    if kind == "working":
        target = root / WORKING_MEMORY
        default_title = "Working Memory"
    elif kind == "long_term":
        if not topic:
            raise ValueError("long_term capture requires --topic")
        slug = _slugify(topic)
        target = root / LONG_TERM_DIR / f"{slug}.md"
        default_title = _humanize(topic)
    else:
        raise ValueError(
            f"Phase 1 capture supports kind=working|long_term; got {kind!r}."
        )

    tags = _normalize_tags(tags or [])
    timestamp = datetime.now().replace(microsecond=0)

    fm, body = _load_or_init(target, kind=kind, title=default_title)

    new_entry = _format_entry(timestamp, tags, content)
    new_body = _append_entry(body, new_entry)
    fm["date_modified"] = now_iso()
    # Maintain the union of frontmatter tags and per-entry tags so that file-
    # level search filters keep working as files grow.
    file_tags = sorted(set(fm.get("tags") or []) | set(tags))
    fm["tags"] = file_tags

    atomic_write_text(target, frontmatter.dump(fm, new_body))

    rel_path = str(target.relative_to(root)).replace("\\", "/")
    index.upsert_file(
        path=rel_path,
        kind=kind,
        title=str(fm.get("title") or default_title),
        body=new_body,
        date_created=str(fm.get("date_created") or now_iso()),
        date_modified=str(fm.get("date_modified")),
        tags=file_tags,
    )
    return target


# ---- File helpers ------------------------------------------------------


def _load_or_init(
    target: Path, *, kind: str, title: str
) -> tuple[dict, str]:
    """Return (frontmatter, body) for ``target``, creating defaults if absent."""
    if target.exists():
        text = target.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
        # Guarantee the keys downstream code reads.
        fm.setdefault("title", title)
        fm.setdefault("kind", kind)
        fm.setdefault("date_created", now_iso())
        fm.setdefault("tags", [])
        return fm, body

    target.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "title": title,
        "kind": kind,
        "date_created": now_iso(),
        "date_modified": now_iso(),
        "tags": [],
    }
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
        # Replace internal whitespace with hyphens for safety.
        t = re.sub(r"\s+", "-", t)
        cleaned.append(t)
    # Stable de-dup preserving first occurrence.
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
