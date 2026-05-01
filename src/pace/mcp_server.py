"""MCP server exposing PACE to Claude Cowork.

Tool surface mirrors PRD §6.8:

    pace_status              — always called early in a session
    pace_capture             — persist durable facts/decisions/etc.
    pace_search              — FTS5 lookup over the vault
    pace_load_project        — resolve + read a project's summary
    pace_list_projects       — enumerate projects
    pace_create_project      — scaffold a new project
    pace_init                — onboarding bootstrap

Maintenance tools (``compact``, ``review``, ``archive``, ``reindex``,
``doctor``) are intentionally **not** exposed as MCP tools. They belong
to scheduled tasks or manual CLI use; exposing them risks the model
running maintenance mid-session (PRD §6.8).

Each tool delegates to the same Python functions the CLI uses — there
is no logic duplication. Tool descriptions are written to drive correct
invocation; the model reads them every session, so they earn their
tokens.

The vault root is resolved via ``find_vault_root`` with the user-config
fallback **disabled**: the MCP server is bound to whatever folder
Claude Code opened (cwd walk-up) plus any explicit ``PACE_ROOT`` env
the per-vault ``.mcp.json`` injected. We deliberately skip the
``%APPDATA%\\pace\\config.json`` "default vault" pointer so that
opening a brand-new folder to set up a *second* PACE agent doesn't
leak the *first* vault's identity into the new session. See
``pace.paths.find_vault_root`` for the full chain.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from pace import doctor as doctor_ops
from pace import entries as entries_mod
from pace import followups as fu_ops
from pace import heartbeat as heartbeat_ops
from pace import projects as project_ops
from pace import settings as pace_settings
from pace import vault as vault_ops
from pace.capture import capture as capture_entry
from pace.frontmatter import parse as parse_frontmatter
from pace.index import Index
from pace.paths import (
    INDEX_DB,
    WORKING_MEMORY,
    find_vault_root,
    is_initialized,
)

# Reconfigure stdout/stderr the same way the CLI does so any error path
# emitting non-ASCII into a Windows cp1252 console doesn't crash the
# server. (FastMCP writes its protocol on stdout, but uses stderr for
# logging; both must be UTF-8 capable.)
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


mcp = FastMCP("PACE")


# ---- Helpers ----------------------------------------------------------


def _initialized_root() -> Path | None:
    """Return the vault root iff it exists and is initialized.

    ``use_user_config=False`` keeps the MCP server bound to the folder
    Claude Code opened (via cwd walk-up + ``PACE_ROOT`` env). This is
    what makes multiple PACE agents in different folders safe — a
    session opened in ``Bob/`` will never resolve to ``Misa/`` just
    because Misa happens to be the CLI's default-vault pointer in
    ``%APPDATA%\\pace\\config.json``.
    """
    root = find_vault_root(use_user_config=False)
    if root is None or not is_initialized(root):
        return None
    return root


def _open_index(root: Path) -> Index:
    return Index(root / INDEX_DB)


def _not_initialized_response() -> dict[str, Any]:
    return {
        "error": "Vault not initialized. Call pace_init first.",
        "initialized": False,
    }


_TRUNCATION_NOTICE = (
    "\n\n[older entries elided to fit hard cap; "
    "use pace_search to recall specific older content]\n"
)


# v0.2.1 lazy-maintenance thresholds. PACE no longer relies on external
# scheduled tasks; instead, ``pace_status`` flags when each maintenance
# task is due, and the session-start contract in CLAUDE.md tells the
# model to run them silently after greeting the user.

_COMPACT_AGE_HOURS = 24       # compaction is "due" 24h after last run
_REVIEW_AGE_DAYS = 7          # weekly review is "due" if 7d since last run


def _needs_compact(last_compact_iso: str | None, *, now: datetime) -> bool:
    """True if it's been at least 24h since the last compaction (or never)."""
    if last_compact_iso is None:
        return True
    try:
        last = datetime.fromisoformat(last_compact_iso)
    except ValueError:
        return True
    return (now - last) >= timedelta(hours=_COMPACT_AGE_HOURS)


def _needs_review(last_review_iso: str | None, *, now: datetime) -> bool:
    """True if it's at least 7d since the last weekly review (or never).

    Unlike compaction, weekly review is intentionally low-cadence — gating
    purely on age (not weekday) keeps the trigger predictable across
    timezones and missed weeks.
    """
    if last_review_iso is None:
        return True
    try:
        last = datetime.fromisoformat(last_review_iso)
    except ValueError:
        return True
    return (now - last) >= timedelta(days=_REVIEW_AGE_DAYS)


def _needs_heartbeat(
    settings: pace_settings.Settings, last_heartbeat_iso: str | None
) -> bool:
    """True if the heartbeat is opted-in and its run-window guard passes."""
    if not settings.heartbeat_enabled:
        return False
    decision = heartbeat_ops.should_run(settings, last_run_iso=last_heartbeat_iso)
    return decision.run


def _truncate_working_memory(body: str, hard_chars: int) -> str:
    """Return ``body`` capped at ``hard_chars`` for inclusion in pace_status.

    Compaction normally keeps working memory below the *soft* cap; the
    hard cap here is the safety net for "user fired off a flurry of
    captures between scheduled tasks." We keep the newest entries that
    fit and append a one-line notice so the model knows older content
    exists and is reachable via ``pace_search``.

    Falls back to a plain char-tail truncation if the body has no
    parseable entries — exotic shape, but better than silently
    returning a partial entry.
    """
    if len(body) <= hard_chars:
        return body

    parsed = entries_mod.split(body)
    if not parsed:
        return body[-hard_chars:]

    budget = hard_chars - len(_TRUNCATION_NOTICE)
    kept_reversed: list = []
    total = 0
    for entry in reversed(parsed):
        text = entry.raw
        addition = len(text) + (1 if kept_reversed else 0)
        if total + addition > budget and kept_reversed:
            break
        kept_reversed.append(entry)
        total += addition

    kept = list(reversed(kept_reversed))
    return entries_mod.join(kept) + _TRUNCATION_NOTICE




# ---- Tools ------------------------------------------------------------


@mcp.tool()
def pace_status() -> dict[str, Any]:
    """Get the vault's initialization state and a quick contents summary.

    CALL THIS at the start of every conversation, before greeting the user.
    Use the response to decide whether to enter onboarding (when
    ``initialized`` is false), to surface OneDrive conflicted-copy
    warnings, and to ground your first reply in ``working_memory`` —
    that field saves a follow-up call.

    Returns a dict with:
        initialized      — bool
        root             — absolute path of the vault, or null
        files            — counts by kind (working/long_term/...)
        last_compact     — ISO timestamp or null
        last_review      — ISO timestamp or null
        last_heartbeat   — ISO timestamp or null
        needs_compact    — bool. True if 24h+ since the last compaction.
                           When true, run `pace compact --plan` then
                           `--apply` silently AFTER replying to the
                           user's first message of the session.
        needs_review     — bool. True if 7d+ since the last weekly
                           review. Same lazy-pattern: handle silently
                           after the user has been greeted.
        needs_heartbeat  — bool. True if the heartbeat is opted-in and
                           ready to run (working hours, past cadence).
                           Run `pace heartbeat --plan/--apply` lazily;
                           findings surface via the next session's
                           inbox.
        working_memory   — body of memories/working_memory.md (or empty)
        inbox            — list of ready followups to surface at the
                           top of your first reply (highest priority
                           first); empty list if none. Resolve via
                           pace_resolve_followup once acted on.
        warnings         — list of human-readable issues to raise

    Example: ``pace_status()`` — no arguments.
    """
    # use_user_config=False: see _initialized_root() for rationale.
    root = find_vault_root(use_user_config=False)
    if root is None or not is_initialized(root):
        return {
            "initialized": False,
            "root": None,
            "files": {},
            "last_compact": None,
            "last_review": None,
            "last_heartbeat": None,
            "needs_compact": False,
            "needs_review": False,
            "needs_heartbeat": False,
            "working_memory": "",
            "inbox": [],
            "warnings": [],
        }

    wm_body = ""
    wm_path = root / WORKING_MEMORY
    settings = pace_settings.load(root)
    if wm_path.is_file():
        _, body = parse_frontmatter(wm_path.read_text(encoding="utf-8"))
        wm_body = _truncate_working_memory(body, settings.working_memory_hard_chars)

    inbox = fu_ops.inbox_for_status(root)

    idx = _open_index(root)
    try:
        counts = idx.count_by_kind()
        last_compact = idx.get_config("last_compact")
        last_review = idx.get_config("last_review")
        last_heartbeat = idx.get_config("last_heartbeat")
        # Source warnings from doctor so MCP and CLI never disagree about
        # which issues need surfacing.
        report = doctor_ops.run_all(root, idx)
    finally:
        idx.close()

    now = datetime.now()
    return {
        "initialized": True,
        "root": str(root),
        "files": counts,
        "last_compact": last_compact,
        "last_review": last_review,
        "last_heartbeat": last_heartbeat,
        "needs_compact": _needs_compact(last_compact, now=now),
        "needs_review": _needs_review(last_review, now=now),
        "needs_heartbeat": _needs_heartbeat(settings, last_heartbeat),
        "working_memory": wm_body,
        "inbox": inbox,
        "warnings": doctor_ops.report_to_warnings(report),
    }


@mcp.tool()
def pace_capture(
    kind: str,
    content: str,
    tags: list[str] | None = None,
    topic: str | None = None,
    project: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Persist a durable fact, decision, preference, or high-signal moment.

    CALL THIS when the user states something you'd want to remember next
    session — names, dates, decisions, preferences, corrections,
    validated approaches, anything tagged #high-signal in the PRD's
    content taxonomy. DO NOT capture conversational filler, code that's
    already in git, or cross-folder user facts that belong in Cowork's
    own auto-memory rather than this PACE root.

    Arguments:
        kind     — one of: working (default landing zone), long_term
                   (requires topic), project_summary (requires project),
                   project_note (requires project + note slug).
        content  — the text to save.
        tags     — optional list. The standard set drives search and
                   pruning: #person, #identifier, #date, #user,
                   #business, #preference, #decision, #high-signal.
                   The leading # is optional.
        topic    — required for kind=long_term; becomes the filename
                   under memories/long_term/<topic>.md.
        project  — required for kind=project_summary or project_note.
                   Project must already exist (call pace_create_project
                   first if needed).
        note     — required for kind=project_note; slug used for
                   projects/<project>/notes/<note>.md.

    Returns: ``{"path", "kind"}`` on success, or ``{"error"}``.

    Example: ``pace_capture(kind="long_term", topic="people",
        content="Alex is COO; prefers brevity over warmth in writing.",
        tags=["#person", "#user"])``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()

    idx = _open_index(root)
    try:
        path = capture_entry(
            root,
            kind=kind,
            content=content,
            tags=list(tags or []),
            topic=topic,
            project=project,
            note=note,
            index=idx,
        )
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}
    finally:
        idx.close()

    return {
        "path": path.relative_to(root).as_posix(),
        "kind": kind,
    }


@mcp.tool()
def pace_search(
    query: str,
    scope: str | None = None,
    project: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find vault entries matching a free-text query (SQLite FTS5).

    CALL THIS whenever the user mentions a topic, project, person, or
    fact you might already have notes on — before asking them to repeat
    context. Empty hits is a valid answer; don't synthesize content
    that isn't there.

    Arguments:
        query   — FTS5 query string. Supports phrases ("kickoff plan"),
                  prefixes (kick*), and column filters (title:Q3).
        scope   — 'memory' (working + long_term), 'projects' (summaries
                  + notes), 'all' (includes archived), or omit for
                  non-archived files. Default: omit.
        project — restrict to a single project's files.
        limit   — max hits, default 10.

    Returns: ``{"hits": [{"path", "title", "kind", "project", "snippet",
    "rank"}]}``. Snippets carry «match» markers for highlight.

    Example: ``pace_search(query="Q3 pricing", scope="memory", limit=5)``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()

    idx = _open_index(root)
    try:
        hits = idx.search(query, scope=scope, project=project, limit=limit)
    except ValueError as exc:
        return {"error": str(exc)}
    finally:
        idx.close()

    return {
        "hits": [
            {
                "path": h.path,
                "title": h.title,
                "kind": h.kind,
                "project": h.project,
                "snippet": h.snippet,
                "rank": h.rank,
            }
            for h in hits
        ]
    }


@mcp.tool()
def pace_load_project(name: str) -> dict[str, Any]:
    """Resolve a project by name/alias/title/fuzzy and return its summary.

    CALL THIS when the user signals a project context shift — by name
    ("let's work on Alpha"), alias ("the alpha effort"), title ("Project
    Alpha"), or topical keyword ("the onboarding redesign"). The call
    records a project_load reference (used by weekly pruning) and
    returns the canonical summary so you have current state before
    responding to the user's actual request.

    If nothing matches, the response carries an ``error`` field — ask
    the user to clarify rather than guessing. Never fabricate a project.

    Returns:
        ``{"project": {"name", "title", "aliases", "summary_path"},
           "summary": "<body>"}`` on success.
        ``{"error": "no project matched <name>"}`` otherwise.

    Example: ``pace_load_project(name="alpha effort")``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()

    idx = _open_index(root)
    try:
        result = project_ops.load_project(root, name, index=idx)
    finally:
        idx.close()

    if result is None:
        return {"error": f"No project matched {name!r}."}

    proj, summary_body = result
    return {
        "project": {
            "name": proj.name,
            "title": proj.title,
            "aliases": proj.aliases,
            "summary_path": proj.summary_relpath,
            "date_created": proj.date_created,
            "date_modified": proj.date_modified,
        },
        "summary": summary_body,
    }


@mcp.tool()
def pace_list_projects() -> dict[str, Any]:
    """List every project in the vault.

    CALL THIS when the user asks what they're working on, when
    pace_load_project failed and you want to suggest plausible matches,
    or when you need to disambiguate before creating a new project.

    Returns: ``{"projects": [{"name", "title", "aliases",
    "date_created", "date_modified"}]}``.

    Example: ``pace_list_projects()``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()

    out = []
    for proj in project_ops.list_projects(root):
        out.append(
            {
                "name": proj.name,
                "title": proj.title,
                "aliases": proj.aliases,
                "date_created": proj.date_created,
                "date_modified": proj.date_modified,
            }
        )
    return {"projects": out}


@mcp.tool()
def pace_create_project(
    name: str,
    aliases: list[str] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Create a new project directory with an empty summary.

    CALL THIS when the user introduces a new project ("starting work on
    the Q3 launch", "new project: Beta"). Pick a clean ``name``: must
    start with a letter or digit and contain only alphanumerics,
    hyphens, and underscores. Pass any informal names the user used as
    ``aliases`` so future references match without ambiguity.

    Returns:
        ``{"name", "title", "aliases", "summary_path"}`` on success.
        ``{"error"}`` if the name is invalid or the project already
        exists — in which case you can call pace_load_project on the
        existing one.

    Example: ``pace_create_project(name="Beta", aliases=["q3-launch"],
        title="Q3 Launch")``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()

    idx = _open_index(root)
    try:
        proj = project_ops.create_project(
            root, name, aliases=list(aliases or []), title=title, index=idx
        )
    except (ValueError, FileExistsError) as exc:
        return {"error": str(exc)}
    finally:
        idx.close()

    return {
        "name": proj.name,
        "title": proj.title,
        "aliases": proj.aliases,
        "summary_path": proj.summary_relpath,
    }


@mcp.tool()
def pace_add_followup(
    body: str,
    trigger: str = "manual",
    trigger_value: str = "",
    project: str | None = None,
    priority: str = "normal",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Queue a proactive item to resurface for the user later.

    CALL THIS when the user states a commitment to follow up on, asks
    you to remember to do something later, or describes a deadline you
    should flag as it approaches. The heartbeat (if enabled) and the
    next session's pace_status will surface ready items.

    Arguments:
        body          — what to surface to the user. Phrase it as a
                        sentence you'd actually say ("the legal review
                        is due Friday"), not as data.
        trigger       — when this becomes ready. One of:
                        - "date":   trigger_value is an ISO date
                                    (YYYY-MM-DD); status starts pending.
                        - "manual": ready immediately (default).
                        - "stale" / "pattern": reserved for the
                          heartbeat scanner; you generally won't pass
                          these directly.
        trigger_value — interpretation depends on trigger. Required
                        for trigger="date".
        project       — optional project name for grouping.
        priority      — "low", "normal" (default), or "high".
        tags          — optional list of #tags.

    Returns: ``{"id", "status", "trigger"}`` on success, or ``{"error"}``.

    Example: ``pace_add_followup(body="Remind me to circle back on the
        legal review", trigger="date", trigger_value="2026-05-02",
        priority="high")``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()
    try:
        fu = fu_ops.add_followup(
            root,
            body=body,
            trigger=trigger,
            trigger_value=trigger_value,
            project=project,
            priority=priority,
            tags=list(tags or []),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"id": fu.id, "status": fu.status, "trigger": fu.trigger}


@mcp.tool()
def pace_list_followups(
    status: str | None = None,
    project: str | None = None,
    include_done: bool = False,
) -> dict[str, Any]:
    """List followups in the vault's inbox.

    CALL THIS when the user asks "what am I forgetting?", "what do you
    have queued for me?", or any similar inbox-y question. The session-
    start `pace_status` already surfaces ready items, so during a
    session you mainly need this for "show me the pending stuff" or
    "what did I dismiss last week."

    Arguments:
        status       — filter to one of pending / ready / done /
                       dismissed. Default: all active (pending+ready).
        project      — restrict to one project's followups.
        include_done — set true to include resolved items.

    Returns: ``{"followups": [{"id", "status", "trigger",
        "trigger_value", "project", "priority", "body"}]}``.

    Example: ``pace_list_followups(status="ready")``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()
    items = fu_ops.list_followups(
        root, status=status, project=project, include_done=include_done
    )
    return {
        "followups": [
            {
                "id": fu.id,
                "status": fu.status,
                "trigger": fu.trigger,
                "trigger_value": fu.trigger_value,
                "project": fu.project,
                "priority": fu.priority,
                "body": fu.body,
            }
            for fu in items
        ]
    }


@mcp.tool()
def pace_resolve_followup(
    id: str, status: str = "done"
) -> dict[str, Any]:
    """Mark a followup done (or dismissed) and move it out of the inbox.

    CALL THIS once the user has acknowledged or acted on a followup you
    surfaced. Don't leave ready items lingering — they pollute every
    subsequent session start until resolved.

    Arguments:
        id     — the followup's id (returned in pace_status.inbox).
        status — "done" (default) if the user acted on it, or
                 "dismissed" if they waved it off.

    Returns: ``{"id", "status"}`` on success, or ``{"error"}``.

    Example: ``pace_resolve_followup(id="f-2026-05-02-091500-abc123",
        status="done")``
    """
    root = _initialized_root()
    if root is None:
        return _not_initialized_response()
    try:
        fu = fu_ops.resolve_followup(root, id, status=status)
    except ValueError as exc:
        return {"error": str(exc)}
    if fu is None:
        return {"error": f"No active followup with id {id!r}."}
    return {"id": fu.id, "status": fu.status}


@mcp.tool()
def pace_init(root: str | None = None) -> dict[str, Any]:
    """Bootstrap an uninitialized PACE vault — onboarding only.

    CALL THIS only during first-run onboarding (PRD Appendix A), after
    the user has supplied their name and a brief description of the
    work they'll be doing in this folder. After a successful init,
    immediately call pace_capture twice — once to save the user's
    name/role to long_term/user.md, once to save the work description
    to working_memory.md. Then offer to register the daily/weekly
    scheduled tasks.

    Arguments:
        root — optional explicit vault path. Defaults to PACE_ROOT env
               var or the server's CWD.

    Returns: ``{"root", "created_dirs", "created_files",
    "already_initialized"}``.

    Example: ``pace_init()`` — onboarding will pick up CWD/PACE_ROOT.
    """
    if root is not None:
        target = Path(root).expanduser().resolve()
    else:
        # ``find_vault_root`` returns None when PACE_ROOT points at an
        # uninitialized directory — which is exactly the case ``pace_init``
        # needs to handle. Prefer the env var over cwd so onboarding always
        # writes into the directory the user/Cowork pointed us at.
        env = os.environ.get("PACE_ROOT")
        if env:
            target = Path(env).expanduser().resolve()
        else:
            target = Path.cwd().resolve()
    target.mkdir(parents=True, exist_ok=True)
    result = vault_ops.init(target)
    return {
        "root": str(result.root),
        "created_dirs": result.created_dirs,
        "created_files": result.created_files,
        "already_initialized": result.already_initialized,
        "git_initialized": result.git_initialized,
    }


# ---- Entry point ------------------------------------------------------


def main() -> int:
    """Console-script entry point. Runs the MCP server over stdio."""
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
