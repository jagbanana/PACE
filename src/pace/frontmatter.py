"""YAML frontmatter parser and serializer.

Frontmatter is the canonical metadata source for every PACE markdown file.
Schema is documented in PRD §6.5. This module is purposely loose about which
fields are present — validation lives at higher layers (capture, indexer).
"""

from __future__ import annotations

import re
from typing import Any

import yaml

# Match an opening ``---`` on the first line, then everything up to a closing
# ``---`` line, then the rest of the document. ``re.DOTALL`` so ``.`` spans
# newlines.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into (frontmatter dict, body string).

    If no frontmatter block is present, returns ``({}, text)``. Any leading
    blank lines between the frontmatter and the body are stripped — they're
    cosmetic separators emitted by :func:`dump`, not content.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm_text, body = match.groups()
    loaded = yaml.safe_load(fm_text) or {}
    if not isinstance(loaded, dict):
        # Frontmatter that isn't a mapping (e.g. a bare list) is invalid for
        # PACE; surface explicitly rather than silently dropping it.
        raise ValueError("Frontmatter must be a YAML mapping at the top of the file.")
    return loaded, body.lstrip("\n")


def dump(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize ``frontmatter`` and ``body`` to a single document string.

    ``sort_keys=False`` preserves the order callers pass in, which keeps the
    diff churn low when files are rewritten.
    """
    fm_text = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    # Ensure exactly one blank line between frontmatter and body, and that
    # the document ends with a newline.
    body = body.lstrip("\n")
    if body and not body.endswith("\n"):
        body = body + "\n"
    return f"---\n{fm_text}\n---\n\n{body}"
