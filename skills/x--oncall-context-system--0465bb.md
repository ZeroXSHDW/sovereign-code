---
name: oncall-context-system
description: A file-based memory system so oncall context never evaporates between shifts or chat sessions — a living ticket ledger, a deadline calendar, a working-on tracker, an automation-gaps log, daily logs, and a shift handoff. Use when setting up an oncall workspace, starting or ending a shift, tracking tickets/deadlines across a rotation, generating a handoff, or keeping an AI agent oriented across oncall sessions.
---

# Oncall Context System

The problem this solves: oncall knowledge evaporates. It lives in one engineer's
head, in scattered chat sessions, in a ticket they looked at Tuesday and forgot
by Friday — and it's gone entirely at handoff. This is a lightweight,
plain-Markdown system that makes shift context **persistent, portable, and
agent-readable**. No database, no proprietary tool — just files in a folder,
committable to git.

## The Mental Model: Memory, Brain, Reflexes

Three layers, each with a distinct job. Don't blur them.

| Layer | What it is | Where it lives |
|-------|-----------|----------------|
| **Memory** | The persistent context — files that survive across sessions and shifts | `oncall-context/<week>/` |
| **Brain** | The know-how — triage logic, alarm correlation, service runbooks | your skills (see `ticket-triage`, `alarm-correlation`, `runbook-authoring`) |
| **Reflexes** | Automation triggers — shift start/end, context loading, stale-ticket scans | hooks / scheduled jobs |

This skill owns the **Memory** layer. The files are the source of continuity; the
skills tell the agent how to think; the hooks fire the routines.

## Layout

One folder per shift week (`YYYY-MM-DD_to_YYYY-MM-DD/`), each containing:

```
oncall-context/
  <week>/
    deadlines.md     # date-sorted deadlines & follow-ups — READ FIRST every session
    inherited.md     # frozen snapshot of what carried over from the previous shift
    tickets.md       # living ticket ledger — our journal of observations & actions
    pipelines.md     # living CI/CD journal (optional, if you own deploys)
    working-on.md     # what's actively in flight right now
    gaps.md          # automation gaps — things the agent couldn't do alone
    <YYYY-MM-DD>.md   # daily logs (append-only, one per day)
    summary.md        # shift info table + running snapshot
    handoff.md        # frozen at shift end — briefing for the next oncall
    incidents/
      <ticket-id>.md  # full audit trail per sev-2+ incident
templates/
  handoff.md          # canonical handoff template (copy in at shift end)
```

## The Files, and the Question Each Answers

| File | The question it answers | Rule |
|------|------------------------|------|
| `deadlines.md` | *What needs attention by when?* | **Read first, every session.** Date-sorted; each row has an explicit Action. Move to Completed when done; carry unresolved forward at handoff. |
| `tickets.md` | *What have we observed and done with each ticket?* | Journal, **not** source of truth — see the cardinal rule below. |
| `pipelines.md` | *What have we observed with deploys?* | Same journal semantics as tickets. |
| `working-on.md` | *What's consuming oncall attention right now?* | Update the moment scope changes (new wave, impact grows). Stale here = the next session is blind. |
| `gaps.md` | *What couldn't the agent automate?* | An automation backlog — feeds "what to build next." |
| `<date>.md` | *What happened today?* | Append-only. Never edit past days. Name by date, not "day 1". |
| `summary.md` | *Who owns this shift, and what's the snapshot?* | Canonical Shift Info table (oncall, previous oncall, start/end). |
| `inherited.md` | *What did I walk into?* | Frozen at shift start from the previous handoff. Don't edit after creation. |
| `handoff.md` | *What does the next person need?* | Frozen at shift end from the template. |
| `incidents/<id>.md` | *Exactly how did we handle this sev-2?* | Granular worklog — every action, comment, metric, timestamp. |

## The Cardinal Rule: Journal, Not Source of Truth

`tickets.md` and `pipelines.md` record *what you did and saw* — but tickets and
pipelines change independently (others comment, upstream resolves, escalations
fire). The journal goes stale the moment someone else acts.

- **User asks about a specific ticket/pipeline?** Read the journal for context on
  what's already been tried → **fetch fresh** from the system of record → update
  the journal with what you find.
- **Bulk operation** (triage sweep, handoff)? Use the journal as a starting point
  to avoid re-fetching everything; fetch fresh for anything that looks changed
  and for anything new.
- **After every action you take**, update the journal immediately so the next
  session has context.

Treat your ticketing/monitoring system as the source of truth for *state*; the
journal is your source of truth for *what we've investigated and decided*.

## The Shift Lifecycle

### Shift start
1. Determine the current week folder; create it if missing.
2. Read the previous shift's `handoff.md`.
3. Seed the new folder: `summary.md` (Shift Info), `inherited.md` (frozen from
   the handoff), `tickets.md` (carried-over tickets + standard section headers),
   `deadlines.md` (unresolved deadlines + known escalation dates), `working-on.md`
   (action items from the handoff), `gaps.md` (unresolved gaps), today's daily log.
4. Orient: surface deadlines due in the first days, and the most critical
   inherited items.

### During the shift
Update as you go — the "when X happens, update Y" reflex is what keeps the system
honest:

| When this happens… | Update… |
|---|---|
| Triage / discover tickets | `tickets.md` (rows), `summary.md` (counts), daily log |
| Discover a deadline or follow-up date | `deadlines.md` (row with date + explicit action) |
| Take action on a ticket | `tickets.md` (Status, Last Action, Updated), daily log; incident file if sev-2 |
| New impact numbers / expanded blast radius | `tickets.md` on **all** affected rows (old numbers are now stale), incident file |
| Resolve a ticket | move to Resolved in `tickets.md`, `summary.md` counts; move any deadline to Completed |
| Hit a wall the agent can't cross | `gaps.md` (what, why, what would automate it) |
| Learn something about a service | the relevant runbook |
| Start working a sev-2 | `working-on.md` |

### Shift end
1. Copy `templates/handoff.md` into the week folder.
2. Fill it from local data (tickets, deadlines, incidents, daily logs) and fresh
   API pulls (pipeline health, open-over-SLA, compliance dashboards).
3. Flag the sections only a human can fill (portal-only checks) for manual
   completion.
4. Carry unresolved deadlines and gaps forward into next week's files.
5. `tickets.md` is the primary source for the write-ups — but re-fetch ticket
   *state* to catch changes made outside your awareness.

## Handoff Doc: [AUTO] / [TOOL] / [HUMAN]

Mark every handoff section by how it gets filled — it makes generation
mechanical and makes the human's remaining work obvious:

- **[AUTO]** — filled from local context files (no API calls).
- **[TOOL]** — filled by live API/CLI calls (pipeline health, SLA queries, compliance).
- **[HUMAN]** — portal-only or judgment items the agent can't reach; list them in
  the preview so the oncall knows exactly what's left before publishing.

## Tips

- **`deadlines.md` is the heartbeat.** If the agent reads one file at session
  start, it's this — it converts a pile of tickets into "here's what's due today."
- **Journal ≠ truth.** The single most common failure is trusting a stale ledger.
  Fetch fresh for any specific question; use the journal to avoid *redundant* work,
  not to *replace* the system of record.
- **Append-only daily logs.** Editing history destroys the audit trail. New day,
  new entry.
- **`gaps.md` is a gift to your future self and your team** — it turns "the agent
  couldn't do X" into a prioritized automation backlog instead of silent friction.
- **Keep it in git.** History across rotations becomes searchable, and the handoff
  can double as a wiki source.
- For the after-action write-up once an incident is over, use the `postmortem`
  skill; for live sev handling, `incident-response`; for triage and correlation,
  `ticket-triage` and `alarm-correlation`.
