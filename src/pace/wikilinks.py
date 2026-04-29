"""Obsidian-style ``[[Wikilink]]`` parsing, resolution, and rewriting.

A wikilink may take any of:

* ``[[target]]`` — bare target.
* ``[[target|display]]`` — pipe-aliased display text (we keep ``target``).
* ``[[target#section]]`` — section anchor (we keep ``target`` only).
* ``[[target#section|display]]`` — both.

Phase 2 uses this module for two jobs:

1. After every file write, record outbound wikilinks into the ``refs`` table
   so reference counts drive pruning correctly (PRD §7.1).
2. When a project is renamed, rewrite every wikilink that points at the old
   name so cross-file references survive the move (PRD acceptance, Phase 2).

Resolution against the file index is heuristic — wikilinks aren't typed —
but covers the cases PACE actually emits: project summaries by name, long-
term topic files by stem, and explicit relative paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A non-greedy match between ``[[`` and ``]]`` so multiple links on one line
# don't merge. Targets cannot contain ``[``, ``]``, ``|``, ``#``.
_WIKILINK_RE = re.compile(r"\[\[([^\]\[\|#]+)((?:#[^\]\[\|]+)?)(\|[^\]\[]+)?\]\]")


@dataclass(frozen=True)
class WikilinkMatch:
    """One occurrence of a wikilink, with enough context to rewrite it."""

    target: str         # The unmodified target text inside the brackets.
    section: str        # Including the leading ``#`` if present, else "".
    display: str        # Including the leading ``|`` if present, else "".
    span: tuple[int, int]  # (start, end) in the original body.

    def render(self, new_target: str) -> str:
        return f"[[{new_target}{self.section}{self.display}]]"


def extract(body: str) -> list[WikilinkMatch]:
    """Return all wikilinks in ``body`` in source order."""
    out: list[WikilinkMatch] = []
    for m in _WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if not target:
            continue
        out.append(
            WikilinkMatch(
                target=target,
                section=m.group(2) or "",
                display=m.group(3) or "",
                span=m.span(),
            )
        )
    return out


def resolve(target: str, index_paths: dict[str, int]) -> int | None:
    """Map a wikilink target to a file id, or ``None`` if no match.

    Tries (in order): exact path match (with and without ``.md``), the
    common topic locations (``memories/long_term/<x>.md``), the project
    summary location (``projects/<x>/summary.md``), and finally a
    case-insensitive stem match across all indexed paths.
    """
    candidates = _candidate_paths(target)
    for cand in candidates:
        if cand in index_paths:
            return index_paths[cand]

    # Fallback: case-insensitive stem comparison.
    target_stem = Path(target).stem.lower()
    if target_stem:
        for path, fid in index_paths.items():
            if Path(path).stem.lower() == target_stem:
                return fid
    return None


def rewrite(body: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Replace wikilink targets that match keys in ``mapping``.

    Match is exact on the target string. Returns ``(new_body, count)``.
    Used by project rename to swap ``[[Old]]`` → ``[[New]]`` and
    ``[[projects/Old/...]]`` → ``[[projects/New/...]]`` across the vault.
    """
    if not mapping:
        return body, 0

    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        target = match.group(1).strip()
        section = match.group(2) or ""
        display = match.group(3) or ""

        new_target = _apply_mapping(target, mapping)
        if new_target != target:
            count += 1
            return f"[[{new_target}{section}{display}]]"
        return match.group(0)

    new_body = _WIKILINK_RE.sub(_replace, body)
    return new_body, count


# ---- Internals --------------------------------------------------------


def _candidate_paths(target: str) -> list[str]:
    """Generate plausible vault-relative paths for a wikilink target."""
    # Normalize backslashes — wikilinks should always use forward slashes.
    norm = target.replace("\\", "/").strip("/")
    candidates = [
        norm,
        f"{norm}.md" if not norm.endswith(".md") else norm,
        f"memories/long_term/{norm}.md",
        f"memories/long_term/{norm.lower()}.md",
        f"projects/{norm}/summary.md",
    ]
    # Stable de-dup preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _apply_mapping(target: str, mapping: dict[str, str]) -> str:
    """Apply rename mapping to a wikilink target.

    Two rewrite shapes are supported:

    * Exact target match — ``[[Old]]`` → ``[[New]]`` when ``Old`` is a key.
    * Path-prefix match — ``[[projects/Old/foo]]`` →
      ``[[projects/New/foo]]`` when the mapping carries a ``projects/Old/``
      key prefix.
    """
    if target in mapping:
        return mapping[target]
    for old, new in mapping.items():
        if old.endswith("/") and target.startswith(old):
            return new + target[len(old):]
    return target
