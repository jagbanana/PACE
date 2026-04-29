# PACE first-run onboarding

Triggered when `pace_status` returns `initialized: false`. Three beats,
max three of your turns. Adapt phrasing lightly to context; don't drift.

## Beat 1 — Introduce + collect (one turn)

Open with this script:

> Hi — I'm Claude, and this folder will be set up as a **PACE root** so
> I can remember our work between sessions. A few quick questions
> before we begin:
>
> 1. What should I call you?
> 2. What name and emoji should I use for myself in this vault? Pick
>    a nickname plus any emoji — or just say "you pick" and I'll
>    choose an emoji that fits the work. (You can also say "just
>    Claude is fine" to skip the personality.)
> 3. What's the rough nature of the work we'll be doing here, and where
>    on disk should the vault live? (Pick a folder you'll come back to
>    — typically somewhere in your Documents.)

If the user defers on the emoji ("you pick"), choose one that fits the
work description (e.g. 🧠 for memory/research, 📊 for analytics, 🚀
for launches, 🎨 for design, 📝 for writing). Tell the user which one
you picked in your next reply so they can object.

After the user answers, call (in this order):

1. `pace_init(root="<path they gave>")` — scaffolds the vault folder,
   the SQLite index, `.gitignore`, the in-vault `CLAUDE.md`, and the
   scheduled-task prompt files. Idempotent. Also records the path in
   the per-user config so future sessions find it automatically.
2. `pace_capture(kind="long_term", topic="user", content="<their name
   and role/description>", tags=["#person", "#user"])`.
3. **If the user picked a nickname (and possibly emoji):**
   `pace_capture(kind="long_term", topic="user", content="Assistant
   identity in this vault: nickname '<nickname>', emoji '<emoji>'.
   Address the user as '<name>' at the top of every reply (vary the
   opener); sign with '— <nickname> <emoji>' at the bottom.",
   tags=["#preference", "#user", "#high-signal"])`.
4. `pace_capture(kind="working", content="Identity bookends: address
   user as '<name>'; sign as '— <nickname> <emoji>'. Working on:
   <work description>.", tags=["#user", "#high-signal"])` — this
   pinned working-memory entry is exempt from compaction's
   force-promotion (PRD §6.10), so personality stays in `pace_status`
   output forever.

If the user said "just Claude is fine" or otherwise declined a
nickname, skip step 3 and write step 4 with just the user's name and
the work description (no `<nickname> <emoji>` portion). The
**Address the user and sign every reply** rule in SKILL.md still
applies — you'll just sign with the emoji alone (or skip the
sign-off entirely if neither was given).

## Beat 2 — Propose scheduled tasks

> Saved. I'm setting up two background tasks so I can keep my memory
> tidy without bothering you: a **daily** compaction that consolidates
> each day's notes, and a **weekly** review that archives stale items
> and synthesizes themes. They run inside Cowork while it's open.
> Sound good?

If the user agrees, register both tasks via Cowork's
`mcp__scheduled-tasks__create_scheduled_task` tool. Both prompts ship
with this plugin and resolve via the `${CLAUDE_PLUGIN_ROOT}` env var:

- **Daily compaction** — daily at 5:00 local time. Read the contents
  of `${CLAUDE_PLUGIN_ROOT}/system-prompts/compact.md` and pass it as
  the task's prompt verbatim.
- **Weekly review** — Sundays at 6:00 local time. Read
  `${CLAUDE_PLUGIN_ROOT}/system-prompts/review.md` and pass it
  verbatim.

If the user declines, register both tasks anyway in a paused state (or
note that the absence will be surfaced through future `pace_status`
warnings). Don't push back.

## Beat 3 — Confirm + finish (one turn)

> Done. Vault folder created at `<path>`, version control initialized,
> both tasks scheduled. From here on, just talk to me normally — I'll
> handle remembering. What would you like to work on?

End onboarding. Resume normal flow with the user's next message.

## Edge cases

- **User specifies an absolute path that doesn't exist yet.** Fine —
  `pace_init` creates parent directories.
- **User wants the vault inside OneDrive.** Mention they should
  right-click the folder in File Explorer and choose "Always keep on
  this device" — `pace_doctor` will surface a warning later if they
  forget. Don't block onboarding on this.
- **User asks "what are you saving about me?" mid-onboarding.** Point
  them at `<vault>/memories/long_term/` — everything is human-readable
  Markdown, nothing is hidden. Then resume.
- **`pace_init` returns `already_initialized: true`.** The path the
  user gave is already a vault. Skip the captures (don't double-write)
  and proceed straight to Beat 2 to propose scheduled tasks.
