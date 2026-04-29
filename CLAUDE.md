# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is the **PACE source repository** — the canonical, GitHub-publishable codebase for PACE (Persistent AI Context Engine). The folder doubles as a usable PACE vault: `pace init` scaffolds runtime directories (`memories/`, `projects/`, `system/`) alongside the source.

Two ways the repo is used:
1. **As the published source** — what eventually lives on GitHub. Vault directories and DB are gitignored so user content never ships.
2. **As an active vault** — the maintainer keeps a *separate copy* of this folder for their own "AI intern" instance. That copy accumulates real notes; this repo does not.

When working in this repo, always treat it as **the source/template version**. Never commit real user content into `memories/` or `projects/`.

## What PACE Is

PACE is a local Markdown-based memory system that runs alongside Claude Cowork. The vision: take an LLM that's a brilliant intern (book-smart, no context about you) and grow it into a long-tenured employee that knows your business, your people, and your preferences. Day by day, week by week, captured facts and project context compound. See [PACE PRD.md](PACE%20PRD.md) for the full spec.

The system is **deliberately simple and local**: Markdown + Python CLI + SQLite FTS5 + MCP server. No vector DBs, no cloud services, no API keys. Compaction and review run inside Cowork's scheduled-task runtime, never via direct API calls.

## Architecture (per PRD v2.0)

### Source layout (this repo)
- `src/pace/` — Python package: CLI, MCP server, index, capture, projects, compact, review, onboarding, doctor.
- `src/pace/prompts/` — version-controlled scheduled-task prompts (`compact.md`, `review.md`).
- `src/pace/templates/` — files emitted into a user's vault by `pace init` (e.g. CLAUDE.md template).
- `tests/` — pytest suite.
- `pyproject.toml` — entry point `pace = "pace.cli:main"`.

### Runtime vault layout (created by `pace init`, gitignored here)
- `memories/working_memory.md`, `memories/long_term/`, `memories/archived/` — tiered memory.
- `projects/<Name>/summary.md` and `projects/<Name>/notes/` — per-project context.
- `system/pace_index.db` — SQLite FTS5 index.
- `system/logs/` — scheduled-task run logs.

### Integration model
The model invokes PACE through the **MCP server**, never via slash commands. A thin **CLAUDE.md template** dropped into the user's vault tells the model when to call which tool. Onboarding follows the three-beat conversation in PRD Appendix A.

### Lifecycle
1. **First-run onboarding** — empty folder + `pace_init` → fully bootstrapped vault after one conversation.
2. **In-session capture** — model captures the categories defined in PRD §6.9 (people, dates, decisions, preferences, high-signal moments, etc.).
3. **Daily compaction** (scheduled task) — consolidates `working_memory.md`, promotes stable facts, refreshes project summaries.
4. **Weekly deep review** (scheduled task) — archives stale entries, validates wikilinks, generates weekly synthesis.

## Conventions to Enforce

- All emitted markdown is Obsidian-compatible: `[[Wikilinks]]`, `#tags`, YAML frontmatter per PRD §6.5.
- All file writes are atomic (write-temp + fsync + rename) to survive OneDrive sync.
- All paths use `pathlib`. Mac support is v1.1 — don't preclude it with Windows-only APIs except inside `pace doctor`.
- The CLI is the only writer to the vault. The MCP server delegates to the same Python functions.
- Tag-driven retention: `#high-signal`, `#decision`, `#user` entries are exempt from automatic archival.
- Reference counts (used in pruning) come from the `refs` table — `project_load` and emitted wikilinks count; search hits do not.
- Scheduled tasks execute inside Cowork's runtime only. PACE never calls the Anthropic API directly and never holds an API key.

## Current Status

**Phase 0 (project skeleton) in progress.** See [PACE Dev Plan.md](PACE%20Dev%20Plan.md) for the full phase breakdown and acceptance criteria.

## Platform Notes

Target: Windows 11 with Cowork. Mac is v1.1. OneDrive caveat: the PACE root must be set to "Always keep on this device" — `pace doctor` verifies this attribute on Windows. Conflicted-copy files (`* (Conflicted Copy *).md`) are detected by `pace doctor`, surfaced via `pace_status`, and resolved by the user — never auto-resolved.
