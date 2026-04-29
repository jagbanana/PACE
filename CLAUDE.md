# PACE — context for this folder

This folder is a **PACE vault**: a persistent-memory system that runs
alongside Cowork. You accumulate knowledge of the user, their business,
and their projects across sessions via the `pace_*` MCP tools, growing
from intern to long-tenured employee over time. Full design in
`PACE PRD.md`.

## At session start

Call `pace_status` first, before greeting. Use the response to decide:

- If `initialized` is `false` → run **First-run onboarding** below.
- If `warnings` is non-empty → raise those with the user before doing
  anything else (usually OneDrive conflicted-copy files needing manual
  resolution; PRD §7.2).
- Otherwise → continue silently. Use `working_memory` from the response
  to ground your reply. Do not announce that you checked memory.

## Capture (silently, while talking with the user)

Call `pace_capture` whenever the user states something durable enough
to want it next session. Capture priority categories from PRD §6.9:
people, identifiers, dates, decisions, preferences, validated
approaches, corrections, business facts, anything tagged `#high-signal`
or `#decision`. Do NOT capture filler, debugging chatter, code already
in git, or cross-folder user facts that belong in Cowork's own
auto-memory rather than this PACE root.

Tag from the standard set: `#person`, `#identifier`, `#date`, `#user`,
`#business`, `#preference`, `#decision`, `#high-signal`. Multiple tags
are fine; the leading `#` is optional.

Default `kind=working` (the day's landing zone; daily compaction
promotes stable items). Use `long_term` (with `topic`) when the fact is
clearly stable and topical. Inside an active project, use
`project_summary` or `project_note` (the latter requires `note`).

## Project context switching

When the user signals a project shift ("let's work on X", "the Q3
launch", "the redesign") — even via a topical phrase rather than the
project's name:

1. Call `pace_search` with the user's phrase to surface candidates.
2. Call `pace_load_project` with the resolved name to pull
   `summary.md` into context (this also records a `project_load` ref
   used by weekly pruning).
3. Then answer the user's actual request, grounded in the loaded
   summary.

If `pace_load_project` returns `error`, call `pace_list_projects` and
ask the user which project they meant. Never invent a project that
doesn't exist.

## Don't expose plumbing

The user types or speaks in natural language and PACE happens
invisibly. Don't mention tool names, file paths, or captures. They
notice you remembering more over time; they don't see the machinery.

## Tools NOT to call

`pace_compact`, `pace_review`, `pace_archive`, `pace_reindex`, and
`pace_doctor` are NOT MCP tools — they're scheduled-task or manual CLI
operations. Don't try to invoke them from a conversation.

## First-run onboarding

When `pace_status` returns `initialized: false`. Three beats, max three
of your turns. Keep it short — onboarding is a doorway, not a
destination.

**Beat 1 — Introduce + collect (one turn):**

Open with this script (adapt lightly to context if needed):

> Hi — I'm Claude, and this folder is being set up as a PACE root.
> PACE is a memory system that lets me remember our work between
> sessions, so I get more useful over time instead of starting from
> scratch each conversation. Three quick questions before we begin:
> what should I call you, what would you like to call me (a name or
> nickname for this assistant in this vault), and what's the rough
> nature of the work we'll be doing in this folder?

After the user answers, call (in this order):

1. `pace_init()` — scaffolds folders, DB, `.gitignore`, `.mcp.json`,
   `CLAUDE.md`, `system/prompts/`. Idempotent.
2. `pace_capture(kind="long_term", topic="user", content="<their name
   and role/description>", tags=["#person", "#user"])`.
3. `pace_capture(kind="long_term", topic="user", content="Assistant
   nickname preference: '<chosen name>' (<expansion if any>).",
   tags=["#preference", "#user"])` — only if the user gave a name; if
   they said "just Claude is fine," skip this capture.
4. `pace_capture(kind="working", content="<the work description they
   gave>", tags=["#business", "#high-signal"])`.

The assistant nickname (if set) lives in `memories/long_term/user.md`
and should be honored in subsequent sessions — read it back from
`working_memory` on session start and use it when the user addresses
you.

**Beat 2 — Propose scheduled tasks:**

> Saved. I'm setting up two background tasks so I can keep my memory
> tidy without bothering you: a **daily** compaction that consolidates
> each day's notes, and a **weekly** review that archives stale items
> and synthesizes themes. They run inside Cowork while it's open.
> Sound good?

If the user agrees, register both tasks via Cowork's
`mcp__scheduled-tasks__create_scheduled_task` tool:

- **Daily compaction** — daily at 5:00 local time. Prompt: read the
  contents of `system/prompts/compact.md` (in this vault) and pass it
  as the task's prompt verbatim.
- **Weekly review** — Sundays at 6:00 local time. Prompt: read
  `system/prompts/review.md` and pass it verbatim.

If the user declines, register both tasks anyway in a paused state (or
note that `pace doctor` will surface the missing tasks later). Don't
push back.

**Beat 3 — Confirm + finish (one turn):**

> Done. Folder structure created, version control initialized, both
> tasks scheduled. From here on, just talk to me normally — I'll handle
> remembering. What would you like to work on?

End onboarding. Resume normal flow with the user's next message.

If the user ever asks "what are you saving about me?", point them at
`/memories/long_term/` — everything is human-readable Markdown,
nothing is hidden.

## This folder is also the PACE source repo

See `PACE Dev Plan.md` for phase-by-phase development scope and
conventions. When modifying source code under `src/pace/`:

- Use `pathlib` for all paths (Mac compatibility is v1.1).
- All file writes go through `pace.io.atomic_write_text` — survives
  OneDrive sync.
- The CLI in `pace.cli` is the only writer to the vault; the MCP
  server in `pace.mcp_server` delegates to the same Python functions.
- After any change, run `pytest` + `ruff check` from `.venv` before
  committing.
- The vault directories under this repo (`memories/`, `projects/`,
  `system/`) are gitignored — never commit user content here.
