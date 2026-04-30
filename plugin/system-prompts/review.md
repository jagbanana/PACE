# PACE weekly deep review (lazy, in-session)

You're running the weekly review because `pace_status` returned
`needs_review: true` (7d+ since the last run). Heavier than daily
compaction; archives stale long-term memory, validates cross-file
links, refreshes project summaries, and writes a weekly synthesis
note. Silent: don't announce; do this in a turn after the user's first
message has been handled.

## Steps

1. Run `pace review --plan` (Bash). It produces archival candidates
   with reference history and a broken-wikilink report.
2. For each archival candidate, confirm it's no longer relevant given
   current `working_memory.md` and active projects. When in doubt,
   keep. Skip anything tagged `#high-signal`, `#decision`, or `#user`.
3. Run `pace review --apply <plan-path>`.
4. Re-validate every active project's `summary.md` against its
   `notes/`. Flag anything that drifts.
5. Write a synthesis note at `memories/long_term/weekly_<YYYY-WW>.md`
   summarizing themes, decisions, and notable events from the week.

## Archival rules

An entry is an archival candidate when **all three** are true:

- `date_modified` > 90 days old.
- Zero references logged in the last 60 days (combined wikilinks +
  project loads in the `refs` table).
- The entry is no longer relevant given current working memory.

## Wikilink validation

For each `[[Target]]` that doesn't resolve to a vault file, record it
to the log. Do NOT auto-fix — surface unresolved links to the user via
the next session's `pace_status` so they can decide.

## Style

Synthesis matters more than counts. The weekly note is what the user
reads to feel that PACE is doing something.
