# PACE Development Plan

**Companion document to:** `PACE PRD.md` v2.0
**Last Updated:** 2026-04-26
**Target Stack:** Python 3.11+, SQLite (FTS5), `mcp` Python SDK, Click for CLI, `portalocker` for file locking, `pyyaml` for frontmatter, `ruff` for linting, `pytest` for tests.

---

## Guiding Principles

- **Each phase ships a usable artifact.** No phase is purely refactor; each unlocks a real workflow.
- **CLI is the source of truth.** The MCP server is a thin wrapper. Anything testable is testable from the CLI without an LLM in the loop.
- **Acceptance criteria gate phase completion.** A phase isn't done until its checklist passes.
- **One PR per phase.** Each phase is a coherent reviewable unit.

---

## Phase 0 — Project Skeleton

**Goal:** a working Python project the next phase can build on.

**Scope**
- `git init` at repo root.
- Python project under `system/scripts/` using a `src/` layout (`pyproject.toml`, package at `pace/`).
- Dependencies: `click`, `mcp`, `pyyaml`, `portalocker`, `python-dateutil`. Dev: `pytest`, `ruff`.
- Entry points: `pace = "pace.cli:main"` and a runnable `mcp_server.py`.
- `.gitignore` for `__pycache__/`, `*.db`, `*.db-wal`, `*.db-shm`, `.venv/`, OneDrive sync markers.
- A trivial `pace --version` command.
- A trivial `pytest` test that imports the package.
- Ruff config (line length 100, target py311).

**Acceptance**
- [ ] `pip install -e .` succeeds in a fresh venv.
- [ ] `pace --version` prints a version.
- [ ] `pytest` collects and passes ≥1 test.
- [ ] `ruff check` is clean.
- [ ] Repo committed with a sensible first commit.

**Estimated effort:** 1–2 hours.

---

## Phase 1 — CLI Core + SQLite FTS5

**Goal:** a working memory store with capture and search, no projects yet.

**Scope**
- `pace/index.py` — opens/creates the SQLite DB, applies the schema from PRD §7.1, exposes `add_file()`, `update_file()`, `delete_file()`, `search()`, `mark_referenced()`. Uses WAL mode.
- `pace/frontmatter.py` — read/write YAML frontmatter on markdown files using `pyyaml`.
- `pace/capture.py` — append a captured entry to the right file with a fresh frontmatter block, then update the index in the same transaction.
- `pace/cli.py` — Click app with subcommands:
  - `pace init` — scaffolds folders (`memories/`, `memories/long_term/`, `memories/archived/`, `projects/`, `system/logs/`), creates `pace_index.db`, writes `.gitignore`, drops a stub `CLAUDE.md`. Idempotent.
  - `pace status` — prints initialization state, file counts, last compact/review dates (read from `config` table).
  - `pace capture --kind <k> [--tags ...] "<text>"` — `kind` ∈ {`working`, `long_term`}. (Project-scoped capture lands in Phase 2.)
  - `pace search "<query>" [--scope memory] [--limit N]` — FTS5 query, prints ranked hits with file path, title, snippet.
  - `pace reindex` — walks the vault, rebuilds the index from disk.
- Tests in `system/scripts/tests/`:
  - Round-trip: `init` → `capture` → `search` returns the captured entry.
  - Reindex: edit a markdown file directly → `reindex` → `search` finds the new content.
  - Frontmatter integrity: capture preserves existing frontmatter on append.

**Acceptance**
- [ ] `pace init` in an empty directory produces the expected tree and a valid empty SQLite DB.
- [ ] `pace capture --kind working "test entry"` writes to `memories/working_memory.md` with frontmatter and indexes it.
- [ ] `pace search "test"` returns the entry.
- [ ] `pace reindex` is idempotent and matches a fresh init's state.
- [ ] All tests pass; no Ruff warnings.

**Estimated effort:** 1 day.

---

## Phase 2 — Projects

**Goal:** project-scoped capture and retrieval.

**Scope**
- `pace/projects.py` — list/create/load/rename projects. A project is a directory under `projects/` with a `summary.md` and a `notes/` subdir.
- Extend `pace_index.db` schema to populate `project` and `kind` correctly for project files.
- Extend CLI:
  - `pace project list` — prints projects with last-touched timestamps.
  - `pace project create <name> [--alias ...]` — creates the dir, scaffolds an empty `summary.md` with frontmatter (including `aliases`), indexes it.
  - `pace project load <name>` — resolves name → exact dir match → alias match → FTS5 fuzzy. Prints `summary.md` content and inserts a `project_load` row into `refs`.
  - `pace project rename <old> <new>` — renames the directory, updates files, rewrites wikilinks across the vault.
  - `pace project alias <name> add <alias>` and `pace project alias <name> remove <alias>` — manage aliases without re-editing frontmatter by hand.
- Extend `pace capture` to accept `--kind project_summary | project_note` with required `--project <name>`.
- Wikilink helper: `pace/wikilinks.py` parses `[[...]]` references on every write and maintains the `references` table.
- Tests:
  - Create project → load returns the empty summary.
  - Capture project_note → search filtered by `--project` returns it.
  - Rename project → wikilinks elsewhere in the vault are rewritten.

**Acceptance**
- [ ] `pace project create Alpha` produces `/projects/Alpha/summary.md` and `/projects/Alpha/notes/` and indexes them.
- [ ] `pace project load Alpha` prints summary and bumps `reference_count`.
- [ ] Capture into a project + search-by-project works.
- [ ] Renaming preserves wikilinks. Test asserts no broken `[[...]]`.

**Estimated effort:** 1 day.

---

## Phase 3 — MCP Server

**Goal:** Cowork can invoke PACE through MCP tools. End of this phase, the model uses PACE in a real conversation.

**Scope**
- `system/scripts/mcp_server.py` — uses the `mcp` Python SDK. Exposes the tools from PRD §6.8 (`pace_status`, `pace_capture`, `pace_search`, `pace_load_project`, `pace_list_projects`, `pace_create_project`, `pace_init`).
- Tool descriptions written carefully — these are what the model reads to decide when to invoke. Each description:
  - States the tool's purpose in one sentence.
  - Lists when to call it (and when *not* to).
  - Shows a one-line example.
- `.mcp.json` template that registers the server. Generated by `pace init`.
- All MCP tools delegate to the same Python functions the CLI uses; no logic duplication.
- Manual test: register the MCP, restart Cowork, confirm tools appear and round-trip.
- Automated test: spawn the MCP server in a subprocess, send JSON-RPC, assert responses.

**Acceptance**
- [ ] `.mcp.json` generated at `pace init` registers the server correctly.
- [ ] After restarting Cowork, `pace_status` is callable and returns initialized state.
- [ ] A real conversation in Cowork can capture a fact and retrieve it later via search, with no slash commands or terminal use.
- [ ] Tool descriptions reviewed against the PRD to confirm they encode the intended invocation triggers.

**Estimated effort:** 1–2 days. Tuning the tool descriptions usually takes a second pass once you watch the model use them.

---

## Phase 4 — Onboarding

**Goal:** opening Cowork in an empty folder produces a fully-bootstrapped PACE root after one conversation.

**Scope**
- `pace/onboarding.py` — generates the runtime artifacts:
  - `CLAUDE.md` template with PACE instructions (see PRD §5.2).
  - `.mcp.json` with the PACE server registered.
  - Initial `working_memory.md` and a `long_term/user.md` stub for the user's name.
- `pace_init` MCP tool ensures these are produced atomically.
- CLAUDE.md template content includes:
  - Pointer that this is a PACE root.
  - Instruction: at session start, call `pace_status` and silently load `working_memory.md`.
  - Instruction: when the user mentions a project, call `pace_search` then `pace_load_project`.
  - Instruction: when the user states durable facts, call `pace_capture`.
  - Instruction: do **not** mention these tool calls to the user — the experience is invisible.
- Scheduled-task wiring: during onboarding, the model uses Cowork's `mcp__scheduled-tasks` MCP to register two tasks (daily compaction, weekly review). The exact onboarding conversation flow is specified in **PRD Appendix A — First-Run Onboarding Script**; the model follows that beat-by-beat.
- Manual end-to-end test: in a fresh empty folder, open Cowork, have a 3-minute conversation, confirm:
  - Folder structure is initialized.
  - User's name is captured.
  - Two scheduled tasks exist in Cowork.
  - `git log` shows an initial commit.

**Acceptance**
- [ ] Empty folder → fully-bootstrapped root after one conversation, with no manual file edits or terminal commands by the user.
- [ ] `git log` shows an initial commit produced by onboarding.
- [ ] Two scheduled tasks visible in Cowork's UI.
- [ ] CLAUDE.md content reviewed and pruned — every instruction in it earns its tokens.

**Estimated effort:** 2 days. Most of this is iterating on the CLAUDE.md prompt and onboarding conversation script.

---

## Phase 5 — Compaction & Review

**Goal:** scheduled tasks consolidate working memory daily and prune long-term memory weekly.

**Scope**
- `pace/compact.py` — daily compaction logic:
  - Read `working_memory.md` and entries with `date_modified` in last 24h.
  - Group redundant entries.
  - Apply promotion rules from PRD §6.10 to identify candidates.
  - Output a structured "compaction plan" (JSON) the LLM can review and apply.
  - Apply approved changes: merge, promote, update project `summary.md`s.
  - Log to `/system/logs/compact_<date>.log`.
- `pace/review.py` — weekly review logic:
  - Walk `/long_term/`, identify archival candidates per PRD §6.10.
  - Validate wikilinks across the vault.
  - Generate `/memories/long_term/weekly_<YYYY-WW>.md` synthesis.
  - Log to `/system/logs/review_<date>.log`.
- CLI: `pace compact` and `pace review` runnable manually for testing.
- Lockfile at `/system/.pace.lock` prevents overlap.
- **Execution model — Cowork-runtime only.** The scheduled-task prompts (registered in Phase 4) instruct Cowork to open the PACE folder, run `pace compact --plan` (or `pace review --plan`) to get a JSON list of merge/promote/archive candidates with the relevant file content, exercise judgment on each, and call back into the CLI to apply the approved changes. PACE never invokes the Anthropic API directly — no API key, no network calls. Tradeoff: tasks only run when Cowork is open; missed runs are caught up on next opportunity.
- Draft and version-control the actual scheduled-task prompts as part of this phase (`system/scripts/pace/prompts/compact.md` and `review.md`) so they're reviewable.
- Tests:
  - Promotion: seed `working_memory.md` with old entries, run `compact`, assert promotions occurred.
  - Archival: seed a stale `long_term/` entry, run `review`, assert it moved to `archived/`.
  - Lock contention: simulate two `compact` invocations, assert one waits or fails clearly.

**Acceptance**
- [ ] `pace compact` produces sensible promotions on a seeded vault.
- [ ] `pace review` archives stale entries and writes a weekly synthesis.
- [ ] Scheduled tasks run successfully on schedule for at least 3 consecutive days during testing.
- [ ] Logs in `/system/logs/` are human-readable and useful for debugging.

**Estimated effort:** 2–3 days.

---

## Phase 6 — Polish & Hardening

**Goal:** PACE is ready for daily use, not just demos.

**Scope**
- `pace doctor` — checks:
  - PACE root has "Always keep on this device" set on Windows (uses `attrib` or PowerShell).
  - SQLite DB integrity (`PRAGMA integrity_check`).
  - Index drift (file mtimes vs last-indexed timestamps).
  - Broken wikilinks.
  - Conflicted-copy files from OneDrive (`* (Conflicted Copy *).md`). Findings are surfaced through `pace_status` so the model raises them to the user at session start (PRD §7.2). Resolution is user-initiated — `pace doctor` never auto-deletes a conflict.
  - Missing or paused scheduled tasks.
- `pace archive <path>` — manual archival.
- Robust error messages for common failure modes (DB locked, OneDrive virtualization, missing project).
- `pace status` extended with health summary from `doctor`.
- Documentation: a README at the repo root with quickstart and troubleshooting. (Not a marketing doc — operational reference.)
- One-week dogfood: use PACE on the user's actual work for 7 days, file issues for everything that breaks the "I just talk to it" experience.

**Acceptance**
- [ ] `pace doctor` catches all known failure modes on synthetic broken vaults.
- [ ] One-week dogfood completed; success metrics from PRD §8 measured.
- [ ] No P0 bugs from dogfood remain unfixed.

**Estimated effort:** 2–3 days plus the dogfood week.

---

## Total Estimated Timeline

| Phase | Effort |
|---|---|
| 0 — Skeleton | 1–2 hours |
| 1 — CLI + FTS5 | 1 day |
| 2 — Projects | 1 day |
| 3 — MCP Server | 1–2 days |
| 4 — Onboarding | 2 days |
| 5 — Compaction & Review | 2–3 days |
| 6 — Polish | 2–3 days + 1 week dogfood |
| **Total active work** | **~10 working days** |
| **Total wall time** | **~3 weeks including dogfood** |

---

## Cross-Cutting Concerns

These apply across all phases — call out in code review, not as a phase of their own.

- **Atomic markdown writes.** Every file write goes through a `write_atomic()` helper (write temp + fsync + rename). Prevents OneDrive partial-sync corruption.
- **All paths via `pathlib`.** No `os.path.join`, no string concatenation. Prepares for future Mac support.
- **No print() in library code.** Use `logging` configured in `cli.py` and `mcp_server.py` entry points.
- **Frontmatter is canonical.** If filesystem and frontmatter disagree on `date_modified`, frontmatter wins; `pace doctor` reconciles.
- **MCP tool descriptions are PR-reviewed.** Treat them like UI copy — words matter, the model reads them every session.

---

## Definition of Done for v1

PACE is shippable when **all** of these are true:

1. PRD §8 success metrics are achieved during dogfood week.
2. Every phase's acceptance checklist is checked.
3. `pace doctor` returns clean on a healthy vault.
4. The user can describe their workflow as "I just talk to it" without explaining any PACE concept to a hypothetical observer.

Anything beyond — Mac support, hooks-based prompt injection, semantic search, multi-user — is **explicitly v1.1+**.
