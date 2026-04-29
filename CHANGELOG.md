# Changelog

All notable changes to PACE are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.2]: https://github.com/jagbanana/PACE/releases/tag/v0.1.2
[0.1.1]: https://github.com/jagbanana/PACE/releases/tag/v0.1.1
[0.1.0]: https://github.com/jagbanana/PACE/releases/tag/v0.1.0
