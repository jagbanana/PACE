# PACE — Persistent AI Context Engine

> **A local, human-readable memory system that gives Claude persistence across sessions.**
> Markdown files. SQLite FTS5. An MCP server. No cloud, no vector DB, no API keys.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)](#status)

---

## What PACE is

Out of the box, every conversation with Claude starts from a blank slate. PACE fixes that for **knowledge work** — research, marketing, planning, strategy, anything multi-week — by giving the assistant a persistent, human-readable memory that lives next to your project, not in a cloud database.

You **never type a slash command.** You just talk to Claude. Behind the scenes:

- When you state a fact, decision, preference, or person worth remembering, the assistant captures it silently.
- When you mention a project — by name, alias, or even a topical phrase like *"the Q3 launch"* — the assistant pulls that project's summary into context before answering.
- A daily compaction and a weekly review run as background tasks to keep the vault tidy. They consolidate, promote, archive, and synthesize so memory stays useful instead of bloated.

The result is an assistant that grows from feeling like a brilliant intern to a long-tenured employee you can groom and trust. Day by day it knows more about you, your business, and your projects.

### What it's *not*

- **Not a coding assistant memory tool.** Code lives in git; PACE captures the soft context around it (decisions, preferences, identifiers, relationships).
- **Not a cloud service.** Everything is local files. No credentials, no syncing through Anthropic's servers, no telemetry.
- **Not a vector DB.** PACE uses SQLite FTS5 for keyword + ranked search. It's fast, debuggable, and zero-config; if you want semantic recall, layer it on top — the vault is just Markdown.

### Status

v0.1.2 — beta. The Cowork plugin and Claude Code CLI workflow are both stable; 160+ tests cover capture, search, compaction, review, and the MCP surface. Used daily by the maintainer. Mac dogfood pending; Windows + OneDrive is the primary target.

---

## Architecture at a glance

PACE has four moving parts that all read from and write to a folder of Markdown files (the "vault"):

```
                     ┌────────────────────────────────────────┐
                     │              YOUR VAULT                │
                     │     (Markdown + SQLite + YAML)         │
                     │                                        │
                     │   memories/   projects/   system/      │
                     └──▲──────────────▲──────────────▲───────┘
                        │              │              │
                  reads / writes  reads / writes  reads / writes
                        │              │              │
        ┌───────────────┴──┐    ┌──────┴────────┐ ┌──┴────────────────┐
        │   MCP server     │    │      CLI      │ │  Scheduled tasks  │
        │  (pace_mcp)      │    │     (pace)    │ │ (daily / weekly)  │
        │                  │    │               │ │                   │
        │  pace_status     │    │ pace init     │ │ compact prompt    │
        │  pace_capture    │    │ pace status   │ │ review prompt     │
        │  pace_search     │    │ pace capture  │ │                   │
        │  pace_load_proj. │    │ pace search   │ │ run inside Cowork │
        │  pace_create_*   │    │ pace doctor   │ │ no API calls      │
        │  pace_init       │    │ pace reindex  │ │                   │
        │  pace_list_proj. │    │ pace archive  │ │                   │
        └────────▲─────────┘    │ pace compact  │ └─────────▲─────────┘
                 │              │ pace review   │           │
                 │              └───────────────┘           │
            invoked by                                  invoked by
            the model                                  Cowork's
            (Claude in Cowork                          scheduled-task
             or Claude Code)                           system
```

The MCP server and the CLI are thin wrappers over the same Python functions — there's a single source of truth for every read and every write.

### The vault on disk

Everything PACE knows about you lives in a folder you can open in Obsidian, VS Code, or any text editor:

```
your-vault/
├── memories/
│   ├── working/
│   │   └── 2026-04-29.md          ← today's landing zone for new captures
│   ├── long_term/
│   │   ├── user.md                ← who you are, your preferences
│   │   ├── business.md            ← context about your work
│   │   └── <topic>.md             ← arbitrary topical files
│   └── archived/                  ← weekly review moves stale entries here
│
├── projects/
│   ├── q3-launch/
│   │   ├── summary.md             ← always loaded when project is active
│   │   └── notes/
│   │       └── 2026-04-29-meeting-with-marketing.md
│   └── website-redesign/
│       └── summary.md
│
├── system/
│   ├── pace_index.db              ← SQLite FTS5 index (rebuildable)
│   ├── pace_config.yaml           ← tunables (budgets, retention, etc.)
│   ├── prompts/
│   │   ├── compact.md             ← daily-task prompt (read by Cowork)
│   │   └── review.md              ← weekly-task prompt
│   └── logs/                      ← maintenance run logs
│
├── .mcp.json                      ← Claude Code stdio server registration
├── .gitignore                     ← so the vault can be a git repo if you want
└── CLAUDE.md                      ← session-start instructions for the model
```

Every file is plain Markdown with **YAML frontmatter** describing kind, tags, source, and timestamps. Every entry uses **`[[Wikilinks]]`** for cross-references and **`#tags`** for retrieval. The vault is browsable, editable, and grep-able by hand. SQLite is purely an index over what's already in Markdown — delete it and `pace reindex` rebuilds from disk.

### How a session flows

The contract between the model and PACE is small and front-loaded. At session start the model calls `pace_status`; everything else is reactive.

```
   ┌─────────────────────┐
   │ User opens Cowork   │
   │ in any folder       │
   └─────────┬───────────┘
             │
             ▼
   ┌─────────────────────┐      not initialized      ┌──────────────────┐
   │ Skill: call         │ ────────────────────────▶ │ 3-question       │
   │ pace_status FIRST   │                           │ onboarding flow  │
   └─────────┬───────────┘                           └──────────────────┘
             │ initialized
             ▼
   ┌─────────────────────────────────────────────────┐
   │ Response carries working_memory  +  warnings    │
   │ (today's notes, identity pin, OneDrive issues)  │
   └─────────┬───────────────────────────────────────┘
             │
             ▼
   ┌─────────────────────┐
   │ User talks. Model   │
   │ responds, grounded  │
   │ in working_memory.  │
   └─────────┬───────────┘
             │
             ├─ user states a durable fact ──────────▶  pace_capture (silent)
             │
             ├─ user mentions a project / topic ─────▶  pace_search → pace_load_project
             │
             └─ user asks "what do you know about X" ▶  pace_search
```

The user sees an assistant that remembers; they don't see the tool calls. The model is instructed to never expose plumbing.

---

## How memory and context are managed

This is the heart of PACE. The design is built around two unavoidable facts:

1. **Context windows are finite.** Loading the entire vault every session would burn tokens and degrade attention.
2. **Most facts decay in importance.** A meeting note from yesterday matters; the same note from 90 days ago, untouched, probably doesn't.

So PACE separates memory into tiers, only loads the smallest one at session start, and runs scheduled jobs to move information through the tiers as it ages.

### The four tiers

| Tier | Loaded when? | What lives here | How it gets here |
|---|---|---|---|
| **Working** (`memories/working/`) | **Always**, via `pace_status` at session start | Today's captures, ephemeral notes, anything not yet promoted | Every `pace_capture` defaults here |
| **Long-term** (`memories/long_term/`) | On demand, via `pace_search` | Stable facts about people, identifiers, decisions, preferences, business context | Daily compaction promotes from working; identity-pin captures land here directly |
| **Project** (`projects/<name>/`) | On demand, via `pace_load_project` | A project's `summary.md` plus topical notes; loaded as a unit when the user mentions the project | Created by `pace_create_project`; populated by captures with `kind=project_summary` or `project_note` |
| **Archived** (`memories/archived/`) | Never (search-only) | Long-term entries that aged out without being referenced | Weekly review moves stale entries here; nothing is ever deleted |

### What gets captured (and what doesn't)

The model is instructed to capture **only durable context** worth having next session:

✅ **Capture** — names, roles, identifiers (account numbers, ticker symbols, slugs), key dates, decisions ("we picked option B because…"), validated approaches, corrections to earlier mistakes, business facts, anything tagged `#high-signal` or `#decision`.

❌ **Skip** — debugging chatter, filler, code already in git, generic how-to answers, anything cross-folder that belongs in Cowork's own auto-memory rather than this PACE root.

The standard tag set is small: `#person`, `#identifier`, `#date`, `#user`, `#business`, `#preference`, `#decision`, `#high-signal`. Tags drive both retrieval *and* retention — three of them are exempt from auto-archival (see below).

### Capture flow

```
   user says something durable
            │
            ▼
   ┌─────────────────────────────────────────────────┐
   │ Model decides: kind, topic/project, tags        │
   │ Calls pace_capture(...)                         │
   └─────────────┬───────────────────────────────────┘
                 │
                 ▼
   ┌─────────────────────────────────────────────────┐
   │ pace.capture                                    │
   │   1. Append to the right Markdown file          │
   │      - working: memories/working/<date>.md      │
   │      - long_term: memories/long_term/<topic>.md │
   │      - project_*: projects/<name>/...           │
   │   2. Atomic write (survives OneDrive sync)      │
   │   3. Update SQLite FTS5 index + refs table      │
   │   4. Update wikilink graph                      │
   └─────────────────────────────────────────────────┘
```

Every write is atomic (`pace.io.atomic_write_text`) so a crashed sync engine or an antivirus scanner can't leave the vault half-written.

### Daily compaction — keeping working memory bounded

If working memory grew unbounded, `pace_status` would balloon and every session would carry yesterday's noise. So at 5:00 local time each day, Cowork's scheduled-task system runs the daily compaction prompt (which lives in `system/prompts/compact.md`):

```
   ┌──────────────────────────────────────────────────────┐
   │ pace compact --plan                                  │
   │   reads yesterday's working file + recent activity   │
   │   emits a JSON plan: promote, refresh, archive       │
   └─────────────────┬────────────────────────────────────┘
                     │  (Claude in Cowork reviews / refines)
                     ▼
   ┌──────────────────────────────────────────────────────┐
   │ pace compact --apply <plan.json>                     │
   │   1. Promote working entries to memories/long_term/  │
   │      based on age + reference count + tags           │
   │   2. Refresh project summaries that saw activity     │
   │   3. Force-promote oldest non-exempt entries until   │
   │      working memory fits within the soft budget      │
   └──────────────────────────────────────────────────────┘
```

**Promotion rules** are conservative — an entry is promoted to long-term when:

- it's at least N days old (configurable; default 1) **and** has been referenced from another file, **OR**
- it carries a long-term tag (`#person`, `#identifier`, `#decision`, `#high-signal`), **OR**
- it would otherwise overflow the working-memory budget (force-promotion fallback).

Force-promotion has one exception: entries tagged `#user`, `#high-signal`, or `#decision` are **never** force-evicted. This is what lets PACE keep a pinned identity entry (your name, the assistant's nickname and emoji) at the top of working memory forever.

### Working-memory size budget

Working memory is loaded in full on every `pace_status` call, so its size matters. PACE enforces a two-stage budget measured in characters (defaults in `system/pace_config.yaml`):

```
                          ┌─────────────────────────┐
   working memory size →  │  16 000 chars (soft)    │  ≈ 4K tokens
                          │  ─────────────────────  │
                          │  daily compaction       │  force-promotes
                          │  triggers force-promote │  oldest non-exempt
                          │  to bring back below    │  entries to
                          │  soft cap               │  long_term/working-
                          │                         │  overflow.md
                          ├─────────────────────────┤
                          │  32 000 chars (hard)    │  ≈ 8K tokens
                          │  ─────────────────────  │
                          │  pace_status truncates  │  appends a notice;
                          │  on the fly so the      │  older entries
                          │  model never sees an    │  remain on disk
                          │  oversize payload       │  and searchable
                          └─────────────────────────┘
```

This means **the model's session-start payload is bounded** even if compaction hasn't run for a few days. Truncation is non-destructive — older entries stay on disk and surface via `pace_search`.

### Weekly review — archiving the genuinely stale

Sundays at 6:00 local time, the weekly review prompt runs. It looks at every long-term entry and asks two questions:

1. **Is it old?** Older than 90 days (configurable).
2. **Is it cold?** No references in the last N days, no recent edits.

If both are yes **and** the entry doesn't carry a retention-exempt tag (`#user`, `#high-signal`, `#decision`), the review proposes moving it to `memories/archived/`. The maintainer (Claude, in this case) reviews the proposal before applying. Nothing is ever deleted; archived files remain searchable.

Review also writes a short synthesis note for the week — themes that emerged across captures, decisions made, anything worth surfacing.

### Project context switching

When you say *"let's work on the redesign"* — or anything topical that hints at a known project — the model:

1. Calls `pace_search` with your phrase to surface candidate projects.
2. Calls `pace_load_project` with the resolved name. That:
   - Pulls `projects/<name>/summary.md` into context.
   - Records a `project_load` reference, so weekly pruning knows the project is active.
3. Then answers your actual request, grounded in the loaded summary.

If `pace_load_project` returns an error (typo, ambiguous reference), the model calls `pace_list_projects` and asks you which one. It never invents a project that doesn't exist.

### Vault location resolution

The MCP server figures out which vault to talk to via this chain (first hit wins):

```
   1. PACE_ROOT env var                                   ← debugging
   2. CLAUDE_PLUGIN_OPTION_VAULT_ROOT env var             ← Cowork plugin config
   3. Per-user config file:
        Windows:   %APPDATA%\pace\config.json
        macOS/Lx:  ~/.config/pace/config.json
   4. Walk up from cwd looking for system/pace_index.db   ← Claude Code workflow
   5. None of the above → pace_status returns
        initialized: false → onboarding picks a path
```

This is why a single Cowork install can serve every project: the vault location is set once, in step 2 or 3, and survives restarts.

---

## Install

There are two install paths depending on which Claude client you're using.

### Option A — Claude Cowork (recommended)

This is the supported path for almost everyone. Cowork doesn't load project-scoped `.mcp.json` files, so a plugin is the only way to wire MCP into Cowork.

**Prerequisites**

- [Claude Cowork](https://claude.com) installed and running.
- [`uv`](https://docs.astral.sh/uv/) on your `PATH`. The plugin uses `uvx` to run the bundled PACE source in an isolated environment, so you don't manage Python yourself.
  - Windows (PowerShell): `irm https://astral.sh/uv/install.ps1 | iex`
  - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- After installing `uv`, **fully quit and relaunch Cowork** (kill tray processes too) so the new `PATH` propagates.

**Steps**

1. Download `pace-memory.plugin` from the [releases page](https://github.com/jagbanana/PACE/releases) — or build it yourself (see [Building from source](#building-from-source) below).
2. **Heads up:** Cowork and Claude Code share the desktop app but use *separate* plugin stores. A plugin installed via *Settings → Customize* lands in **Claude Code's** store and won't appear in Cowork. Cowork has its own marketplace folder under your active session directory.
3. Extract `pace-memory.plugin` into Cowork's local-uploads marketplace. PowerShell's built-in `tar` works on `.plugin` directly without renaming:
   ```powershell
   $dest = "$env:APPDATA\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\marketplaces\local-desktop-app-uploads\pace-memory"
   New-Item -ItemType Directory -Path $dest -Force | Out-Null
   tar -xf "C:\path\to\pace-memory.plugin" -C $dest
   ```
   *Other extractors that work: 7-Zip, Git Bash's `unzip`, or Windows' built-in **Extract All** after renaming `.plugin` to `.zip`. Don't use Python's `zipfile.extractall` — it doesn't opt into Windows long paths and Cowork's session-UUID nesting will trip MAX_PATH.*
4. Register the plugin in that marketplace's `marketplace.json` by adding a `pace-memory` entry to the `plugins` array. Full example in [`plugin/README.md`](plugin/README.md#step-5--register-the-plugin-in-the-marketplace-manifest).
5. Restart Cowork, open its plugin/customize panel, find `pace-memory`, and enable it. Cowork prompts for the optional `vaultRoot` field — leave blank to let onboarding pick a path.
6. Open Cowork in any folder and start a conversation. The bundled skill detects an uninitialized vault and runs a short three-question onboarding (your name, an optional assistant nickname + emoji, and the rough nature of your work). After that, just talk.

Full plugin docs (including the long-path / extraction gotcha and how to verify the install landed in the right store): [`plugin/README.md`](plugin/README.md).

### Option B — Claude Code (CLI workflow)

For Claude Code users, the `.mcp.json` mechanism *does* work, so the simpler "vault is a project folder" workflow is supported:

```bash
git clone https://github.com/jagbanana/PACE.git my-pace-vault
cd my-pace-vault
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pace init                       # scaffolds the vault, writes .mcp.json
```

Open `my-pace-vault` in Claude Code. The generated `.mcp.json` registers the local stdio server and the in-vault `CLAUDE.md` tells the model how to behave. From there the experience matches the plugin path.

---

## CLI reference

The model uses MCP tools; humans use the CLI. They share the same underlying functions.

| Command | Purpose |
|---|---|
| `pace init [<path>]` | Scaffold an empty vault. Idempotent. Records the path in the per-user config. |
| `pace status` | File counts, last-task timestamps, health summary. |
| `pace capture --kind <k> [--topic <t>] [--project <p>] [--note <n>] [--tag ...] "<text>"` | Persist content. Kinds: `working`, `long_term`, `project_summary`, `project_note`. |
| `pace search "<query>" [--scope memory\|projects\|all] [--project <p>]` | FTS5 search; ranked snippets. |
| `pace project list` / `create` / `load` / `rename` / `alias add\|remove` | Project lifecycle. |
| `pace compact --plan` / `--apply <file>` | Daily compaction. |
| `pace review --plan` / `--apply <file>` | Weekly review. |
| `pace archive <path>` | Move a Markdown file to `memories/archived/`. |
| `pace doctor [--json]` | Health checks; never auto-fixes. |
| `pace reindex` | Rebuild the FTS5 index from disk. |

---

## Building from source

```bash
git clone https://github.com/jagbanana/PACE.git
cd PACE
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/build_plugin.py
# → dist/pace-memory.plugin
```

The build script writes a single file: `dist/pace-memory.plugin`. **That file *is* the plugin zip** — same archive format as `.zip`, just named with the `.plugin` extension Anthropic's plugin spec uses. There's no separate `.zip` artifact.

What the script does:

1. **Stages** the runtime Python source into a temp directory — `src/pace/`, `pyproject.toml`, `LICENSE`, plus a minimal in-zip `README.md`. The temp dir lives outside the source tree (and outside OneDrive) so file locking can't fight us.
2. **Sanity-checks** that `plugin/.claude-plugin/plugin.json`'s `version` matches `pace.__version__` so a forgotten bump fails loudly.
3. **Zips** `plugin/` plus the staged source (under the `server/` arc-name prefix) into `dist/pace-memory.plugin`.

At runtime, the plugin's `.mcp.json` runs `uvx --from ${CLAUDE_PLUGIN_ROOT}/server pace-mcp`, which resolves the bundled source and runs the MCP server. No PyPI publish required.

If you need a `.zip`-extension copy for a tool that doesn't recognize `.plugin`, just copy the file: `cp dist/pace-memory.plugin dist/pace-memory.zip`.

### Running tests

```bash
pytest                # full suite
pytest -k compact     # subset
ruff check            # lint
ruff format           # auto-format
```

There are 160+ tests covering capture, search, compaction, review, doctor, the MCP surface, plugin packaging, and onboarding artifacts.

---

## Repository layout

```
src/pace/         # Python package: CLI, MCP server, indexer, etc.
tests/            # pytest suite
plugin/           # Cowork plugin source — bundled into pace-memory.plugin
  ├── .claude-plugin/plugin.json
  ├── .mcp.json
  ├── skills/pace-memory/    # SKILL.md the model loads at session start
  └── system-prompts/        # compact.md, review.md (scheduled-task prompts)
scripts/          # build_plugin.py
pyproject.toml    # entry points: pace = pace.cli:main; pace-mcp = pace.mcp_server:main
LICENSE
README.md
```

The runtime vault directories (`memories/`, `projects/`, `system/`) are created by `pace init` and gitignored. This source repo can double as a runnable vault — clone it, run `pace init`, and you're set.

---

## Troubleshooting

### Cowork doesn't list `pace_*` tools after installing the plugin

Most common cause: the plugin landed in **Claude Code's** plugin store rather than Cowork's marketplace. Both UIs live inside the same desktop app and look similar, but they're separate stores. Check `%APPDATA%\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\installed_plugins.json` — if `"plugins"` is `{}`, Cowork has zero plugins enabled and the install went to the wrong place. Walk through Option A above to put it in Cowork's marketplace.

If `installed_plugins.json` *does* show `pace-memory` and the tools still don't appear, then `uv` is the issue: confirm `uv --version` works in PowerShell, then fully quit Cowork (including tray processes via Task Manager) and relaunch.

### Extraction failed with `FileNotFoundError` or "Path too long"

Windows MAX_PATH (260-char) limit. Cowork's session directory contains two UUIDs that already eat ~80 characters; combined with the plugin's internal `skills\pace-memory\references\onboarding.md` nesting, some files blow past the limit. Use Windows' built-in *Extract All*, Git Bash's `unzip`, 7-Zip, or `tar -xf` from PowerShell — they all opt into long-path mode. Python's `zipfile.extractall` does *not*.

### Claude Code doesn't list `pace_*` tools

Check that `.mcp.json` exists at the vault root. If not, `pace init` didn't run or didn't complete. The file's `command` field must point at a Python interpreter that has `pace` installed (re-run `pace init` if you moved the venv).

### "OneDrive has marked vault files as online-only"

`pace doctor` flagged `onedrive-virtualized`. SQLite mmap fails silently against virtualized files. Right-click the vault folder in File Explorer and choose **Always keep on this device**.

### "OneDrive produced N conflicted-copy files"

`pace doctor` flagged `conflicted-copies`. Two devices wrote divergent versions of the same file. PACE never picks a winner — open both, merge by hand, then `pace archive <path-to-loser>` to preserve the discarded version.

### "Daily compaction has never run" / "hasn't run in Nd Nh"

The scheduled task isn't firing. Check Cowork's scheduled-task UI to confirm the task is registered and not paused. The task only fires while Cowork is open on this machine — if you don't open Cowork on a given day, that day's compaction is skipped. PACE catches up on the next run.

### "N file(s) modified on disk after last index"

`pace doctor` flagged `index-drift`. You edited Markdown directly (typically in Obsidian) without telling PACE. Run `pace reindex`.

### "PaceLockBusy: another PACE maintenance task already holds the lock"

Two compact or review runs collided. The first one will finish in seconds; retry. If it's stuck, delete `system/.pace.lock` (only when no PACE process is running).

### Tests fail with `ModuleNotFoundError: pace`

You're running pytest outside the venv. Activate it (`.venv\Scripts\activate`) and re-run.

---

## Platform support

- **Windows 11** with Cowork — primary target.
- **macOS** — should work; the only Windows-specific code path is `pace doctor`'s OneDrive virtualization check, which is gated by `sys.platform`. Mac dogfood pending.
- **OneDrive** — supported, but the PACE root must be configured "Always keep on this device." `pace doctor` verifies this.

## Design tenets

- **Local-first.** Markdown files + Python CLI + SQLite FTS5 + an MCP server. No vector DBs, no cloud services, no API keys.
- **Human-readable.** Everything PACE writes is browsable in [Obsidian](https://obsidian.md): `[[Wikilinks]]`, `#tags`, YAML frontmatter.
- **Seamless.** The user never types a command or remembers a syntax. The model decides when to capture, search, or load project context.
- **Self-maintaining.** Daily compaction and weekly review run as Cowork scheduled tasks. PACE never hits the Anthropic API directly — Claude itself does the LLM work, in-session.
- **Conservative by default.** Nothing is ever deleted; archive is a one-way move you can grep. Force-promotion exempts identity / decision tags so personality and high-signal context survive forever.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports, design feedback, and Mac dogfooding are especially welcome.

## License

MIT. See [LICENSE](LICENSE).
