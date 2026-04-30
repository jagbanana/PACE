# Changelog

All notable changes to PACE are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.1]: https://github.com/jagbanana/PACE/releases/tag/v0.2.1
[0.2.0]: https://github.com/jagbanana/PACE/releases/tag/v0.2.0
[0.1.2]: https://github.com/jagbanana/PACE/releases/tag/v0.1.2
[0.1.1]: https://github.com/jagbanana/PACE/releases/tag/v0.1.1
[0.1.0]: https://github.com/jagbanana/PACE/releases/tag/v0.1.0
