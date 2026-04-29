# pace-memory — Cowork plugin

PACE (Persistent AI Context Engine) is a local Markdown memory system
for Claude. It captures the people, decisions, dates, preferences, and
high-signal moments that surface during real work — and surfaces them
again next session. Day by day and week by week, the AI's working
knowledge of you and your business compounds.

This plugin is the Cowork-native way to install PACE. Once enabled, the
`pace_*` tools appear in every Cowork session and the bundled skill
tells the model when to invoke them. You don't run any commands
yourself — open the folder you want to use as your vault and talk.

## Prerequisites

- **Cowork** installed and running.
- **`uv`** on your `PATH`. Install from <https://docs.astral.sh/uv/>:
  - **Windows (PowerShell):** `irm https://astral.sh/uv/install.ps1 | iex`
  - **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

  The plugin uses `uvx` to run the bundled PACE Python source in an
  isolated environment, so you don't manage Python or virtualenvs
  yourself. After installing `uv`, **restart Cowork** so the new
  `PATH` propagates.
- **Python 3.11+** is fetched automatically by `uv` if it isn't
  already installed.

Verify `uv` is on your PATH:

```sh
uv --version
```

## Install

1. Download the latest `pace-memory.plugin` (a zip file) from the
   [PACE releases page](https://github.com/justingesso/pace/releases).
2. In Cowork, open the **Plugins** UI and choose *Install from file*
   (or drag the `.plugin` onto the Plugins window).
3. Cowork prompts for the plugin's `userConfig` values:
   - **`vaultRoot`** *(optional)* — absolute path to the folder you
     want PACE to use as its vault. Examples:
     - Windows: `C:\Users\you\Documents\my-pace-vault`
     - macOS / Linux: `/home/you/Documents/my-pace-vault`

     **Leave blank to let onboarding pick a path on first use.** You
     can change this later from Cowork's plugin settings.
4. Enable the plugin. Cowork spawns the bundled MCP server via
   `uvx`. The first launch takes a few seconds while `uv` resolves
   the server's dependencies (`click`, `mcp`, `pyyaml`,
   `portalocker`, `python-dateutil`); subsequent launches are
   instant — the resolved environment is cached.

The plugin **bundles its own Python source** (under `server/` inside
the zip), so it doesn't need to download anything from PyPI to start.
The dependencies above are the only things `uv` fetches at first run.

## First use

Open Cowork in any folder (it doesn't have to be the vault — the
plugin stores the vault location separately). Start a new conversation
and say something like *"Set up PACE"* or *"Let's get started with
memory"*, or just start working — the model will detect that no vault
is initialized and run a short three-question onboarding:

1. What should it call you?
2. Optional nickname for the assistant in this vault.
3. Where on disk should the vault live (if you didn't set `vaultRoot`
   at install time) and what's the rough nature of your work?

After answering, the model:

- Calls `pace_init` to scaffold the vault (`memories/`, `projects/`,
  `system/`, `.gitignore`, an in-vault `CLAUDE.md`, and the
  scheduled-task prompt files).
- Captures your name, nickname (if given), and work description as the
  first long-term memories.
- Offers to register two background tasks via Cowork's
  scheduled-tasks system: a daily compaction and a weekly review.
  Both use prompts bundled with this plugin.

That's the entire setup. You won't see any of these tool calls — the
skill instructs the model to handle them silently.

## Using PACE day-to-day

You don't invoke PACE explicitly. Just talk to Claude in Cowork.

- When you state a fact, decision, preference, or person worth
  remembering, it gets captured silently.
- When you mention a project — by name, by alias, or by a topical
  phrase like "the Q3 launch" — the model loads that project's
  summary before responding.
- When you ask "what do you know about X" or "who is Y", the model
  searches memory before answering.

You can browse everything PACE has saved by opening the vault folder
in [Obsidian](https://obsidian.md) or any Markdown editor. The vault
is plain Markdown with `[[Wikilinks]]`, `#tags`, and YAML frontmatter
— no proprietary database, no cloud.

## Vault location and the per-user config

The MCP server resolves the vault path via this chain (first hit
wins):

1. **`PACE_ROOT` env var** — debugging escape hatch.
2. **`CLAUDE_PLUGIN_OPTION_VAULT_ROOT` env var** — set by Cowork if
   you filled `vaultRoot` at install time.
3. **Per-user config file** written by `pace_init`:
   - Windows: `%APPDATA%\pace\config.json`
   - macOS / Linux: `~/.config/pace/config.json` (or
     `$XDG_CONFIG_HOME/pace/config.json`).
4. **Nothing** — `pace_status` returns `initialized: false` and
   onboarding asks the user where to put the vault.

To change the vault location, the simplest path is to update
`vaultRoot` in Cowork's plugin settings; the env-var override takes
precedence over the on-disk config so the change takes effect
immediately.

## Verify it's working

Start a Cowork conversation and ask: *"What memory tools do you have?"*
The model should mention `pace_status`, `pace_capture`, `pace_search`,
`pace_load_project`, `pace_list_projects`, `pace_create_project`, and
`pace_init`.

If those don't appear:

- Check that `uv` is on Cowork's PATH (Cowork inherits PATH from your
  shell — restart Cowork after installing `uv`).
- Open Cowork's plugin diagnostics (or the relevant log location for
  your OS) and look for errors from the `pace` MCP server.
- Run `uv --version` and `uvx --help` in a terminal to confirm `uv`
  itself is working.
- The first launch downloads the server's dependencies; if your
  network is restricted, you may need to allow `uv` access to
  `https://pypi.org` for that one-time fetch. Subsequent launches
  use the cache and need no network.

## Daily / weekly maintenance

If you accepted scheduled-task registration during onboarding, two
tasks run while Cowork is open:

- **Daily compaction** at 5:00 local time — promotes stable
  working-memory entries to long-term storage and refreshes project
  summaries that saw activity.
- **Weekly review** on Sundays at 6:00 — archives genuinely-stale
  long-term entries (older than 90 days, no recent references, not
  carrying retention-exempt tags) and writes a synthesis note.

Both prompts ship with this plugin under
`${CLAUDE_PLUGIN_ROOT}/system-prompts/`. You can inspect or tweak them
before they're registered with the scheduled-tasks system; subsequent
edits live inside Cowork's task definitions.

## Troubleshooting

### "Tools don't appear after install"

The bundled MCP server failed to start. Confirm `uv` is on PATH;
restart Cowork after installing `uv`. Check Cowork's plugin logs for a
`pace` server error.

### "OneDrive marked vault files as online-only"

The skill will surface this as a warning at session start. Right-click
the vault folder in File Explorer and choose **Always keep on this
device**. SQLite mmap fails silently against virtualized files.

### "OneDrive produced N conflicted-copy files"

Two devices wrote divergent versions of the same file. PACE never
picks a winner — the model will surface the conflict and ask which
version to keep. The CLI's `pace archive <path>` (run inside the
vault) preserves the loser without deleting it.

### "Daily compaction has never run" / "hasn't run in Nd Nh"

The scheduled task isn't firing. Check Cowork's scheduled-task UI to
confirm the task is registered and not paused. Tasks only fire while
Cowork is open on this machine.

### "Vault not initialized" every session

The per-user config file is missing or pointing at a folder that no
longer exists. Re-run onboarding by saying *"Set up PACE"* in a new
conversation.

## License

MIT. See [LICENSE](LICENSE).

## Source and bug reports

<https://github.com/justingesso/pace>
