"""Followups — proactive items the assistant should resurface for the user.

A *followup* is a single Markdown file under ``followups/`` carrying:

- A trigger that determines when it transitions from ``pending`` to
  ``ready``. Trigger kinds:

  - ``date``    — ``trigger_value`` is an ISO date (``YYYY-MM-DD``);
                  the followup becomes ready when ``now >= that date``.
  - ``stale``   — emitted by the heartbeat scanner; lives at
                  ``status: ready`` from creation. ``trigger_value`` is
                  a short human description of what's stale.
  - ``pattern`` — emitted by the heartbeat scanner; lives at
                  ``status: ready`` from creation.
  - ``manual``  — an explicit user/agent ask to flag at the next
                  session. Lives at ``status: ready`` immediately.

- A status: ``pending`` (waiting on its trigger), ``ready`` (surface to
  the user at the next session start via ``pace_status``), or
  ``done`` / ``dismissed`` (resolved; file moved to ``followups/done/``).

- A free-form body explaining what to surface. Tone of the body is "the
  agent talking to itself"; the agent decides how to phrase it to the
  user when it surfaces.

Files are atomic; nothing here writes to the index. Followups don't
participate in FTS5 search — they're an inbox, not memory.

PRD reference: v0.2 heartbeat / followups.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from pace import frontmatter
from pace.io import atomic_write_text
from pace.paths import FOLLOWUPS_DIR, FOLLOWUPS_DONE_DIR

# ---- Constants -------------------------------------------------------

VALID_TRIGGERS: frozenset[str] = frozenset({"date", "stale", "pattern", "manual"})
VALID_STATUSES: frozenset[str] = frozenset({"pending", "ready", "done", "dismissed"})
VALID_PRIORITIES: frozenset[str] = frozenset({"low", "normal", "high"})

# Followup id shape: f-YYYYMMDD-HHMMSS-<6 hex>. Sortable by creation,
# collision-resistant for the bursts we expect (a heartbeat run might
# create 3-5 at once).
_ID_RE = re.compile(r"^f-\d{8}-\d{6}-[0-9a-f]{6}$")


# ---- Data model ------------------------------------------------------


@dataclass
class Followup:
    """One inbox item. Mutable so callers can flip status before saving."""

    id: str
    created: str               # ISO timestamp
    trigger: str               # one of VALID_TRIGGERS
    trigger_value: str         # interpretation depends on `trigger`
    status: str                # one of VALID_STATUSES
    priority: str              # one of VALID_PRIORITIES
    body: str                  # the prose to surface
    project: str | None = None
    source: str | None = None  # optional: pointer back to a source entry
    tags: list[str] = field(default_factory=list)

    def is_active(self) -> bool:
        return self.status in {"pending", "ready"}

    def to_frontmatter(self) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "id": self.id,
            "kind": "followup",
            "trigger": self.trigger,
            "trigger_value": self.trigger_value,
            "status": self.status,
            "priority": self.priority,
            "created": self.created,
        }
        if self.project:
            fm["project"] = self.project
        if self.source:
            fm["source"] = self.source
        if self.tags:
            fm["tags"] = list(self.tags)
        return fm


# ---- ID + filename helpers ------------------------------------------


def new_id(now: datetime | None = None) -> str:
    """Generate a new followup ID; sortable + collision-resistant."""
    now = now or datetime.now()
    rand = secrets.token_hex(3)
    return f"f-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"


def is_valid_id(s: str) -> bool:
    return bool(_ID_RE.match(s))


def _path_for(root: Path, fu_id: str, *, done: bool = False) -> Path:
    base = FOLLOWUPS_DONE_DIR if done else FOLLOWUPS_DIR
    return root / base / f"{fu_id}.md"


# ---- IO --------------------------------------------------------------


def add_followup(
    root: Path,
    *,
    body: str,
    trigger: str,
    trigger_value: str = "",
    project: str | None = None,
    priority: str = "normal",
    source: str | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    now: datetime | None = None,
) -> Followup:
    """Create a new followup file. Returns the persisted :class:`Followup`.

    ``status`` defaults to ``"pending"`` for ``trigger=date`` and to
    ``"ready"`` for ``stale``, ``pattern``, and ``manual`` — those are
    creation-time-actionable; the date trigger is what we wait on.
    """
    if trigger not in VALID_TRIGGERS:
        raise ValueError(
            f"Invalid trigger {trigger!r}. Expected one of: "
            f"{sorted(VALID_TRIGGERS)}"
        )
    if priority not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority {priority!r}. Expected one of: "
            f"{sorted(VALID_PRIORITIES)}"
        )

    if status is None:
        status = "pending" if trigger == "date" else "ready"
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Expected one of: "
            f"{sorted(VALID_STATUSES)}"
        )

    now = now or datetime.now()
    fu = Followup(
        id=new_id(now),
        created=now.isoformat(timespec="seconds"),
        trigger=trigger,
        trigger_value=trigger_value or "",
        status=status,
        priority=priority,
        body=body.strip(),
        project=project,
        source=source,
        tags=list(tags or []),
    )
    _write(root, fu)
    return fu


def _write(root: Path, fu: Followup, *, done: bool = False) -> Path:
    target = _path_for(root, fu.id, done=done)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = frontmatter.dump(fu.to_frontmatter(), fu.body + "\n")
    atomic_write_text(target, text)
    return target


def read_followup(root: Path, fu_id: str) -> Followup | None:
    """Load a followup by id from the active dir or ``done/``. Returns
    ``None`` if not found anywhere."""
    for path in (_path_for(root, fu_id), _path_for(root, fu_id, done=True)):
        if path.is_file():
            return _parse_file(path)
    return None


def _parse_file(path: Path) -> Followup:
    text = path.read_text(encoding="utf-8")
    fm, body = frontmatter.parse(text)
    return Followup(
        id=str(fm.get("id") or path.stem),
        created=str(fm.get("created") or ""),
        trigger=str(fm.get("trigger") or "manual"),
        trigger_value=str(fm.get("trigger_value") or ""),
        status=str(fm.get("status") or "pending"),
        priority=str(fm.get("priority") or "normal"),
        body=body.rstrip(),
        project=_str_or_none(fm.get("project")),
        source=_str_or_none(fm.get("source")),
        tags=list(fm.get("tags") or []),
    )


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def list_followups(
    root: Path,
    *,
    status: str | None = None,
    project: str | None = None,
    include_done: bool = False,
) -> list[Followup]:
    """Return followups matching the given filters, sorted by id (i.e. by
    creation time, oldest first)."""
    out: list[Followup] = []
    dirs = [root / FOLLOWUPS_DIR]
    if include_done:
        dirs.append(root / FOLLOWUPS_DONE_DIR)
    for d in dirs:
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            if not is_valid_id(entry.stem):
                continue
            try:
                fu = _parse_file(entry)
            except (ValueError, OSError, yaml.YAMLError):
                # Corrupt frontmatter or transient FS error: skip,
                # don't crash the inbox read.
                continue
            if status and fu.status != status:
                continue
            if project and fu.project != project:
                continue
            out.append(fu)
    return out


def resolve_followup(
    root: Path, fu_id: str, *, status: str = "done"
) -> Followup | None:
    """Mark a followup ``done`` (or ``dismissed``) and move it under
    ``followups/done/``. Returns the resolved followup, or ``None`` if
    no active file with that id exists."""
    if status not in {"done", "dismissed"}:
        raise ValueError(
            f"resolve_followup status must be 'done' or 'dismissed'; "
            f"got {status!r}."
        )
    src = _path_for(root, fu_id)
    if not src.is_file():
        return None
    fu = _parse_file(src)
    fu.status = status
    _write(root, fu, done=True)
    try:
        src.unlink()
    except FileNotFoundError:
        # The atomic_write_text pattern emits to <target>.tmp + os.replace;
        # a concurrent observer could have unlinked it. Tolerate.
        pass
    return fu


def update_status(
    root: Path, fu_id: str, *, status: str
) -> Followup | None:
    """Set an active followup's status without moving it. Used to flip
    ``pending`` → ``ready`` when a date trigger fires."""
    if status not in {"pending", "ready"}:
        raise ValueError(
            f"update_status only supports active states ('pending', "
            f"'ready'); got {status!r}. Use resolve_followup for done/"
            f"dismissed."
        )
    src = _path_for(root, fu_id)
    if not src.is_file():
        return None
    fu = _parse_file(src)
    if fu.status == status:
        return fu
    fu.status = status
    _write(root, fu)
    return fu


# ---- Trigger evaluation ---------------------------------------------


def evaluate_date_triggers(
    root: Path, *, now: datetime | None = None
) -> list[Followup]:
    """Find pending date-triggered followups whose date has arrived.

    Returns the list of followups that *would* transition; the caller
    decides whether to apply the transition (the heartbeat plan/apply
    pattern keeps the LLM in the loop). Empty list if none ripe.
    """
    now = now or datetime.now()
    out: list[Followup] = []
    for fu in list_followups(root, status="pending"):
        if fu.trigger != "date":
            continue
        try:
            target = date.fromisoformat(fu.trigger_value)
        except (ValueError, TypeError):
            continue
        if now.date() >= target:
            out.append(fu)
    return out


# ---- Inbox shaping for pace_status -----------------------------------


def inbox_for_status(
    root: Path, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Build the ``inbox`` field surfaced by ``pace_status``.

    Returns up to ``limit`` ready followups, highest-priority first then
    oldest first within each priority bucket. Each entry is a small dict
    the model can mention naturally — id, body, trigger, project,
    priority. Active-only — done items aren't surfaced.
    """
    ready = [fu for fu in list_followups(root, status="ready")]
    priority_order = {"high": 0, "normal": 1, "low": 2}
    ready.sort(key=lambda f: (priority_order.get(f.priority, 1), f.id))
    return [
        {
            "id": fu.id,
            "body": fu.body,
            "trigger": fu.trigger,
            "trigger_value": fu.trigger_value,
            "project": fu.project,
            "priority": fu.priority,
        }
        for fu in ready[:limit]
    ]


__all__ = [
    "Followup",
    "VALID_PRIORITIES",
    "VALID_STATUSES",
    "VALID_TRIGGERS",
    "add_followup",
    "evaluate_date_triggers",
    "inbox_for_status",
    "is_valid_id",
    "list_followups",
    "new_id",
    "read_followup",
    "resolve_followup",
    "update_status",
]
