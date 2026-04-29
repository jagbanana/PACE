# PACE daily compaction

You are running the **daily compaction** for a PACE vault. Your job is
to keep `memories/working_memory.md` tidy, promote stable facts to
`/memories/long_term/`, and refresh project summaries that saw activity
yesterday. PRD reference: §6.3.

## Steps

1. Run `pace compact --plan` to produce a JSON list of merge / promote
   / update candidates with the relevant content snippets attached.
2. For each candidate, decide:
   - **Merge** — when two entries describe the same fact, combine them
     into the more complete version.
   - **Promote** — when a working-memory entry meets the rules below,
     move it into the appropriate `/memories/long_term/<topic>.md`.
   - **Update project summary** — when a project saw working-memory
     activity, refresh `projects/<name>/summary.md` to reflect current
     state and next steps.
   - **Skip** — when the entry is still in flux. Better to keep noise
     than to lose context.
3. Apply the approved actions with `pace compact --apply <plan-file>`.
4. Run `pace status` and append the counts to `system/logs/`.

## Promotion rules (PRD §6.10)

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
