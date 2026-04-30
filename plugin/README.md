# pace-memory — Claude Code plugin

PACE (Persistent AI Context Engine) is a local Markdown memory system
for Claude. It captures the people, decisions, dates, preferences, and
high-signal moments that surface during real work — and surfaces them
again next session. Day by day and week by week, the AI's working
knowledge of you and your business compounds.

This plugin is the recommended way to install PACE in **Claude Code**.
Once enabled, the `pace_*` tools appear in every Claude Code session
and the bundled skill tells the model when to invoke them. You don't
run any commands yourself — open the folder you want to use as your
vault and talk.

## Prerequisites

- The **Claude Desktop App** with Claude Code enabled.
- **`uv`** on your `PATH`. The plugin uses `uvx` to run the bundled PACE
  Python source in an isolated environment, so you don't manage Python
  or virtualenvs yourself.
  - **Windows (PowerShell):** `irm https://astral.sh/uv/install.ps1 | iex`
  - **macOS / Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

  After installing `uv`, **fully quit and relaunch the Claude Desktop
  App** so the new `PATH` propagates.

Verify `uv` is on your PATH:

```sh
uv --version
```

## Install (3 steps)

1. **Download** `pace-memory.plugin` from the
   [PACE releases page](https://github.com/jagbanana/PACE/releases).
2. **Open the Claude Desktop App** and go to **Customize → Browse
   Plugins → Personal → Upload Plugin**. Select the `.plugin` file.
3. **Restart the Claude Desktop App.**

That's it. Open any folder you want to be a PACE vault in Claude Code
and start a session.

> **About the file extension.** A `.plugin` file is just a zip archive
> with a different name — the convention Anthropic's plugin spec uses.
> If a tool refuses to recognize it, copy `pace-memory.plugin` to
> `pace-memory.zip` and use the copy.

## First use

Open Claude Code in any folder (the folder will become your vault, or
PACE will pick a path during onboarding if you'd rather). Start a
session and Claude will detect that no vault is initialized in this
folder, then run a short two-question onboarding:

1. What should it call you?
2. Optional nickname / emoji for the assistant.
3. Where on disk should the vault live, and what's the rough nature of
   your work?

After answering, Claude:

- Calls `pace_init` to scaffold the vault (`memories/`, `projects/`,
  `followups/`, `system/`, `.gitignore`, `.mcp.json`, an in-vault
  `CLAUDE.md`, and the in-session reference prompts).
- Captures your name, nickname (if given), and work description as the
  first long-term memories.
- Optionally turns on the proactive heartbeat (working hours opt-in).

That's the entire setup. No scheduled tasks to register, no cron, no
Windows Task Scheduler. Maintenance runs **lazily at session start**
when due — Claude handles compaction, weekly review, and the
heartbeat silently after replying to your first message.

## Using PACE day-to-day

You don't invoke PACE explicitly. Just talk to Claude in Claude Code.

- When you state a fact, decision, preference, or person worth
  remembering, it gets captured silently.
- When you mention a project — by name, by alias, or by a topical
  phrase like "the Q3 launch" — the model loads that project's
  summary before responding.
- When you ask "what do you know about X" or "who is Y", the model
  searches memory before answering.
- When you say "remind me Friday about the legal review", a followup
  is queued. The next session on or after that Friday surfaces it.

You can browse everything PACE has saved by opening the vault folder
in [Obsidian](https://obsidian.md) or any Markdown editor. The vault
is plain Markdown with `[[Wikilinks]]`, `#tags`, and YAML frontmatter
— no proprietary database, no cloud.

## Vault location and the per-user config

The MCP server resolves the vault path via this chain (first hit
wins):

1. **`PACE_ROOT` env var** — debugging escape hatch.
2. **`CLAUDE_PLUGIN_OPTION_VAULT_ROOT` env var** — set by Claude Code
   if you fill `vaultRoot` in the plugin's settings panel.
3. **Per-user config file** written by `pace_init`:
   - Windows: `%APPDATA%\pace\config.json`
   - macOS / Linux: `~/.config/pace/config.json` (or
     `$XDG_CONFIG_HOME/pace/config.json`).
4. **Nothing** — `pace_status` returns `initialized: false` and
   onboarding asks the user where to put the vault.

To change the vault location, the simplest path is to update
`vaultRoot` in the plugin's settings panel; the env-var override takes
precedence over the on-disk config so the change takes effect
immediately.

## Verify it's working

Start a Claude Code session in any folder and ask:
*"What memory tools do you have?"*

The model should mention `pace_status`, `pace_capture`, `pace_search`,
`pace_load_project`, `pace_list_projects`, `pace_create_project`,
`pace_init`, plus the followup tools (`pace_add_followup`,
`pace_list_followups`, `pace_resolve_followup`).

If those don't appear:

- Check that `uv` is on your shell's PATH (`uv --version`).
- Restart the Claude Desktop App fully (kill any tray processes too).
  PATH is read at launch, so a half-restart misses a fresh `uv`
  install.
- The first plugin launch downloads the server's runtime dependencies
  (`click`, `mcp`, `pyyaml`, `portalocker`, `python-dateutil`). If your
  network is restricted, allow `uv` access to `https://pypi.org` for
  that one-time fetch. Subsequent launches use the cache.

## Lazy maintenance — what runs when

PACE has no external scheduler. `pace_status` returns three flags that
tell the model which maintenance tasks are due:

- **`needs_compact`** — true if 24h+ since the last compaction. Claude
  runs `pace compact --plan/--apply` silently after replying to your
  first message.
- **`needs_review`** — true if 7d+ since the last weekly review. Same
  pattern; heavier work; only fires once a week.
- **`needs_heartbeat`** — true if you opted into the heartbeat, are in
  working hours, and the cadence guard has elapsed. Findings become
  `ready` followups for the next session's inbox.

You don't see any of this happening — the contract in `CLAUDE.md`
tells the model to handle these flags silently in its next turn after
greeting you.

## Cowork status

PACE was originally built for Claude Cowork. On v0.1.x, the Cowork
plugin path worked. **On v0.2.0+, the Cowork plugin loads but its
MCP server doesn't start in Cowork sessions** — the cause is in
Cowork's account-marketplace upload pipeline, not in PACE itself
(the bundled server runs fine when invoked directly). Tracked at
<https://github.com/jagbanana/PACE/issues>. **For now, use Claude Code.**

## Troubleshooting

### Tools don't appear

- `uv --version` works in your terminal? If not, install `uv` and
  fully restart the Claude Desktop App.
- Plugin showing in the Claude Code plugin list? Customize → Browse
  Plugins → Personal — you should see `pace-memory` listed and
  toggled on.
- First-launch network: `uv` needs one-time access to
  `https://pypi.org` to fetch the runtime deps; subsequent launches
  hit the cache.

### "OneDrive marked vault files as online-only"

The skill will surface this as a warning at session start. Right-click
the vault folder in File Explorer and choose **Always keep on this
device**. SQLite mmap fails silently against virtualized files.

### "OneDrive produced N conflicted-copy files"

Two devices wrote divergent versions of the same file. PACE never
picks a winner — the model will surface the conflict and ask which
version to keep. The CLI's `pace archive <path>` (run inside the
vault) preserves the loser without deleting it.

### "Vault not initialized" every session

The per-user config file is missing or pointing at a folder that no
longer exists. Re-run onboarding by saying *"Set up PACE"* in a new
conversation.

## License

MIT. See [LICENSE](LICENSE).

## Source and bug reports

<https://github.com/jagbanana/PACE>
