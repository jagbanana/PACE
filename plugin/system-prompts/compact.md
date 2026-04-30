# PACE compaction (lazy, in-session)

You're running PACE compaction because `pace_status` returned
`needs_compact: true` (24h+ since the last run). This is silent
maintenance — the user has already been greeted; do this work in your
next turn without announcing it.

## Steps

1. Run `pace compact --plan` (Bash). It writes a JSON file under
   `system/logs/` and prints the path.
2. Read the JSON. For each candidate in `candidates[]`, decide:
   - **Merge** — when two entries describe the same fact, combine them
     into the more complete version.
   - **Promote** — when a working-memory entry meets the rules below,
     set `decision: "approve"`. The plan's `suggested_topic` is a sane
     default; override `topic` if you want a different long-term file.
   - **Skip** — when the entry is still in flux. Set
     `decision: "skip"`. Better to keep noise than to lose context.
3. Save the edited plan to the same path.
4. Run `pace compact --apply <plan-path>`.

## Promotion rules

A working entry is a promotion candidate when **either**:

- `date_created` > 7 days old AND it has been referenced (loaded via
  `pace_load_project` or wikilinked from another file) at least once;
- OR it carries a high-signal tag: `#person`, `#identifier`,
  `#decision`, `#business` — these are inherently long-term.

## Retention exemptions

NEVER auto-archive entries tagged `#high-signal`, `#decision`, or
`#user`. Losing those costs exactly what PACE was built to preserve.

## Style

Be conservative. When in doubt, keep. The user can always ask you to
trim later, but they can't easily recover a fact you discarded.
