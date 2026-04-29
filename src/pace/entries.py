"""Parse and edit markdown append-log files.

PACE memory files (``working_memory.md``, ``memories/long_term/<topic>.md``,
``projects/<x>/notes/<note>.md``) follow a consistent shape: YAML
frontmatter, then a sequence of level-2 entries headed by
``## YYYY-MM-DD HH:MM — #tags``. Phase 5 needs to *remove* and *add*
entries during compaction — this module handles the splitting safely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Heading shape:  ## 2026-04-27 09:32 — #person #user
# The em-dash + tags are optional. Tags are not required to follow.
_ENTRY_HEADING_RE = re.compile(
    r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})(?: — (.+))?\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Entry:
    """One ``## YYYY-MM-DD HH:MM — #tags`` block within a memory file."""

    heading: str          # The full heading line, no trailing newline.
    timestamp: datetime   # Parsed from the heading.
    tags: list[str]       # Tags from the heading, each starts with '#'.
    body: str             # Everything between this heading and the next.

    @property
    def raw(self) -> str:
        """Render the entry back to source-form markdown."""
        body = self.body.rstrip("\n")
        return f"{self.heading}\n\n{body}\n" if body else f"{self.heading}\n"


def split(body: str) -> list[Entry]:
    """Split ``body`` into entries. Pre-heading content is dropped silently
    (callers should pass body without frontmatter)."""
    matches = list(_ENTRY_HEADING_RE.finditer(body))
    if not matches:
        return []

    out: list[Entry] = []
    for i, m in enumerate(matches):
        heading = m.group(0).rstrip()
        timestamp = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        tags_str = (m.group(2) or "").strip()
        tags = _parse_tags(tags_str)

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        # Trim the leading blank line(s) and trailing whitespace separator.
        entry_body = body[body_start:body_end].lstrip("\n").rstrip()
        out.append(
            Entry(heading=heading, timestamp=timestamp, tags=tags, body=entry_body)
        )
    return out


def join(entries: list[Entry]) -> str:
    """Render a list of entries back into a body string.

    Empty input returns ``""``. Non-empty returns each entry's :attr:`raw`
    form joined by a blank line separator, ending with a trailing newline.
    """
    if not entries:
        return ""
    parts = []
    for i, entry in enumerate(entries):
        if i > 0:
            parts.append("\n")  # blank line between entries
        parts.append(entry.raw)
    return "".join(parts)


def remove(body: str, heading: str) -> tuple[str, Entry | None]:
    """Remove the entry whose heading exactly matches ``heading``.

    Returns ``(new_body, removed_entry)``. If no match, the body is
    returned unchanged with ``removed_entry=None``.
    """
    entries = split(body)
    kept: list[Entry] = []
    removed: Entry | None = None
    for entry in entries:
        if removed is None and entry.heading == heading:
            removed = entry
            continue
        kept.append(entry)
    if removed is None:
        return body, None
    return join(kept), removed


def append(body: str, entry: Entry) -> str:
    """Append ``entry`` to ``body`` preserving the blank-line separator."""
    entries = split(body)
    entries.append(entry)
    return join(entries)


def _parse_tags(s: str) -> list[str]:
    if not s:
        return []
    out: list[str] = []
    for tok in s.split():
        tok = tok.strip()
        if tok.startswith("#"):
            out.append(tok)
    return out
