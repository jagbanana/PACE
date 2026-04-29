# Product Requirements Document (PRD)

**Project Name:** PACE (Persistent AI Context Engine)
**Document Status:** V2.0 (Draft)
**Last Updated:** 2026-04-26
**Target Environment:** Windows 11, single-user, Claude Cowork desktop app. Python 3.11+, SQLite (FTS5), Git for versioning, Obsidian as the human-facing UI over the markdown vault.

---

## 1. Executive Summary

Working with an LLM today is like working with an extremely book-smart intern who knows an enormous amount about the world but nothing about *you* — your business, your projects, your style, your people. Every new session is a new intern. Cowork's projects and built-in memory soften this, but the fundamental problem — **the AI restarts cold every conversation** — remains.

**PACE is a local, Markdown-based memory system that grows the AI from intern to junior to senior over time.** It captures the facts, names, dates, preferences, decisions, and high-signal moments that surface during real work, indexes them, and brings them back in future sessions. Day by day and week by week, the AI's working knowledge of the user and the business compounds — until the assistant stops feeling like an intern and starts feeling like a long-tenured employee the user can groom and trust.

PACE is designed for **knowledge work, not just coding**: research, marketing, planning, strategy, and any other multi-week effort Cowork is well suited to.

The user interacts in **natural language only**. All capture, search, project-switching, and maintenance happens invisibly via an MCP server the model invokes on its own. There are no slash commands, no syntax to memorize.

---

## 2. Core Objectives & Goals

- **Grows With Use** — the AI's knowledge of the user and the business compounds session over session, evolving from generalist intern to trusted operator. This is the north star; every other objective serves it.
- **Captures What Matters** — facts, people, dates, preferences, decisions, and high-signal moments are persisted; conversational filler is not. (See §6.9 for the full content taxonomy.)
- **Tiered Memory** — a hot working memory plus a deeper long-term store, with promotion and pruning rules that mirror how a real employee's retention works.
- **Conversational Project Switching** — the AI swaps active project context based on natural-language cues, without strict commands.
- **Compliance & Simplicity** — only proven local technologies (Markdown, Python, SQLite). No vector databases, no cloud services.
- **Human Visibility** — the entire memory store is human-readable, navigable, and editable in Obsidian (`[[Wikilinks]]`, `#tags`, YAML frontmatter).
- **Seamless Invocation** — invoked by the model itself through MCP tools; the user never types a command.

---

## 3. Non-Goals (Out of Scope for v1)

- **No vector DB / embeddings** — FTS5 only. Compliance and simplicity outweigh semantic recall.
- **No cloud sync of state** — all writes are local.
- **No multi-user / multi-tenant** — single user, single machine.
- **No Mac support in v1** — Mac compatibility is a future-state goal for sharing with friends.
- **No custom UI** — Obsidian is the human-facing UI. PACE produces files Obsidian can render.
- **No replacement of Cowork's built-in auto-memory** — see §4.
- **No third-party telemetry** — nothing leaves the machine.
- **No background daemon** — scheduled work runs through Cowork's own scheduled-tasks system, not a separate service.

---

## 4. Relationship to Cowork's Built-in Auto-Memory

Cowork already ships an auto-memory system that stores user/feedback/project/reference memories at `~/.claude/projects/<dir>/memory/`. PACE does **not** replace it. The two are complementary:

| Concern | Cowork auto-memory | PACE |
|---|---|---|
| Scope | User-level, cross-project | Single PACE root folder |
| Storage | Flat markdown in `~/.claude/...` | Structured vault with `/memories`, `/projects`, `/system` |
| Indexing | None (loaded into prompt) | SQLite FTS5 search |
| Switching | N/A | Project context switches on natural language |
| Best for | Lasting facts about the user, their preferences, their tools | Project artifacts, working memory, business context for *this* engagement |

**Rule of thumb:** if a fact is true regardless of which folder Claude is invoked in, it belongs in Cowork auto-memory. If it's specific to the work happening inside the PACE root, it belongs in PACE.

---

## 5. System Architecture

PACE lives entirely inside a single root directory. The folder is git-tracked. The OneDrive folder containing the PACE root **must be configured "Always keep on this device"** to prevent virtualization of files SQLite needs to mmap.

### 5.1 Folder Structure

```
/PACE_Root/
├── .git/                          # Git repo, see §7.4
├── .gitignore                     # Excludes /system/pace_index.db* and OneDrive markers
├── .mcp.json                      # Registers the PACE MCP server with Cowork
├── CLAUDE.md                      # Thin prompt layer; tells the model PACE exists
├── /memories/
│   ├── working_memory.md          # Hot, current state. Loaded frequently.
│   ├── /long_term/                # Stable, factual knowledge. Topic-organized.
│   └── /archived/                 # Pruned but preserved memories.
├── /projects/
│   ├── /Project_Alpha/
│   │   ├── summary.md             # Canonical project context. Auto-maintained.
│   │   └── /notes/                # Free-form artifacts (docs, transcripts, lists).
│   └── /Project_Beta/
└── /system/
    ├── pace_index.db              # SQLite FTS5 index (gitignored).
    ├── pace_index.db-wal          # WAL file (gitignored).
    ├── pace_index.db-shm          # Shared memory (gitignored).
    ├── /scripts/                  # Python implementation.
    │   ├── pace.py                # CLI entry point.
    │   ├── mcp_server.py          # MCP server entry point.
    │   ├── /pace/                 # Python package.
    │   │   ├── cli.py
    │   │   ├── index.py           # SQLite FTS5 wrapper.
    │   │   ├── capture.py
    │   │   ├── compact.py
    │   │   ├── review.py
    │   │   ├── projects.py
    │   │   └── onboarding.py
    │   └── pyproject.toml
    └── /logs/                     # Append-only run logs for compact/review tasks.
```

### 5.2 Integration Layer — MCP Server + Thin CLAUDE.md

PACE is invoked by the model, not the user. Two layers make this seamless:

**1. The PACE MCP server** (`system/scripts/mcp_server.py`) exposes a small set of tools. Cowork sees them as native tools the model can call any time. Tool surface in §6.8.

**2. A thin `CLAUDE.md` at the PACE root** is auto-generated during onboarding and tells the model:
- This folder is a PACE root.
- The MCP tools `pace_*` are available and what each is for.
- At the start of a new conversation, call `pace_status` and silently load `working_memory.md`.
- When the user mentions a project by name or topic, call `pace_search` then `pace_load_project` to pull its `summary.md` into context before answering.
- When the user states a durable fact, preference, or update, call `pace_capture` to persist it.

The CLAUDE.md is intentionally short — long instructions get diluted. The MCP tool descriptions carry most of the weight.

> **Future enhancement (not v1):** a `UserPromptSubmit` hook that auto-runs `pace_search` against every prompt and injects relevant snippets. Makes retrieval invisible at the cost of token overhead. Defer until v1 is stable.

### 5.3 Indexing

- SQLite database with an FTS5 virtual table over all markdown files in `/memories/` and `/projects/`.
- Schema (§7.1) tracks: file path, title, body, tags, last_modified, file_type (memory/project_summary/project_note), project_name (nullable), reference_count.
- **Indexing trigger:** every PACE CLI write updates the index synchronously inside the same transaction. FTS5 inserts are sub-millisecond — no async needed.
- A `pace reindex` command rebuilds the index from disk for the case where the user edits markdown directly in Obsidian.
- Pre-write hook: `pace doctor` checks for index drift on session start (compares file mtimes to last-indexed timestamps) and reindexes touched files automatically.

### 5.4 System Lifecycle

The lifecycle has four states, each described in detail in §6:

0. **First-run onboarding** — empty folder → fully bootstrapped (§6.1).
1. **In-session capture** — facts persisted as the conversation produces them (§6.2).
2. **Daily compaction** — scheduled task consolidates working memory and project summaries (§6.3).
3. **Weekly deep review** — scheduled task prunes, archives, and synthesizes (§6.4).

---

## 6. Key Features & Requirements

### 6.1 First-Run Onboarding

**Trigger:** Cowork opens in a folder where `system/pace_index.db` does not exist.

**Detection:** the CLAUDE.md template (or a bootstrapping skill) instructs the model to call `pace_status` early. If the tool returns `{ "initialized": false }`, the model enters onboarding mode.

**Flow:**
1. Model introduces PACE in plain language and asks the user's name.
2. Model calls `pace_init` to scaffold the folder structure, initialize the SQLite DB, generate `.gitignore` and `.mcp.json`, and write the CLAUDE.md template.
3. Model calls `pace_capture` to save the user's name as the first long-term memory.
4. Model uses Cowork's `mcp__scheduled-tasks` MCP to register two scheduled tasks (daily compaction, weekly review). User sees these get created and can manage them in Cowork's task UI.
5. Model offers to commit the initial state to git (`git init` already happened in `pace_init`).
6. Model confirms onboarding is complete and asks what the user wants to work on.

**Acceptance:** opening Cowork in an empty folder leads to a fully-initialized PACE root after one conversation, with no manual file editing or terminal commands required from the user.

### 6.2 In-Session Capture

**Goal:** the high-signal content that lets the AI grow from intern to senior gets written to disk before the session ends or compacts.

**What to capture (priority categories — see §6.9 for full taxonomy):**
- **People** — colleagues, clients, vendors mentioned by name and their roles.
- **Names & identifiers** — account names, codenames, internal terms.
- **Dates & timelines** — deadlines, recurring events, project milestones.
- **Facts about the user** — role, working style, communication preferences, decision style.
- **Facts about the business** — products, KPIs, processes, regulatory constraints.
- **Preferences** — formats, tools, things to avoid.
- **Decisions** — the user picked X over Y, and why.
- **High-signal moments** — corrections ("no, do it this way"), validated approaches ("yes, that was right"), surprises.

**Mechanism:** the model calls `pace_capture` with:
- `content` — the text to save.
- `kind` — one of `working`, `long_term`, `project_summary`, `project_note`.
- `project` — name of the active project (required when `kind` involves a project).
- `tags` — list, drawn from the conventional set in §6.9 (e.g. `#person`, `#decision`, `#high-signal`).

`pace_capture` appends to the appropriate file with YAML frontmatter and updates the FTS5 index in the same transaction.

**What does NOT get captured:** conversational filler, code that's already in git, debugging steps already in commit messages, or anything Cowork's auto-memory would handle better (cross-folder user facts that aren't specific to this PACE root).

### 6.3 Daily Compaction

**Trigger:** scheduled task created at onboarding, runs once per day while Cowork is open.

**What it does:**
1. Reads `working_memory.md` and the last 24h of long-term writes.
2. Consolidates redundancies (multiple entries about the same fact get merged).
3. Promotes stable entries from `working_memory.md` into `/long_term/<topic>.md` based on the rules in §6.10.
4. Updates `summary.md` for any project touched in the last 24h.
5. Logs run results to `/system/logs/`.

**Implementation:** a `pace compact` CLI command, invoked by a scheduled Cowork task that runs Claude with a fixed prompt against the PACE folder. **The LLM judgment runs entirely inside Cowork's scheduled-task runtime** — PACE never calls the Anthropic API directly, never holds an API key, never reaches the network. Tradeoff: scheduled tasks only fire while Cowork is open on this machine; if the machine is off or Cowork is closed, the run is skipped and resumed on next opportunity.

### 6.4 Weekly Deep Review

**Trigger:** scheduled task, runs once per week.

**What it does:**
1. Audits interlinks across `/long_term/` — flags broken `[[Wikilinks]]`.
2. Archives long-term entries matching the pruning rules in §6.10 (move to `/archived/`).
3. Re-validates every active project's `summary.md` against its `/notes/`.
4. Generates a weekly synthesis note at `/memories/long_term/weekly_<YYYY-WW>.md` that summarizes themes and progress.
5. Logs run results.

Like daily compaction, weekly review executes entirely inside Cowork's scheduled-task runtime (no direct API).

### 6.5 Obsidian Integration

- **Wikilinks:** all internal references use `[[Filename]]`. The CLI provides a `pace link <from> <to>` helper that the model can call to maintain bidirectional links.
- **Tags:** `#tag` syntax in body and `tags:` array in frontmatter. The FTS5 index splits on tags for fast filtering.
- **Frontmatter:** required on every long-term and project file. Schema:
  ```yaml
  ---
  title: <human-readable title>
  date_created: <ISO-8601>
  date_modified: <ISO-8601>
  kind: long_term | project_summary | project_note
  tags: [<tag>, ...]
  related_projects: [[Project_Name]]
  aliases: [<alias>, ...]   # project_summary only — informal names the model can match against
  ---
  ```
  Reference counts are derived on demand from the `references` table (§7.1), not stored in frontmatter.

### 6.6 Natural-Language Project Context Switching

This was conflated in v1 of the PRD. v2 splits it into two distinct concerns:

**6.6.a — Intent detection (the model's job).**
The model recognizes from natural language that the user has shifted to a different project. Examples: *"let's work on Project B,"* *"switching gears to the marketing site,"* or even an indirect cue like *"can you draft the launch email?"* when "launch email" is a known artifact in a specific project. This is pure prompt engineering — handled by CLAUDE.md instructions and the MCP tool descriptions.

**6.6.b — Context loading (the CLI's job).**
Once intent is detected, the model calls `pace_load_project(name)`. The MCP server resolves the name in this order: (1) exact match against project directory names, (2) match against any project's `aliases` frontmatter field, (3) FTS5 fuzzy match across project titles, aliases, and `summary.md` content. It then reads `summary.md`, records a `project_load` reference (used in pruning — see §7.1), and returns the content. The model integrates that content into its working context before answering the user's actual request.

**Failure mode:** if `pace_load_project` returns no match, the model asks the user once for clarification rather than hallucinating a project.

### 6.7 CLI Command Surface

The Python CLI is the single source of truth for all writes. The MCP server is a thin wrapper around it. Direct human use of the CLI is supported but never required.

| Command | Purpose |
|---|---|
| `pace init` | Scaffold an empty PACE root. Idempotent. |
| `pace status` | Report initialization state, file counts, last compact/review dates. |
| `pace capture --kind <k> [--project <p>] [--tags ...] "<text>"` | Persist content. |
| `pace search "<query>" [--scope memory\|projects\|all] [--project <p>]` | FTS5 query, returns ranked snippets with file paths. |
| `pace project list` | Enumerate projects with last-touched timestamps. |
| `pace project create <name>` | Create a new project with empty summary. |
| `pace project load <name>` | Print `summary.md` (used by MCP). |
| `pace project rename <old> <new>` | Rename safely (preserves wikilinks). |
| `pace compact` | Run daily compaction. |
| `pace review` | Run weekly review. |
| `pace archive <path>` | Move a file to `/archived/`. |
| `pace reindex` | Rebuild the FTS5 index from disk. |
| `pace doctor` | Health check: OneDrive sync state, DB integrity, index drift, broken wikilinks. |

### 6.8 MCP Tool Surface

Exposed by the PACE MCP server. Names and descriptions matter — the model picks tools based on their descriptions, so they must be precise.

| Tool | Maps to |
|---|---|
| `pace_status` | `pace status` (always called early in a session) |
| `pace_capture` | `pace capture` |
| `pace_search` | `pace search` |
| `pace_load_project` | `pace project load` |
| `pace_list_projects` | `pace project list` |
| `pace_create_project` | `pace project create` |
| `pace_init` | `pace init` (used during onboarding) |

`compact`, `review`, `archive`, `reindex`, and `doctor` are **not** exposed as MCP tools. They're invoked by scheduled tasks or run by the user manually. Exposing them risks the model running maintenance mid-session.

### 6.9 Memory Taxonomy

PACE captures along two axes: **what kind of thing it is** (the content taxonomy) and **where it lives** (the file taxonomy). The model uses the content taxonomy to decide *whether* to capture; the file taxonomy decides *where it goes*.

#### 6.9.a Content Taxonomy — what's worth remembering

These are the categories the model is trained (via CLAUDE.md and tool descriptions) to recognize and capture. Each carries a conventional tag that drives both search and pruning.

| Category | Examples | Tag |
|---|---|---|
| **People** | Colleagues, clients, vendors mentioned by name. Their role, reporting line, what they care about. | `#person` |
| **Names & identifiers** | Account names, codenames, internal jargon, product SKUs. | `#identifier` |
| **Dates & timelines** | Deadlines, recurring events, milestones, anniversaries of decisions. | `#date` |
| **Facts about the user** | Role, working hours, communication style, decision style, what they delegate vs own. | `#user` |
| **Facts about the business** | Products, KPIs, processes, regulatory constraints, customers, vendors. | `#business` |
| **Preferences** | Format preferences, tool choices, things the user wants avoided. | `#preference` |
| **Decisions** | The user picked X over Y, with reasoning if given. | `#decision` |
| **High-signal moments** | Corrections, validated approaches, surprises, "remember this" asks. | `#high-signal` |

**What's explicitly out of scope:** conversational filler, debugging steps already in commit messages, code already in git, and cross-folder user facts that belong in Cowork's auto-memory rather than this PACE root.

#### 6.9.b File Taxonomy — where it goes

- **`/memories/working_memory.md`** — anything the user just told the model that's relevant to the current week. Default landing zone for new captures unless clearly project-scoped.
- **`/memories/long_term/<topic>.md`** — stable, multi-project facts: `people.md`, `vendors.md`, `business.md`, `user.md`, `processes.md`. One file per topic; topics emerge organically as the vault grows.
- **`/projects/<name>/summary.md`** — the canonical "what is this project, where is it, what's next" document. One per project. Maintained by daily compaction.
- **`/projects/<name>/notes/<artifact>.md`** — produced artifacts: drafts, transcripts, research dumps, lists. Free-form structure within the folder.
- **`/memories/archived/`** — never written to directly; only `pace archive` puts things here.

### 6.10 Promotion & Pruning Rules

Hybrid: concrete heuristics surface candidates, the LLM (during compaction/review) makes the final call.

**Promotion (working → long-term), evaluated daily:**
- Entry's `date_created` > 7 days old, AND
- Entry has been referenced (loaded via `pace_load_project` or wikilinked from another file) at least once, OR
- Entry contains identifying info (name, email, account number, recurring date) detected by simple regex, OR
- Entry is tagged `#person`, `#identifier`, `#decision`, or `#business` (these are inherently long-term by content category).

**Archival (long-term → archived), evaluated weekly:**
- Entry's `date_modified` > 90 days old, AND
- Zero references logged in the last 60 days (see §7.1 references table), AND
- LLM judges the entry as no longer relevant given current `working_memory.md`.

**Retention exemptions (never auto-archived):**
- Entries tagged `#high-signal` or `#decision` — these are the moments that taught the AI how to work with the user; losing them would cost what PACE was built to preserve.
- Entries tagged `#user` — facts about the boss are forever-relevant within this root.

Defaults are conservative — better to keep too much than to lose context. All thresholds are configurable in `system/pace_config.yaml`.

---

## 7. Technical Design Decisions

### 7.1 SQLite Schema (FTS5)

```sql
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,           -- working | long_term | project_summary | project_note | archived
  project TEXT,                  -- nullable; project name when applicable
  title TEXT NOT NULL,
  body TEXT NOT NULL,            -- markdown body without frontmatter; canonical for FTS
  aliases TEXT,                  -- JSON array; populated for kind='project_summary'
  date_created TEXT NOT NULL,    -- ISO-8601
  date_modified TEXT NOT NULL,   -- ISO-8601
  tags TEXT                      -- JSON array, also indexed in FTS
);

-- External-content FTS5: index references files.<col> by rowid.
CREATE VIRTUAL TABLE files_fts USING fts5(
  title, body, tags, aliases,
  content='files', content_rowid='id',
  tokenize='porter unicode61'
);

CREATE TABLE refs (
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES files(id),  -- nullable for project_load (no source file)
  target_id INTEGER NOT NULL REFERENCES files(id),
  ref_type TEXT NOT NULL,        -- 'wikilink' | 'project_load'
  occurred_at TEXT NOT NULL      -- ISO-8601
);
CREATE INDEX idx_refs_target_time ON refs(target_id, occurred_at);

CREATE TABLE config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

**Reference counting policy.** `refs` rows are inserted when:
- A `pace_load_project` call resolves to a target file (`ref_type='project_load'`).
- A markdown write contains a `[[Wikilink]]` to another file (`ref_type='wikilink'`, one row per occurrence).

Search hits do **not** create reference rows — they're too noisy and would inflate counts past the point where pruning can do its job.

Reference counts used in pruning rules are computed on demand:
```sql
SELECT COUNT(*) FROM refs WHERE target_id = ? AND occurred_at > date('now','-60 days');
```

WAL mode is enabled at DB open for clean concurrent-read behavior across multiple Cowork windows.

### 7.2 OneDrive "Always Local" Requirement

The PACE root sits inside OneDrive. Two risks:
- SQLite mmap fails when OneDrive virtualizes the DB file.
- Markdown writes during sync can produce `* (Conflicted Copy *).md` files.

**Mitigations:**
- The user configures the PACE root with "Always keep on this device" so files never become virtual. `pace doctor` verifies this attribute on every health check.
- DB and WAL files are gitignored; their absence on other devices is fine — they're rebuilt locally from markdown via `pace reindex`.
- Markdown writes are atomic (write-temp + fsync + rename) to minimize conflict windows.

**Conflicted-copy handling — alert, don't silently resolve.**
A conflicted copy means OneDrive saw two divergent versions of a file. PACE never picks a winner automatically; choosing wrong loses data the user might need.
- `pace doctor` scans for `* (Conflicted Copy *).md` files in the vault.
- `pace_status` (called by the model at session start) surfaces any conflicts in its return value.
- The model's CLAUDE.md instructions say: when `pace_status` reports conflicts, raise the issue to the user as the first thing in the conversation, show the conflicting paths, and ask which version is canonical before doing anything else.
- Resolution is user-initiated: keep one, merge by hand, or invoke `pace archive` on the loser.

### 7.3 Concurrency

- Single user, but multiple Cowork windows may run simultaneously.
- SQLite WAL mode handles concurrent readers + one writer cleanly.
- Markdown file writes use `portalocker` with a short timeout. On contention, `pace_capture` retries up to 3× with backoff before surfacing an error.
- Scheduled tasks acquire an exclusive lock at `/system/.pace.lock` so daily/weekly jobs never overlap.

### 7.4 Git Versioning

- `git init` runs during `pace_init`.
- `.gitignore` excludes `/system/pace_index.db*`, OneDrive markers, and `__pycache__/`.
- All markdown is tracked. The user gets full diff history for free.
- PACE does **not** auto-commit. The model may suggest commits at natural checkpoints, but commits are user-initiated.

### 7.5 Mac Compatibility (Deferred)

All Python code uses `pathlib` and avoids Windows-specific APIs except inside `pace doctor`'s OneDrive check, which is gated behind a platform detect. Mac support is a v1.1 stretch goal — explicitly out of scope for v1.

---

## 8. Success Metrics

PACE is working when:

1. **Cold-start recall** — a session opened the morning after a productive day correctly recalls 3+ specific facts from yesterday without being prompted.
2. **Project switch fidelity** — saying "let's work on X" results in the model loading X's `summary.md` and acknowledging current state in 90%+ of cases, with no slash command use.
3. **Capture coverage** — at the end of a one-week trial, a manual review of the conversation transcripts vs the markdown files shows ≥80% of durable facts were captured automatically.
4. **Knowledge accumulation (the north-star metric)** — at the 30, 60, and 90-day marks, asking the model open-ended questions like "what do you know about my business?" or "how do I prefer to work?" produces progressively richer, more accurate answers. This is how we measure intern → junior → senior.
5. **Maintenance reliability** — daily and weekly scheduled tasks run successfully ≥95% of scheduled days (counted only against days when Cowork was open at least once), with logs to prove it.
6. **Vault hygiene** — Obsidian opens the vault and shows a clean, navigable graph; no orphaned `[[Wikilinks]]` after 30 days of operation.
7. **Zero-friction UX** — the user can describe their PACE workflow as "I just talk to it" without mentioning any command, file, or folder.

---

## 9. Phased Implementation Plan (Summary)

Detailed phases in `PACE Dev Plan.md`. High level:

- **Phase 0 — Skeleton.** Python project, dependencies, lint/test rigging.
- **Phase 1 — CLI core + SQLite FTS5.** `init`, `capture`, `search`, `status`, `reindex`.
- **Phase 2 — Projects.** `project list/create/load/rename`, summary maintenance helpers.
- **Phase 3 — MCP server.** Wraps CLI; tool descriptions tuned for model invocation.
- **Phase 4 — Onboarding.** First-run flow + CLAUDE.md template + `.mcp.json` generator + scheduled-task wiring.
- **Phase 5 — Compaction & review.** `compact` and `review` commands with promotion/pruning logic.
- **Phase 6 — Polish.** `doctor`, logging, error handling, OneDrive guard rails.

---

## Appendix A — First-Run Onboarding Script

The conversation flow when Cowork is opened in an uninitialized PACE folder. The model follows this script as instructed by the bootstrap CLAUDE.md template. Onboarding is a doorway, not a destination — keep it short.

**Trigger:** model calls `pace_status` early in the session and receives `{ "initialized": false }`.

**Beat 1 — Introduce + first capture (one model turn):**
> "Hi — I'm Claude, and this folder is being set up as a PACE root. PACE is a memory system that lets me remember our work between sessions, so I get more useful over time instead of starting from scratch each conversation. Two quick questions before we begin: what should I call you, and what's the rough nature of the work we'll be doing in this folder?"

**Beat 2 — Acknowledge + propose scheduled tasks (after user answers):**
The model:
1. Calls `pace_init` to scaffold structure (folders, DB, `.gitignore`, `.mcp.json`, CLAUDE.md, `git init`).
2. Calls `pace_capture` with the user's name and role — `kind=long_term`, file `long_term/user.md`, tags `#person #user`.
3. Calls `pace_capture` with the work description — `kind=working`, tags `#business #high-signal`.
4. Then says:
> "Saved. I'm setting up two background tasks so I can keep my memory tidy without bothering you: a **daily** compaction that consolidates each day's notes, and a **weekly** review that archives stale items and synthesizes themes. They run inside Cowork while it's open. Sound good?"

**Beat 3 — Register tasks + finish (after user confirms):**
The model:
1. Uses Cowork's `mcp__scheduled-tasks` MCP to register the two tasks with their PACE-provided prompts.
2. Then says:
> "Done. Folder structure created, version control initialized, both tasks scheduled. From here on, just talk to me normally — I'll handle remembering. What would you like to work on?"

**Constraints:**
- Maximum three model turns end-to-end. If the user asks tangential questions, answer briefly and return to the script.
- Never explain MCP, SQLite, or file paths unless the user asks. The user does not need to know how PACE works to use it.
- If the user declines scheduled tasks, register them anyway in a paused state — `pace doctor` will surface this so they're easy to enable later.
- If the user ever asks "what are you saving about me?" — point them at `/memories/long_term/`. Everything is human-readable; nothing is hidden.
