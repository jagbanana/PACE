---
description: Bootstrap a PACE vault in the current folder. Use this once in any new folder before you start talking to PACE — it scaffolds the vault, captures your identity, and asks you to restart the session.
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
  assistant-identity capture in Step 3b and only sign replies with
  whatever emoji they chose (or none).

## Step 2 — Scaffold the vault

Run this Bash command from the user's current working directory:

```
uvx --from "${CLAUDE_PLUGIN_ROOT}/server" pace init
```

This:

- Creates the `memories/`, `projects/`, `followups/`, `system/`
  directory structure.
- Initializes the SQLite index.
- Writes `CLAUDE.md`, a project-level `.mcp.json`,
  `system/prompts/{compact,review,heartbeat}.md`,
  `system/pace_config.yaml`, and `.gitignore`.
- Best-effort runs `git init`.

It's idempotent — safe to re-run — but stops short if the folder is
already a fully-initialized vault.

If the command exits non-zero or prints an error, surface the error to
the user verbatim and stop. Do not proceed to Step 3 if Step 2 didn't
succeed.

## Step 3 — Capture identity (also via Bash, since MCP isn't available yet)

Run these `pace capture` commands using the same
`uvx --from "${CLAUDE_PLUGIN_ROOT}/server"` prefix. Substitute the
user's actual answers; quote the content argument carefully (it may
contain spaces, apostrophes, or non-ASCII characters).

**a) The user's identity (always):**

```
uvx --from "${CLAUDE_PLUGIN_ROOT}/server" pace capture --kind long_term --topic user --tag "#person" --tag "#user" "<NAME> is <ROLE/DESCRIPTION FROM Q3>."
```

**b) The assistant identity (only if the user picked a nickname):**

```
uvx --from "${CLAUDE_PLUGIN_ROOT}/server" pace capture --kind long_term --topic user --tag "#preference" --tag "#user" --tag "#high-signal" "Assistant identity in this vault: nickname '<NICKNAME>', emoji '<EMOJI>'. Address the user as '<NAME>' at the top of every reply (vary the opener); sign with '— <NICKNAME> <EMOJI>' at the bottom."
```

**c) A pinned working-memory entry (always):**

```
uvx --from "${CLAUDE_PLUGIN_ROOT}/server" pace capture --kind working --tag "#user" --tag "#high-signal" "Identity bookends: address user as '<NAME>'; sign as '— <NICKNAME> <EMOJI>'. Working on: <WORK DESCRIPTION>."
```

If the user declined the nickname, write entry (c) without the
`'— <NICKNAME> <EMOJI>'` portion (just `address user as '<NAME>'.
Working on: ...`).

## Step 4 — Ask the user to restart

Once Steps 2 and 3 succeed, tell them something close to:

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
