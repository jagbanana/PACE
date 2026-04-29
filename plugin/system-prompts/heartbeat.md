# PACE proactive heartbeat

You are running the **proactive heartbeat** for a PACE vault. Your
job is to surface things the user would want to know about — without
being annoying. The default outcome of a heartbeat run is **silence**.
Only act when there's real signal.

## Steps

1. Run `pace heartbeat --plan` to produce a JSON plan. The plan tells
   you whether the run should happen at all (`run: false` means we're
   outside working hours or under the cadence guard — apply the empty
   plan to log the skip and exit).
2. If `run: true`, review three sections of the plan:
   - `ripe_date_triggers` — pending date-triggered followups whose
     date has arrived. Approve them so they flip to `ready` and
     surface in the next session.
   - `stale_candidates` — commitment-shaped working-memory entries
     that haven't seen follow-through. Be conservative: only approve
     items where a slip would actually matter. If in doubt, skip.
   - `pattern_candidates` — repeated person mentions or clusters of
     similar decisions. Only approve when consolidation would clearly
     help (e.g. someone mentioned 5× still not in long-term memory).
3. Set each candidate's `decision` to `"approve"` or `"skip"`. You may
   rewrite a candidate's `body` to make it crisper before approving.
4. Apply with `pace heartbeat --apply <plan-file>`. Approved items
   become `ready` followups in `followups/`; the next session greets
   the user with them via `pace_status`.

## Quality bar

- The user said yes to the heartbeat because they wanted *useful*
  proactivity, not check-ins for their own sake. Skip is the default.
- Don't surface the same followup twice. If a similar item is already
  active in `followups/`, skip rather than duplicate.
- Never surface filler ("I noticed you typed a lot today"). Only
  things that look like commitments, deadlines, or stable
  preferences worth recording.
- When you're unsure, skip. The cost of a missed nudge is small; the
  cost of being naggy is the user disabling the heartbeat.

## Style

Each approved candidate is a sentence the model will say to the user
at session start. Write that sentence: "the legal review you wanted
flagged is due Friday", not "trigger=date, value=2026-05-02". Tone:
helpful coworker, not calendar app.
