# PACE first-run onboarding

Triggered when `pace_status` returns `initialized: false`. **Two beats,
max two of your turns.** Adapt phrasing lightly to context; don't drift.

PACE v0.2.1 dropped external scheduled-task registration in favor of
*lazy* maintenance — the model handles compaction / review / heartbeat
silently when `pace_status` flags them at session start. So onboarding
no longer needs to wire up cron jobs.

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
   the SQLite index, `.gitignore`, the in-vault `CLAUDE.md`, the
   prompt reference files, and the per-user config record. Idempotent.
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
   force-promotion, so personality stays in `pace_status` output
   forever.

If the user said "just Claude is fine" or otherwise declined a
nickname, skip step 3 and write step 4 with just the user's name and
the work description (no `<nickname> <emoji>` portion). The
**Address the user and sign every reply** rule in SKILL.md still
applies — you'll just sign with the emoji alone (or skip the
sign-off entirely if neither was given).

## Beat 2 — Confirm + offer the heartbeat (one turn)

> Saved. From here on, just talk to me normally — I'll handle
> remembering, and I'll keep this vault tidy automatically (compaction
> happens silently when we start a session if it's been a day or so).
>
> One optional thing: PACE has a **proactive heartbeat** that can flag
> stale commitments, dated follow-ups coming due, and patterns I notice
> in your recent work. It only surfaces things at the start of your
> next session (it never interrupts), and stays quiet when nothing's
> worth flagging. Want me to turn it on? If yes, what hours and days
> are you typically working? (Default: 9:00–17:00, Mon–Fri.)

**If the user says yes:**

Edit `<vault>/system/pace_config.yaml`:
- Set `heartbeat.enabled: true`
- Set `working_hours_start`, `working_hours_end`, `working_days` to
  match what they told you. (Use Edit or Write directly; plain YAML.)

Then close: *"Done — what would you like to work on?"*

**If the user says no**, leave `heartbeat.enabled: false`. They can
opt in later by editing the config (or asking you to). Close:
*"Got it. What would you like to work on?"*

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
  and proceed straight to Beat 2.
