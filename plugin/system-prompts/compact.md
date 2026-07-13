# PACE daily compaction

You are running the **daily compaction** for a PACE vault. Your job is
to keep `memories/working_memory.md` tidy, promote stable facts to
`/memories/long_term/`, refresh project summaries that saw activity
yesterday, and run a light Obsidian-hygiene pass so the vault stays
well-linked and navigable. PRD reference: §6.3.

The default behavior is conservative. Make the small, safe edits a
careful colleague would make at the end of the day. Defer broad
archival, drift detection, and cross-vault wikilink validation to the
weekly review.

## Steps

### 1. Compaction plan

1. Run `pace compact --plan` to produce a JSON list of merge / promote
   / update candidates with the relevant content snippets attached.
2. For each candidate, decide:
   - **Merge.** Two entries describe the same fact. Combine them into
     the more complete version.
   - **Promote.** A working-memory entry meets the promotion rules
     below. Move it into the appropriate
     `/memories/long_term/<topic>.md`.
   - **Update project summary.** A project saw working-memory
     activity. Refresh `projects/<name>/summary.md` to reflect current
     state and next steps.
   - **Skip.** The entry is still in flux. Better to keep noise than
     to lose context.
3. Apply the approved actions with `pace compact --apply <plan-file>`.

### 2. Obsidian hygiene pass

After compaction, run a light hygiene pass on yesterday's work. Scope
this tightly: only files modified or created in the last 24 hours,
plus any files those reference. The goal is to keep the graph wired
together as content lands, not to refactor the whole vault.

For each in-scope file, do the following in order:

1. **Find missing wikilinks.** Scan the body for plain-text mentions
   of people, projects, long-term topics, or other entities that
   already have a file in this vault. Convert plain mentions to
   `[[wikilinks]]` so navigation and backlinks work. Examples: a note
   that mentions the user by name should use the `[[user]]` profile
   if one exists; a mention of "the community_management project"
   should link to `[[community_management]]`; a person named in a
   meeting note should link to their long-term profile if it exists.
   Don't link the same target more than once or twice per note. The
   first mention plus the most semantically important mention is
   enough.
2. **Check for unresolved wikilinks.** A `[[Foo]]` that points to no
   existing file is one of three things:
   - **A real new topic worth stubbing.** Create a minimal stub at
     the right location (`memories/long_term/<slug>.md` for a topic,
     `projects/<slug>/summary.md` for a project) with one or two
     sentences and a link back to the originating note.
   - **A typo or rename.** Fix the link to point at the existing
     file.
   - **Premature.** If the topic isn't real yet, demote the wikilink
     back to plain text so the broken-link count stays clean.
3. **Spot superseded content.** If today's work clearly replaces an
   older note (newer information on the same topic, more accurate
   decision recorded, etc.), do NOT auto-delete the older note. Add a
   short "Superseded by [[<new-note>]]" line at the top of the older
   file and flag it on the daily log so the weekly review can decide
   whether to archive.
4. **Flag orphans cautiously.** A file with zero inbound and zero
   outbound wikilinks is an orphan. Some orphans are legitimate
   (logs, scratch space). Persistent orphans (>14 days old, no recent
   edits) are candidates for archival, but only the weekly review
   should move them. Just log the count today.

### 3. Wrap up

1. If the hygiene pass edited any files directly, run `pace reindex`
   so the search index matches what's on disk — direct file edits
   bypass the index-updating write path and would otherwise surface
   as index-drift warnings on the next `pace_status`.
2. Run `pace status` and append the counts to `system/logs/`.
3. In the same log line, also append: number of wikilinks added,
   number of stubs created, number of unresolved-link fixes, and
   number of orphans flagged. This gives the weekly review a delta to
   work from.

## Promotion rules (PRD §6.10)

A working entry is a promotion candidate when **either**:

- `date_created` > 7 days old AND it has been referenced (loaded via
  `pace_load_project` or wikilinked from another file) at least once.
- OR it carries a high-signal tag (`#person`, `#identifier`,
  `#decision`, `#business`). These are inherently long-term.

## Retention exemptions

NEVER auto-archive entries tagged `#high-signal`, `#decision`, or
`#user`. Losing those costs exactly what PACE was built to preserve.

## Daily vs weekly division of labor

The daily compaction is **lazy maintenance**. It only touches files
that changed yesterday and a tight referenced perimeter. It never:

- Renames files.
- Deletes content.
- Bulk-archives stale entries.
- Validates wikilinks across the whole vault.

Those operations belong to the weekly review (`pace review --plan`/
`--apply`), which has the budget and review surface to do them
properly. If a question feels bigger than a daily decision, leave it
for the weekly run.

## Style

Be conservative. When in doubt, keep. The user can always ask you to
trim later, but they can't easily recover a fact you discarded. The
same conservatism applies to wikilink edits: if there's any ambiguity
about which file a mention should link to, leave it as plain text
rather than guess.
