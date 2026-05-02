---
description: Bootstrap a PACE vault in the current folder
allowed-tools: ["Bash"]
---

The user just typed `/pace-setup`. They want to bootstrap a PACE vault in
the current folder.

**Why this command exists.** When the pace-memory plugin is installed via
Claude Desktop's "Upload Plugin" UI (the only install path today), its MCP
server isn't auto-loaded in Claude Code project sessions. That means
`pace_status`, `pace_init`, and the other `pace_*` MCP tools aren't
available for first-vault setup. This slash command sidesteps that by
invoking the plugin's bundled Python CLI directly via Bash. After
bootstrap, a project-level `.mcp.json` gets written and PACE loads
normally on the next session start.

## Step 1 — Greet and collect identity

Open with this script (adapt lightly to the conversation):

> Hi — I'm Claude. Before I scaffold this folder as a PACE vault, three
> quick questions:
>
> 1. What should I call you?
> 2. What name and emoji should I use for myself in this vault? Pick a
>    nickname plus emoji, or say "you pick" and I'll choose one that
>    fits the work, or "just Claude is fine" to skip the personality.
> 3. What's the rough nature of the work we'll be doing here?

Wait for the user's answers before doing anything else.

- If they defer on the emoji ("you pick"), choose one that fits the
  work: 🧠 memory/research, 📊 analytics, 🚀 launches, 🎨 design,
  📝 writing. Tell them which one you chose when you reply so they can
  object.
- If they opt out of a nickname ("just Claude is fine"), skip the
  assistant-identity capture in Step 5b and only sign replies with
  whatever emoji they chose (or none).

## Step 2 — Find the plugin install path

`${CLAUDE_PLUGIN_ROOT}` is **not** set in your Bash environment — it's
only substituted in `.mcp.json` files at MCP launch time. Don't use it
literally in shell commands; the shell expands it to empty. Find the
plugin install yourself:

```
PLUGIN_ROOT=$(ls -d ~/.claude/plugins/marketplaces/*/pace-memory 2>/dev/null | head -n 1)
echo "PLUGIN_ROOT=$PLUGIN_ROOT"
```

Verify the path is non-empty and contains both `.claude-plugin/plugin.json`
and `server/`. If the glob returns nothing, ask the user where the
pace-memory plugin is installed. Use `$PLUGIN_ROOT` for the rest of this
command.

## Step 3 — Install pace persistently (one-time per machine)

Before `pace init`, install the bundled CLI persistently so MCP launches
are sub-100ms instead of 5–30 seconds. This must run in its own process
*before* `pace init`; running it from inside a `pace init` process
triggers Windows file-lock errors.

```
uv tool install --force "$PLUGIN_ROOT/server"
```

This drops `pace-mcp.exe` (and `pace.exe`) into `~/.local/bin/` (same
directory as `uvx.exe`, already on Claude Code's launcher PATH).
Idempotent and safe to re-run; `--force` ensures plugin upgrades
replace older installs.

If the command fails with "Access is denied", the user has a stuck
install. Tell them to run `uv tool uninstall pace-memory` first, then
retry the install.

## Step 4 — Scaffold the vault

```
uvx --from "$PLUGIN_ROOT/server" pace init --plugin-root "$PLUGIN_ROOT"
```

`pace init` looks up the persistent install location from Step 3 via
`uv tool dir --bin` and embeds the absolute path to `pace-mcp.exe`
directly in `.mcp.json` — durable, fast, survives `uv cache clean`.

This step:

- Creates `memories/`, `projects/`, `followups/`, `system/` directories.
- Initializes the SQLite index.
- Writes `CLAUDE.md`, a project-level `.mcp.json` (pointing at the
  persistent `pace-mcp.exe` from Step 3),
  `system/prompts/{compact,review,heartbeat}.md`,
  `system/pace_config.yaml`, and `.gitignore`.
- Best-effort runs `git init`.

It's idempotent — safe to re-run — but stops short if the folder is
already a fully-initialized vault.

If the command exits non-zero or prints an error, surface the error
verbatim and stop. Do not proceed to Step 5.

## Step 5 — Capture identity

Run these `pace capture` commands using the same
`uvx --from "$PLUGIN_ROOT/server"` prefix. Substitute the user's actual
answers; quote the content argument carefully (it may contain spaces,
apostrophes, or non-ASCII characters).

**a) The user's identity (always):**

```
uvx --from "$PLUGIN_ROOT/server" pace capture --kind long_term --topic user --tag "#person" --tag "#user" "<NAME> is <ROLE/DESCRIPTION FROM Q3>."
```

**b) The assistant identity (only if the user picked a nickname):**

```
uvx --from "$PLUGIN_ROOT/server" pace capture --kind long_term --topic user --tag "#preference" --tag "#user" --tag "#high-signal" "Assistant identity in this vault: nickname '<NICKNAME>', emoji '<EMOJI>'. Address the user as '<NAME>' at the top of every reply (vary the opener); sign with '— <NICKNAME> <EMOJI>' at the bottom."
```

**c) A pinned working-memory entry (always):**

```
uvx --from "$PLUGIN_ROOT/server" pace capture --kind working --tag "#user" --tag "#high-signal" "Identity bookends: address user as '<NAME>'; sign as '— <NICKNAME> <EMOJI>'. Working on: <WORK DESCRIPTION>."
```

If the user declined the nickname, write entry (c) without the
`'— <NICKNAME> <EMOJI>'` portion (just `address user as '<NAME>'.
Working on: ...`).

## Step 6 — Ask the user to restart

Once Steps 3, 4, and 5 succeed, tell them something close to:

> Done — this folder is now a PACE vault, and I've saved your name and
> our shared identity. **Please close this Claude Code session and
> start a new one in this same folder (worktree off).** On the next
> start, the project-level `.mcp.json` will load the PACE MCP tools,
> and from then on just talk normally — I'll handle remembering for
> you.

If the user tries to capture something, ask you to remember a fact, or
do other PACE work in this same session before restarting, gently
remind them: the `pace_*` tools won't be available until after the
restart, so anything they say in this session won't be captured. Don't
attempt to call MCP tools that aren't loaded.
