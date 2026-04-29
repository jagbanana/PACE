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

> **Important — Cowork and Claude Code use separate plugin systems
> inside the Claude Desktop app.** A plugin installed via the desktop
> app's *Settings → Customize* screen lands in Claude Code's plugin
> store and **does not appear in Cowork**, even though both are the
> same app. Cowork has its own marketplace under your active
> Cowork session directory, and a plugin must be installed there
> specifically to show up in Cowork sessions.

### Step 1 — Get the `.plugin` file

Download the latest `pace-memory.plugin` from the
[PACE releases page](https://github.com/justingesso/pace/releases),
or build it from the source repo (`python scripts/build_plugin.py`,
which writes `dist/pace-memory.plugin`).

> **About the file extension.** A `.plugin` file is just a zip archive
> with a different name — that's the convention Anthropic's plugin
> spec uses. There is no separate `.zip` file anywhere; if you opened
> `pace-memory.plugin` with 7-Zip, you'd see all the contents. The
> extraction steps below treat it as a zip throughout.

### Step 2 — Try Cowork's UI first

If Cowork exposes an *Install plugin from file* (or *Upload plugin*)
option in its own panel — distinct from the desktop app's
*Settings → Customize* — use that and skip to **Step 6**. If your
Cowork install doesn't have such a UI, or it deposits the plugin in
Claude Code's location instead of Cowork's, fall through to Step 3.

### Step 3 — Locate your Cowork marketplace folder

Cowork stores its plugins under your active session directory.
Open File Explorer to:

```
%APPDATA%\Claude\local-agent-mode-sessions\
```

Navigate into the most recently-modified subfolder, then again into
the most recently-modified subfolder inside that. You should land in
a directory containing `cowork_plugins\`. Continue into:

```
cowork_plugins\marketplaces\local-desktop-app-uploads\
```

That's where local plugins go. The folder should already contain a
`.claude-plugin\marketplace.json` describing the local marketplace.

### Step 4 — Extract the `.plugin` into a subfolder

The marketplace expects each plugin as an **extracted directory**,
not the zip file itself. Recommended approach on Windows: use the
built-in `tar` (works on `.plugin` directly without renaming) from
PowerShell.

```powershell
$plugin = "C:\path\to\pace-memory.plugin"   # adjust to where you saved it
$dest   = "$env:APPDATA\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\marketplaces\local-desktop-app-uploads\pace-memory"
New-Item -ItemType Directory -Path $dest -Force | Out-Null
tar -xf $plugin -C $dest
```

After extraction the layout should be:

```
local-desktop-app-uploads\
├── .claude-plugin\
│   └── marketplace.json
└── pace-memory\
    ├── .claude-plugin\plugin.json
    ├── .mcp.json
    ├── server\        ← bundled Python source
    ├── skills\pace-memory\
    └── system-prompts\
```

**Other extractors that work:**

- **7-Zip** — handles `.plugin` directly; right-click → 7-Zip →
  Extract files.
- **Git Bash's `unzip`** — `unzip pace-memory.plugin -d <dest>`.
- **Windows' built-in *Extract All*** — only after renaming the
  file extension from `.plugin` to `.zip`. (File Explorer shows
  *Extract All* by extension, not by content.)

**Don't use Python's `zipfile.extractall`** from a script on Windows
without long-path mode. The Cowork session path is already two UUIDs
deep; combined with the plugin's internal `skills\pace-memory\references\
onboarding.md` nesting you can blow past Windows MAX_PATH (260 chars)
mid-extraction and the extractor fails with `FileNotFoundError`. The
extractors above all opt into long paths correctly.

### Step 5 — Register the plugin in the marketplace manifest

Open `local-desktop-app-uploads\.claude-plugin\marketplace.json` in
any text editor. Add an entry to the `plugins` array (replace `[]` if
that's what's there):

```json
{
  "name": "local-desktop-app-uploads",
  "version": "1.0.0",
  "description": "Locally uploaded plugins via Claude Desktop app",
  "owner": { "name": "Local User" },
  "plugins": [
    {
      "name": "pace-memory",
      "source": "./pace-memory",
      "description": "Persistent AI Context Engine — local Markdown memory for Claude. Remembers people, decisions, and project context across sessions in a human-readable vault."
    }
  ]
}
```

If the marketplace already lists other local plugins, just append the
`pace-memory` entry to the `plugins` array.

### Step 6 — Restart Cowork

Fully quit Cowork. On Windows: open Task Manager, end every `Claude.exe`
/ `Cowork.exe` process (some persist as a tray icon after the window
closes), then relaunch. On startup Cowork rescans marketplaces and
discovers `pace-memory`.

### Step 7 — Enable the plugin in Cowork's UI

In Cowork's plugin / customize panel, find `pace-memory` listed
under the local-desktop-app-uploads marketplace and toggle it on.
Cowork prompts for the plugin's `userConfig` values:

- **`vaultRoot`** *(optional)* — absolute path to the folder you
  want PACE to use as its vault. Examples:
  - Windows: `C:\Users\you\Documents\my-pace-vault`
  - macOS / Linux: `/home/you/Documents/my-pace-vault`

  **Leave blank to let onboarding pick a path on first use.** You
  can change this later from Cowork's plugin settings.

After enabling, Cowork spawns the bundled MCP server via `uvx`. The
first launch takes a few seconds while `uv` resolves the server's
dependencies (`click`, `mcp`, `pyyaml`, `portalocker`,
`python-dateutil`); subsequent launches are instant — the resolved
environment is cached.

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

### "Tools don't appear after install" — most common cause

The plugin probably landed in Claude Code's plugin store rather than
Cowork's marketplace. They look like the same install button, but
they're separate stores under the hood. Check:

```
%APPDATA%\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\installed_plugins.json
```

If `"plugins"` is `{}`, Cowork has *zero* plugins enabled — the
install went to the wrong place. Walk through the Step 3–7 install
procedure above to put it in Cowork's marketplace and enable it.

You can also check whether `pace-memory` made it into Cowork's
marketplace by looking at:

```
%APPDATA%\Claude\local-agent-mode-sessions\<session>\<session>\cowork_plugins\marketplaces\local-desktop-app-uploads\
```

If there's no `pace-memory\` subdirectory or the directory is missing
the `server\`, `skills\`, or `system-prompts\` folders, the
extraction wasn't complete (often a Windows long-path issue — see
next entry).

### Extraction failed with `FileNotFoundError` or "Path too long"

You hit Windows' MAX_PATH (260-char) limit while extracting the
plugin. The Cowork session directory contains two UUIDs that already
eat ~80 chars; combined with the plugin's internal
`skills\pace-memory\references\onboarding.md` nesting, some files
blow past the limit. Solutions, in order of preference:

1. **`tar -xf` from PowerShell** — built into Windows 10/11, opts
   into long paths automatically, and works on `.plugin` directly:
   `tar -xf pace-memory.plugin -C <destination>`.
2. **Git Bash's `unzip`** — `unzip pace-memory.plugin -d <destination>`,
   no rename required.
3. **7-Zip** — if installed, right-click → 7-Zip → Extract files.
4. **Windows' built-in *Extract All*** — only after renaming the
   file extension from `.plugin` to `.zip` (File Explorer keys off
   the extension to decide whether to offer *Extract All*).
5. **Avoid Python's `zipfile.extractall`** from scripts — it does
   *not* automatically opt into long-path mode on Windows.

### "Where's the zip file?" — there isn't one separately

A `.plugin` file IS a zip archive, just with the extension Anthropic's
plugin spec uses. The build script writes a single
`dist/pace-memory.plugin`; that's the zip. If you need to convince a
tool that doesn't understand the `.plugin` extension, copy the file
to `pace-memory.zip` and use that copy.

### "Tools don't appear" but `installed_plugins.json` shows pace-memory

The MCP server itself failed to start. Confirm:

- `uv --version` succeeds in PowerShell.
- After installing `uv`, you fully quit Cowork (including tray
  processes via Task Manager) and relaunched. Cowork inherits PATH
  at launch time, so a half-restart misses the new `uv`.
- The first launch needs network access to `https://pypi.org` so
  `uv` can fetch the runtime deps. Subsequent launches use the cache.

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
