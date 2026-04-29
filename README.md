# PACE — Persistent AI Context Engine

> **Status:** v1 feature-complete (Phase 6 of [PACE Dev Plan.md](PACE%20Dev%20Plan.md)). Pending: dogfood week.

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

## Quickstart

```bash
# 1. Clone or download this repo. The folder you clone into IS the vault.
git clone https://github.com/justingesso/pace.git my-pace-vault
cd my-pace-vault

# 2. Set up a local Python environment.
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"

# 3. Bootstrap the vault.
pace init

# 4. Open this folder in Cowork. The model will follow the three-beat
#    onboarding script in CLAUDE.md, capture your name and the nature of
#    your work, and register two scheduled tasks (daily compaction and
#    weekly review). After that, just talk to it.
```

That's it. From this point you don't type CLI commands — you just have conversations with Claude Cowork in this folder. PACE captures, searches, and switches project context behind the scenes.

## CLI reference (the model uses MCP; humans use these)

| Command | Purpose |
|---|---|
| `pace init` | Scaffold an empty vault. Idempotent. |
| `pace status` | File counts, last task timestamps, health summary. |
| `pace capture --kind <k> [--topic <t>] [--project <p>] [--note <n>] [--tag ...] "<text>"` | Persist content. Kinds: `working`, `long_term`, `project_summary`, `project_note`. |
| `pace search "<query>" [--scope memory\|projects\|all] [--project <p>]` | FTS5 search; ranked snippets. |
| `pace project list` / `create` / `load` / `rename` / `alias add\|remove` | Project lifecycle. |
| `pace compact --plan` / `--apply <file>` | Daily compaction (PRD §6.3). |
| `pace review --plan` / `--apply <file>` | Weekly review (PRD §6.4). |
| `pace archive <path>` | Manually move a markdown file to `memories/archived/`. |
| `pace doctor [--json]` | Run health checks; never auto-fixes. |
| `pace reindex` | Rebuild the FTS5 index from disk. |

## Repository layout

```
src/pace/         # Python package: CLI, MCP server, indexer, etc.
tests/            # pytest suite
pyproject.toml    # entry points: pace = pace.cli:main, pace-mcp = pace.mcp_server:main
PACE PRD.md       # product spec
PACE Dev Plan.md  # phased implementation plan
CLAUDE.md         # vault instructions for Claude (used at session start)
```

Runtime vault directories (`memories/`, `projects/`, `system/`) are created by `pace init` and gitignored, plus `.mcp.json` (which embeds your local Python path). This repo is the **template** — to use PACE for your own work, clone or copy it into a folder of your choice and run `pace init`.

## Troubleshooting

### Cowork doesn't list `pace_*` tools

Check `.mcp.json` exists at the vault root. If not, `pace init` didn't run or didn't complete. The file's `command` field must point at a Python interpreter that has `pace` installed (re-run `pace init` if you moved the venv).

### "OneDrive has marked vault files as online-only"

`pace doctor` flagged `onedrive-virtualized`. SQLite mmap fails silently against virtualized files (PRD §7.2). Right-click the vault folder in File Explorer and choose **Always keep on this device**.

### "OneDrive produced N conflicted-copy files"

`pace doctor` flagged `conflicted-copies`. Two devices wrote divergent versions of the same file. PACE never picks a winner — open both, merge by hand, then `pace archive <path-to-loser>` to preserve the discarded version.

### "Daily compaction has never run" / "hasn't run in Nd Nh"

The scheduled task isn't firing. Check Cowork's scheduled-task UI to confirm the task is registered and not paused. The task only fires while Cowork is open on this machine — if you don't open Cowork on a given day, that day's compact is skipped (and the next run picks up the backlog).

### "N file(s) modified on disk after last index"

`pace doctor` flagged `index-drift`. You edited markdown directly (typically in Obsidian) without telling PACE. Run `pace reindex`.

### "PaceLockBusy: another PACE maintenance task already holds the lock"

Two compact or review runs collided. The first one will finish in seconds; retry. If it's stuck, delete `system/.pace.lock` (only when no PACE process is running).

### Tests fail with `ModuleNotFoundError: pace`

You're running pytest outside the venv. Activate it (`.venv\Scripts\activate`) and re-run.

## Platform support

- **Windows 11** with Cowork — primary target.
- **macOS** — v1.1 stretch goal. Most code uses `pathlib`; only `pace doctor`'s OneDrive check is Windows-specific.
- **OneDrive** — supported, but the PACE root must be configured "Always keep on this device." `pace doctor` verifies this.

## License

MIT. See [LICENSE](LICENSE).
