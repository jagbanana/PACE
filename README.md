# PACE — Persistent AI Context Engine

> **Status:** v0.1.0. Cowork plugin shipping; CLI/Claude-Code workflow stable.

PACE is a local, Markdown-based memory system that runs alongside [Claude Cowork](https://claude.com) (and [Claude Code](https://claude.com/code)) to give the assistant persistence across sessions. Instead of starting from a blank slate every conversation, PACE captures the facts, names, dates, preferences, decisions, and high-signal moments that surface during real work — and surfaces them again next time. Day by day and week by week, the AI's working knowledge of you and your business compounds, until it stops feeling like a brilliant intern and starts feeling like a long-tenured employee you can groom and trust.

PACE is for **knowledge work, not just coding**: research, marketing, planning, strategy, anything multi-week.

The user interacts in **natural language only**. No slash commands. Capture, search, project switching, and maintenance happen invisibly through an MCP server the model invokes on its own.

## Install

There are two installation paths depending on which client you're using:

### Claude Cowork → install the plugin

This is the supported path for almost everyone. Cowork doesn't load project-scoped `.mcp.json` files, so the only way to wire MCP into Cowork is via a plugin.

The plugin **bundles the PACE Python source inside its zip**. Nothing is fetched from PyPI to make the plugin work — `uvx` just runs the bundled source. The only thing fetched at install time is the small set of runtime dependencies (`click`, `mcp`, `pyyaml`, `portalocker`, `python-dateutil`), and `uv` caches them.

1. Install [`uv`](https://docs.astral.sh/uv/) — the plugin uses `uvx` to launch the bundled PACE source in an isolated environment, so you don't manage Python yourself. Restart Cowork after installing `uv` so the new `PATH` propagates.
2. Download `pace-memory.plugin` from the [releases page](https://github.com/justingesso/pace/releases) (or build it from source — see [Building the plugin](#building-the-plugin) below).
3. In Cowork, open the **Plugins** UI and install `pace-memory.plugin` (drag onto the window or use *Install from file*).
4. Cowork prompts for plugin config. The only field is `vaultRoot` — leave it blank and onboarding will pick a path on first use, or fill in an absolute path now.
5. Open Cowork in any folder and start a conversation. The bundled skill detects an uninitialized vault and runs a short three-question onboarding (your name, optional assistant nickname, where to put the vault and what kind of work you're doing). After that, just talk.

Full plugin docs: [`plugin/README.md`](plugin/README.md).

### Claude Code → install the package and use the CLI

For Claude Code users, the `.mcp.json` mechanism *does* work, so the legacy "vault is a project" workflow is supported:

```bash
git clone https://github.com/justingesso/pace.git my-pace-vault
cd my-pace-vault
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pace init                       # scaffolds the vault here, writes .mcp.json
```

Open `my-pace-vault` in Claude Code. The generated `.mcp.json` registers the local stdio server and the in-vault `CLAUDE.md` tells the model how to behave. From there the experience matches the plugin path.

## Design tenets

- **Local-first.** Markdown files + Python CLI + SQLite FTS5 + an MCP server. No vector DBs, no cloud services, no API keys.
- **Human-readable.** Everything PACE writes is browsable in [Obsidian](https://obsidian.md): `[[Wikilinks]]`, `#tags`, YAML frontmatter.
- **Seamless.** The user never types a command or remembers a syntax. The model decides when to capture, search, or load project context.
- **Self-maintaining.** Daily compaction and weekly review run as Cowork scheduled tasks; PACE never hits the Anthropic API directly.

## Documents

- [PACE PRD.md](PACE%20PRD.md) — full product requirements (V2.0).
- [PACE Dev Plan.md](PACE%20Dev%20Plan.md) — phased build plan with acceptance criteria.
- [CLAUDE.md](CLAUDE.md) — guidance for Claude Code when working in this repo (covers both vault-author and source-dev concerns).
- [plugin/README.md](plugin/README.md) — Cowork-specific install, setup, and usage.

## Building the plugin

```bash
# From the source repo with the venv active:
python scripts/build_plugin.py
# → dist/pace-memory.plugin
```

The build script:
1. **Stages** the runtime Python source into `plugin/server/` — `src/pace/`, `pyproject.toml`, `LICENSE`, plus a minimal in-zip `README.md`. `plugin/server/` is gitignored; it's a build artifact, regenerated on every build.
2. **Sanity-checks** that `plugin/.claude-plugin/plugin.json`'s `version` matches `pace.__version__` so a forgotten bump fails loudly.
3. **Zips** `plugin/` (now including `server/`) into `dist/pace-memory.plugin`.

At runtime, the plugin's `.mcp.json` runs `uvx --from ${CLAUDE_PLUGIN_ROOT}/server pace-mcp`, which resolves the bundled source and runs the MCP server. No PyPI publish required.

## Vault location resolution

The MCP server (whether spawned by the plugin or by Claude Code's `.mcp.json`) resolves the vault path via this chain:

1. **`PACE_ROOT` env var** — debugging / explicit override.
2. **`CLAUDE_PLUGIN_OPTION_VAULT_ROOT`** — set by Cowork when the plugin's `userConfig` is filled at install time.
3. **Per-user config file** written by `pace_init`:
   - Windows: `%APPDATA%\pace\config.json`
   - macOS / Linux: `~/.config/pace/config.json` (or `$XDG_CONFIG_HOME/pace/config.json`).
4. **Walking up from the current working directory** looking for `system/pace_index.db` — the original Claude-Code workflow where the user opens the vault folder directly.
5. **None of the above** → `pace_status` returns `initialized: false` and onboarding sets the vault location.

## CLI reference (the model uses MCP; humans use these)

| Command | Purpose |
|---|---|
| `pace init [<path>]` | Scaffold an empty vault. Idempotent. Records the vault path in the per-user config. |
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
tests/            # pytest suite (136+ tests)
plugin/           # Cowork plugin source — bundled into pace-memory.plugin
scripts/          # Tooling (e.g. scripts/build_plugin.py)
pyproject.toml    # entry points: pace = pace.cli:main, pace-mcp = pace.mcp_server:main
PACE PRD.md       # product spec
PACE Dev Plan.md  # phased implementation plan
CLAUDE.md         # vault instructions for Claude (used at session start)
```

Runtime vault directories (`memories/`, `projects/`, `system/`) are created by `pace init` and gitignored. This source repo doubles as a runnable vault — clone it into the folder you want to be your vault, run `pace init`, and you're set.

## Troubleshooting

### Cowork doesn't list `pace_*` tools after installing the plugin

`uv` is missing or wasn't on Cowork's `PATH` when it started. Install `uv`, restart Cowork, and re-enable the plugin. Run `uvx --from pace-memory pace-mcp --help` in a terminal to verify the package is reachable from PyPI.

### Claude Code doesn't list `pace_*` tools

Check that `.mcp.json` exists at the vault root. If not, `pace init` didn't run or didn't complete. The file's `command` field must point at a Python interpreter that has `pace` installed (re-run `pace init` if you moved the venv).

### "OneDrive has marked vault files as online-only"

`pace doctor` flagged `onedrive-virtualized`. SQLite mmap fails silently against virtualized files (PRD §7.2). Right-click the vault folder in File Explorer and choose **Always keep on this device**.

### "OneDrive produced N conflicted-copy files"

`pace doctor` flagged `conflicted-copies`. Two devices wrote divergent versions of the same file. PACE never picks a winner — open both, merge by hand, then `pace archive <path-to-loser>` to preserve the discarded version.

### "Daily compaction has never run" / "hasn't run in Nd Nh"

The scheduled task isn't firing. Check Cowork's scheduled-task UI to confirm the task is registered and not paused. The task only fires while Cowork is open on this machine — if you don't open Cowork on a given day, that day's compact is skipped.

### "N file(s) modified on disk after last index"

`pace doctor` flagged `index-drift`. You edited markdown directly (typically in Obsidian) without telling PACE. Run `pace reindex`.

### "PaceLockBusy: another PACE maintenance task already holds the lock"

Two compact or review runs collided. The first one will finish in seconds; retry. If it's stuck, delete `system/.pace.lock` (only when no PACE process is running).

### Tests fail with `ModuleNotFoundError: pace`

You're running pytest outside the venv. Activate it (`.venv\Scripts\activate`) and re-run.

## Platform support

- **Windows 11** with Cowork — primary target.
- **macOS** — should work; the only Windows-specific code path is `pace doctor`'s OneDrive virtualization check, which is gated by `sys.platform`. Mac dogfood pending.
- **OneDrive** — supported, but the PACE root must be configured "Always keep on this device." `pace doctor` verifies this.

## License

MIT. See [LICENSE](LICENSE).
