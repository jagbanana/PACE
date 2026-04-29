# PACE — Persistent AI Context Engine

> **Status:** Pre-alpha. Phase 0 of [PACE Dev Plan.md](PACE%20Dev%20Plan.md). Not yet usable end-to-end.

PACE is a local, Markdown-based memory system that runs alongside [Claude Cowork](https://claude.com) to give the assistant persistence across sessions. Instead of starting from a blank slate every conversation, PACE captures the facts, names, dates, preferences, decisions, and high-signal moments that surface during real work — and surfaces them again next time. Day by day and week by week, the AI's working knowledge of you and your business compounds, until it stops feeling like a brilliant intern and starts feeling like a long-tenured employee you can groom and trust.

PACE is for **knowledge work, not just coding**: research, marketing, planning, strategy, anything multi-week.

The user interacts in **natural language only**. There are no slash commands. Capture, search, project switching, and maintenance happen invisibly through an MCP server the model invokes on its own.

## Design tenets

- **Local-first.** Markdown files + Python CLI + SQLite FTS5 + an MCP server. No vector DBs, no cloud services, no API keys.
- **Human-readable.** Everything PACE writes is browsable in [Obsidian](https://obsidian.md): `[[Wikilinks]]`, `#tags`, YAML frontmatter.
- **Seamless.** The user never types a command or remembers a syntax. The model decides when to capture, search, or load project context.
- **Self-maintaining.** Daily compaction and weekly review run as Cowork scheduled tasks; PACE never hits the Anthropic API directly.

## Documents

- [PACE PRD.md](PACE%20PRD.md) — full product requirements (V2.0).
- [PACE Dev Plan.md](PACE%20Dev%20Plan.md) — phased build plan with acceptance criteria.
- [CLAUDE.md](CLAUDE.md) — guidance for Claude Code when working in this repo.

## Repository layout

```
src/pace/         # Python package (CLI, MCP server, indexer, etc.)
src/pace/prompts/ # Scheduled-task prompts (compact.md, review.md)
tests/            # pytest suite
pyproject.toml    # package config; entry point: pace = pace.cli:main
```

Runtime vault directories — `memories/`, `projects/`, `system/` — are created by `pace init` and are gitignored. This repo is the **source/template**. To use PACE for your own work, clone (or copy) the repo into a folder of your choice and run `pace init` there.

## Quickstart (for developers — full UX comes in Phase 4)

```bash
# Clone the repo (this folder becomes your vault, or copy it elsewhere first)
git clone https://github.com/justingesso/pace.git
cd pace

# Set up a local environment
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# Phase 0: confirm it works
pace --version
pytest
ruff check
```

Once Phase 4 lands, the end-user flow becomes "open Cowork in this folder, have a short conversation, and PACE bootstraps itself."

## Platform support

- **Windows 11** with Cowork — primary target.
- **Mac** — v1.1 stretch goal.
- **OneDrive** — supported, but the PACE root folder must be configured "Always keep on this device." `pace doctor` will verify this.

## License

MIT. See [LICENSE](LICENSE).
