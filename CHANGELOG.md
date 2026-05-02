# Changelog

All notable changes to PACE are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.6] — 2026-05-01

### Added
- **`pace bootstrap <path>` CLI command.** Single-command first-vault
  setup for technical users — bypasses the conversational
  "Onboard me to PACE" path entirely. Auto-discovers the pace-memory
  plugin install under `~/.claude/plugins/marketplaces/*/pace-memory/`,
  runs `uv tool install --force <plugin>/server` so `pace-mcp.exe`
  lands persistently in `~/.local/bin/`, then scaffolds the vault and
  writes a project-level `.mcp.json` pointing at the persistent
  binary. Open the resulting folder in Claude Code and the PACE MCP
  tools load on session start; the SKILL handles the brief identity
  onboarding conversationally on first chat. `--plugin-root` lets
  users with custom marketplaces or non-default install paths
  override the auto-discovery.
- **`vault._discover_plugin_root` and `vault.install_pace_persistently`
  helpers** factored out of the bootstrap command so they're
  reusable and testable.

### Changed
- **README install path rewritten.** The "Stand up your first vault"
  section now leads with `pace bootstrap`. The conversational
  "Onboard me to PACE" path is documented as a fallback, with an
  explicit note that Claude Code's skill activation for user-uploaded
  plugins is currently inconsistent — that's why the CLI is the
  recommended entry point.
- **SKILL.md description trimmed from 1215 to ~1000 chars** to fit
  Anthropic's marketplace-validator 1024-char limit on `description`
  fields. Same trigger-phrase coverage. New
  `test_skill_description_under_marketplace_char_limit` guards
  against regressions.

## [0.3.5] — 2026-05-01

### Fixed
- **`pace init` no longer attempts `uv tool install` from inside its
  own running process.** v0.3.4 invoked `uv tool install --force`
  during init, but when `pace init` is launched via `uvx --from
  <plugin>/server` and the plugin is already installed via
  `uv tool install`, uvx reuses the persistent install — meaning
  pace init was running *as* the very tool it was trying to
  overwrite. On Windows this hit "Access is denied" file-lock
  errors, sometimes leaving the persistent install half-deleted
  (missing modules like `colorama`). The bootstrap stuttered and
  produced broken vaults.

  v0.3.5 separates concerns:
  - `pace init` now only **looks up** the persistent install (via
    `uv tool dir --bin`); it never installs.
  - The SKILL/`/pace-setup` bootstrap recipe now runs `uv tool
    install --force "$PLUGIN_ROOT/server"` as its own explicit step,
    in its own subprocess, *before* invoking `pace init`. By the
    time pace init runs, the install is complete and not in flight.

  When pace init runs without a prior persistent install, it
  gracefully falls back to the `uvx --from` shape in `.mcp.json`
  (slow first launch, but functional). The user can promote to a
  fast install later by running `uv tool install` and re-running
  pace init.

### Changed
- **`PersistentInstallError` removed**, `_install_pace_persistently`
  renamed to `_resolve_persistent_pace_mcp` to reflect the
  lookup-only contract.
- **SKILL.md and `/pace-setup`** now have an explicit "Install pace
  persistently" step before "Scaffold the vault." Documentation
  shows the two-step pattern and explains when "Access is denied"
  during install means the user should run `uv tool uninstall
  pace-memory` and retry.

## [0.3.4] — 2026-05-01

### Fixed
- **MCP launch cold-start no longer trips Claude Code's startup
  timeout.** v0.3.3's project `.mcp.json` invoked `uvx --from
  <plugin>/server pace-mcp` on every session, which rebuilds the
  package in an ephemeral env (5+ seconds with warm wheels, 30s+ on
  cold cache). Claude Code's MCP launcher times out well before that
  finishes, so newly-bootstrapped vaults intermittently failed to
  connect.

  v0.3.4: at `pace init --plugin-root <path>` time, run
  `uv tool install --force <plugin>/server`. That drops a
  persistent `pace-mcp.exe` into `~/.local/bin/` (same directory
  Claude Code already knows about for `uvx`). The project
  `.mcp.json` then embeds the absolute path to that binary directly:

  ```json
  {
    "mcpServers": {
      "pace": {
        "command": "C:\\Users\\…\\.local\\bin\\pace-mcp.exe",
        "args": [],
        "env": { "PACE_ROOT": "…" }
      }
    }
  }
  ```

  Sub-100ms launches; survives `uv cache clean`; survives reboots.

### Added
- **`PersistentInstallError` exception** + graceful fallback. If
  `uv tool install` fails (no `uv` on PATH, network outage, malformed
  plugin source), `pace init` warns to stderr and falls back to the
  v0.3.3 `uvx --from` shape rather than aborting. The vault is still
  scaffolded and usable, just slow on first MCP launch until a manual
  install succeeds.

## [0.3.3] — 2026-05-01

### Added
- **`pace init --plugin-root <path>` CLI flag.** Lets the SKILL/slash-
  command bootstrap pass the plugin install path explicitly. When set,
  `pace init` writes a project `.mcp.json` with
  `uvx --from <plugin-root>/server pace-mcp` — durable, identical to
  the plugin's own root `.mcp.json`. Replaces v0.3.2's walk-up
  heuristic, which couldn't work in the actual uvx invocation case
  (uvx puts `pace.__file__` in its cache, which has no
  `.claude-plugin/` ancestor).

### Fixed
- **Real fix for the ephemeral-uvx-cache bug.** v0.3.1 wrote a
  `command` pointing at `%LOCALAPPDATA%\uv\cache\archive-v0\<hash>\
  Scripts\python.exe`. v0.3.2 tried to detect plugin context but
  detection couldn't fire from inside uvx's cache. v0.3.3 takes the
  plugin path as an explicit CLI argument from the bootstrap caller,
  closing the loop. New first-vault setups produce a project
  `.mcp.json` Claude Code can spawn against on every restart, even
  after `uv cache clean`.

### Changed
- **SKILL.md and `/pace-setup` bootstrap recipes rewritten.**
  Both now (1) instruct the model to discover the plugin install
  path via `ls -d ~/.claude/plugins/marketplaces/*/pace-memory`
  rather than relying on `${CLAUDE_PLUGIN_ROOT}` (which Claude Code
  doesn't expand inside Bash invocations); (2) pass `--plugin-root
  "$PLUGIN_ROOT"` to `pace init` so the resulting `.mcp.json` is
  durable; (3) use the same `$PLUGIN_ROOT` shell variable for all
  subsequent `pace capture` calls.

## [0.3.2] — 2026-05-01

### Fixed
- **Project-level `.mcp.json` now uses `uvx` when written from a
  plugin-context invocation.** v0.3.1's first-vault bootstrap ran
  `pace init` via `uvx --from <plugin>/server`, which made
  `sys.executable` an ephemeral path under
  `%LOCALAPPDATA%\uv\cache\archive-v0\<hash>\Scripts\python.exe`.
  Embedding that path in the project `.mcp.json` produced a config
  Claude Code couldn't re-spawn against on the next session, so
  the `pace_*` MCP tools never loaded for newly-bootstrapped vaults.

  `pace init` now detects when it's running inside a plugin install
  (via walking up from `pace.__file__` looking for
  `.claude-plugin/plugin.json`) and writes a `uvx --from <plugin>/server
  pace-mcp` command — the same self-resurrecting pattern the plugin's
  own root `.mcp.json` uses, just with the literal plugin path baked
  in (project-level `.mcp.json` doesn't get `${CLAUDE_PLUGIN_ROOT}`
  substitution). Dev/CLI invocations from a stable venv keep the old
  `sys.executable` form, since that's correct for them.

  This was the actual blocker that kept new vaults from coming online
  after restart in v0.3.1 — symptom was "vault scaffolds fine, identity
  saves fine, but `pace_status` and friends are missing in the next
  session."

## [0.3.1] — 2026-05-01

### Added
- **First-vault bootstrap recipe baked into SKILL.md.** When the user
  says "set up PACE" / "onboard me to PACE" / similar in a brand-new
  folder, the skill walks the model through a 4-step Bash-driven
  bootstrap (greet, run `pace init` via uvx, capture identity via
  `pace capture` invocations, ask the user to restart). After the
  restart, the project-level `.mcp.json` loads the PACE MCP server
  the normal way. End-user experience: open folder → "Set up PACE"
  → answer onboarding questions → restart → just talk.
- **`/pace-memory:pace-setup` slash command** as a redundant
  convenience that wraps the same recipe — useful if the user
  prefers typing slash commands. The skill is the primary path
  because slash commands from user-uploaded plugins have proven
  fragile in current Claude Code; the skill route works reliably
  through Bash + uvx regardless.

### Changed
- **SKILL.md description broadened.** First-vault setup phrases like
  "set up PACE", "onboard me to PACE", "make this a PACE vault",
  "initialize PACE here" now trigger the skill cleanly even in a
  brand-new folder where none of the existing-vault triggers apply.
  The skill now routes those requests at `/pace-setup` instead of
  trying to call `pace_init` (which fails when the MCP server isn't
  loaded).
- **"How to operate" section** added to both `CLAUDE_MD_TEMPLATE`
  and `SKILL.md`. Three posture principles every PACE agent now
  carries into every reply: (1) be useful — don't become a
  liability or seek unnecessary feedback; (2) act like a senior
  resource — build structures and surface them in Obsidian (with
  recommendations for Calendar, Dataview, Kanban, Tasks, Templater
  community plugins), then execute within them rather than
  continuously re-engineering; (3) recommend Connectors and MCP
  servers that would make the agent more independent, even if the
  user can't enable them.
- **README onboarding** updated to lead with `/pace-setup` as the
  one non-natural-language step. Status bumped to v0.3.1.

## [0.3.0] — 2026-05-01

### Added
- **Multi-vault support.** PACE now supports multiple agents on the
  same machine, each living in its own folder with its own memory.
  Stand up `~/agents/Misa` for marketing work, `~/agents/Bob` for
  research, etc.; opening a folder in Claude Code resolves to that
  folder's vault. The README documents the workflow under "Multiple
  PACE agents".

### Changed
- **Vault resolution chain reordered.** The cwd walk-up now beats the
  per-user config file (`%APPDATA%\pace\config.json` /
  `~/.config/pace/config.json`) so multi-vault sessions stay scoped
  to the folder Claude Code opened. The MCP server skips the
  per-user config entirely (`use_user_config=False`) — that file is
  CLI-only now, used as a "default vault when invoked from a folder
  that isn't part of any vault" fallback.
- **`pace init` no longer overwrites the per-user config** when a
  default is already set. New helper `set_vault_root_if_unset` makes
  initializing a *second* vault leave the *first* vault's
  CLI-default pointer alone. First init still seeds the pointer so
  `pace status` from any directory hits a sane default.
- **Plugin author** changed from "Justin Gesso" to "jaglab".
- **README** gains a top-of-page jump-to-Install link, advertises
  multi-agent support, and streamlines the "Stand up your first
  vault" section.

## [0.2.2] — 2026-04-30

### Added
- **Optional Routines guidance.** Lazy in-session maintenance is still
  the default and needs no setup, but if a user asks the model to
  register Claude Code Routines for predictable timing, both the
  CLAUDE.md template and the plugin SKILL.md now teach two
  non-negotiable rules:
  1. **Always create Local Routines, never Remote.** PACE's MCP runs
     on the user's machine; Remote Routines can't reach it (they fail
     silently or with a connection error).
  2. **If `system/prompts/{compact,review,heartbeat}.md` is missing**
     (common on vaults scaffolded before v0.2.0), call `pace_init()`
     first — it's idempotent and fills in missing files without
     touching existing content.

  Recommended cron expressions are documented for all three Routines.

### Changed
- README: clarified positioning ("like OpenClaw, but as a
  self-contained Claude Plugin"), restructured the "What PACE is" pitch,
  added "Natural language onboarding, no technical configuration" to
  the bullet list, refined the Cowork-vs-Claude-Code recommendation.

## [0.2.1] — 2026-04-29

### Changed
- **Pivoted primary client from Claude Cowork to Claude Code.** Install
  is now a single 3-step flow: download `pace-memory.plugin`, upload via
  *Customize → Browse Plugins → Personal → Upload Plugin*, restart the
  Claude Desktop App. No marketplace.json editing, no MAX_PATH
  workarounds, no manual extraction.
- **Replaced Cowork scheduled tasks with lazy in-session maintenance.**
  `pace_status` now returns three new flags — `needs_compact`,
  `needs_review`, `needs_heartbeat` — that the model handles silently
  in its next turn after replying to the user's first message of the
  session. No external scheduler required; works identically in any
  MCP-aware client.
- **Onboarding shrank from 3 beats to 2** (the scheduled-task
  registration step is gone; the heartbeat opt-in folded into the
  Beat 2 confirmation).
- **`system/prompts/{compact,review,heartbeat}.md` repurposed** as
  in-session reference docs instead of scheduled-task input. Same
  content, different invocation.

### Fixed
- The Cowork-specific UX trap of "the plugin loads but tools don't
  start" no longer affects new users — the install path that exhibits
  it is no longer the primary path.

### Known issues
- **Cowork v0.2.x**: the plugin loads in Cowork but its MCP server
  doesn't start. The bundled server itself is healthy (verified via
  manual `uvx --from <plugin>/server pace-mcp`); the issue is in
  Cowork's account-marketplace upload pipeline. Tracked at
  https://github.com/jagbanana/PACE/issues. **Workaround: use Claude
  Code.**

## [0.2.0] — 2026-04-29

### Added
- **Proactive heartbeat (opt-in).** A new background scheduled task that
  scans the vault during user-defined working hours and queues things
  worth flagging into a `followups/` inbox surfaced at the next session
  start. Three signals: ripe date triggers, stale commitments, and
  repeated patterns (person mentions, recurring decisions).
- **Followups memory tier.** New `followups/` directory holds proactive
  inbox items as Markdown files with YAML frontmatter (`pending`,
  `ready`, `done`, `dismissed`). Resolved items move to
  `followups/done/`.
- **New MCP tools:** `pace_add_followup`, `pace_list_followups`,
  `pace_resolve_followup`. `pace_status` now returns an `inbox` field
  with ready followups and a `last_heartbeat` timestamp.
- **New CLI commands:** `pace heartbeat --plan / --apply`,
  `pace followup add / list / resolve`.
- **Heartbeat scheduled-task prompt** at `system/prompts/heartbeat.md`,
  mirrored in the plugin under `system-prompts/heartbeat.md`.
- **Onboarding gained an opt-in step** asking whether the user wants the
  heartbeat enabled and what their working hours are. Defaults are
  9:00–17:00, Mon–Fri.
- **`pace_config.yaml` extended** with a `heartbeat:` section
  (`enabled`, `working_hours_start/end`, `working_days`,
  `cadence_minutes`, `stale_age_days`, `pattern_min_repeats`).

### Changed
- The session-start contract: when `pace_status.inbox` is non-empty, the
  model briefly surfaces ready followups at the top of its first reply,
  then resolves them as the user acts.

## [0.1.2] — 2026-04-29

### Added
- **Personality bookends.** The assistant now addresses the user by name
  at the top of every reply (with varied openers) and signs with an
  optional nickname + emoji at the bottom. Onboarding asks for both;
  user can opt out of either.
- **Identity-pin entry** captured to working memory at onboarding,
  tagged `#user #high-signal` so it's exempt from force-promotion and
  survives in `pace_status` output across sessions.

### Changed
- Force-promotion in daily compaction now skips entries tagged `#user`,
  `#high-signal`, or `#decision`. Halts cleanly when only exempt entries
  remain rather than evicting them.

### Fixed
- A bug introduced in 0.1.1 where the oldest working-memory entry could
  be force-promoted even when it carried a long-term retention tag.

## [0.1.1] — 2026-04-28

### Added
- **Working-memory char budget** with two-stage enforcement:
  - **Soft cap** (16K chars ≈ 4K tokens): daily compaction force-promotes
    oldest non-exempt entries to `memories/long_term/working-overflow.md`
    until the working file fits.
  - **Hard cap** (32K chars ≈ 8K tokens): `pace_status` truncates on the
    fly and appends a notice; older entries remain on disk and searchable.
- `system/pace_config.yaml` for per-vault tunables (working-memory
  budgets, retention thresholds). Tolerant loader returns defaults on
  malformed YAML.
- `pace doctor` now flags oversize working memory (warning over soft,
  error over hard).

### Changed
- `pace init` writes a documented default `pace_config.yaml`.

## [0.1.0] — 2026-04-27

### Added
- Initial public release.
- CLI (`pace`) and MCP server (`pace-mcp`) sharing one Python package.
- Cowork plugin (`pace-memory.plugin`) with bundled source and `uvx`
  runtime — no PyPI publish required to install.
- Memory tiers: working, long-term, project, archived.
- Daily compaction and weekly review as scheduled-task prompts.
- SQLite FTS5 index with refs-table-driven retention.
- `[[Wikilink]]` graph maintained on capture; rename-aware.
- `pace doctor` health checks (OneDrive virtualization, conflicted
  copies, index drift, lockfile, missing scheduled tasks).
- 160+ tests covering capture, search, compaction, review, doctor,
  MCP surface, plugin packaging, and onboarding artifacts.

[0.3.6]: https://github.com/jagbanana/PACE/releases/tag/v0.3.6
[0.3.5]: https://github.com/jagbanana/PACE/releases/tag/v0.3.5
[0.3.4]: https://github.com/jagbanana/PACE/releases/tag/v0.3.4
[0.3.3]: https://github.com/jagbanana/PACE/releases/tag/v0.3.3
[0.3.2]: https://github.com/jagbanana/PACE/releases/tag/v0.3.2
[0.3.1]: https://github.com/jagbanana/PACE/releases/tag/v0.3.1
[0.3.0]: https://github.com/jagbanana/PACE/releases/tag/v0.3.0
[0.2.2]: https://github.com/jagbanana/PACE/releases/tag/v0.2.2
[0.2.1]: https://github.com/jagbanana/PACE/releases/tag/v0.2.1
[0.2.0]: https://github.com/jagbanana/PACE/releases/tag/v0.2.0
[0.1.2]: https://github.com/jagbanana/PACE/releases/tag/v0.1.2
[0.1.1]: https://github.com/jagbanana/PACE/releases/tag/v0.1.1
[0.1.0]: https://github.com/jagbanana/PACE/releases/tag/v0.1.0
