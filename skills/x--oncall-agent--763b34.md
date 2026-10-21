---
name: oncall-agent
description: The orchestrator that composes the oncall skill set into a single autonomous on-call assistant — routing each situation (shift start, triage, alarm, live incident, handoff) to the right specialist skill and keeping them coordinated through shared context files. Use when acting as on-call, running a shift end-to-end, or setting up an AI on-call agent. This is the entry point; it delegates to oncall-context-system, ticket-triage, alarm-correlation, incident-response, runbook-authoring, evidence-discipline, and postmortem.
---

# Oncall Agent (Orchestrator)

The other oncall skills are **specialists**; this is the **conductor**. On its own
each skill does one thing well — but a shift is a flow through all of them, sharing
one set of context files. This skill is the routing layer: it decides which
specialist to invoke for the situation in front of you, and it enforces the
contract that keeps them consistent.

If you only load one oncall skill, load this one — it pulls in the rest as needed.

## The System: Memory · Brain · Reflexes

```
                        ┌─────────────────────────────┐
                        │        oncall-agent          │   ← you are here (router)
                        └───────────────┬─────────────┘
                                        │ routes to
     ┌──────────────┬──────────────┬────┴────────┬──────────────┬──────────────┐
     ▼              ▼              ▼             ▼              ▼              ▼
 ticket-triage  alarm-        incident-     runbook-       postmortem     evidence-
                correlation   response      authoring                     discipline
     └──────────────┴──────────────┴─────────────┴──────────────┴──────────────┘
                                        │ all read/write
                                        ▼
                         ┌─────────────────────────────┐
                         │     oncall-context-system    │   ← shared memory (the files)
                         └─────────────────────────────┘
```

- **Memory** = `oncall-context-system` — the files every specialist reads and writes.
- **Brain** = the specialist skills — how to triage, correlate, handle a sev, write a runbook.
- **Reflexes** = hooks/scheduled jobs that fire the routines (shift start, stale scan).
- **`evidence-discipline`** is cross-cutting — it governs *every* claim any specialist makes.

## Routing Table — Situation → Skill

Match the situation to the specialist. This is the core of the orchestrator.

| Situation | Route to | Then |
|-----------|----------|------|
| Starting/ending a shift; "where are we?" | `oncall-context-system` | Read `deadlines.md` first, then `working-on.md` |
| A queue of open tickets to work | `ticket-triage` | Categorize, prioritize, parallel-investigate |
| One or more alarms firing | `alarm-correlation` | Cluster first — don't investigate alarms one-by-one |
| A confirmed sev1/sev2 with impact | `incident-response` | Runs the live checklist; pulls the runbook |
| Investigating a service you have a runbook for | `runbook-authoring` (to read/update) | Pattern-match the ranked-likelihood table |
| Incident is over, needs an after-action | `postmortem` | Blameless timeline + preventive actions |
| Any factual claim that drives an action | `evidence-discipline` | Cite source, label tier, no correlation-as-cause |

## The Shift, End to End

A full rotation flows through the specialists in a predictable order. Each phase
reads and writes the shared context files, so the next phase (and the next
session, and the next oncall) has what it needs.

### 1. Shift start → `oncall-context-system`
Create/locate the week folder, seed files from the previous handoff, read
`deadlines.md` and `inherited.md`, surface what's due and what carried over.

### 2. Initial triage → `ticket-triage` (+ `alarm-correlation`)
Sweep the queues, categorize and prioritize. **If 3+ tickets need investigation,
fan out read-only sub-agents** (per `ticket-triage`). If multiple alarms are
present, run `alarm-correlation` first to collapse a storm into a few root
causes before you spend effort per-ticket. Reconcile all findings into
`tickets.md` in one pass (only the main agent writes).

### 3. During the shift → route per situation
- New alarm → `alarm-correlation` → matching runbook (`runbook-authoring`).
- Confirmed sev1/sev2 → `incident-response` (which itself pulls the runbook and
  opens the incident file in `oncall-context-system`).
- Every claim you post → filtered through `evidence-discipline`.
- Learned something new about a service → update its runbook (`runbook-authoring`).
- Hit a wall the agent can't cross → log it in `gaps.md`.

### 4. Incident aftermath → `postmortem`
Once a sev is resolved and it warrants an after-action, switch from the live
`incident-response` mode to `postmortem`: blameless timeline, root cause,
preventive action items with owners.

### 5. Shift end → `oncall-context-system`
Generate the handoff ([AUTO]/[TOOL]/[HUMAN] sections), carry unresolved
deadlines and gaps forward, freeze `handoff.md`.

## The Coordination Contract

The specialists stay consistent because they all obey the same rules about the
shared state. This contract is what makes them composable rather than colliding:

1. **One writer.** Only the main agent writes to `tickets.md` and the other
   ledgers. Sub-agents spawned during triage are **read-only** — they return
   findings; the orchestrator reconciles and writes. This prevents concurrent
   writes from corrupting the ledger.
2. **Journal ≠ source of truth.** Every specialist reads the ledger for context
   but re-fetches live state for specific questions (the cardinal rule from
   `oncall-context-system`).
3. **`deadlines.md` is read first, every session** — it's the heartbeat that tells
   any specialist what's due now.
4. **Evidence discipline is non-negotiable across all of them** — triage
   findings, correlation conclusions, incident impact numbers, and postmortem
   root causes all cite sources and label evidence tier.
5. **Runbooks are living** — `incident-response` and `alarm-correlation` *read*
   them; after any incident, `runbook-authoring` *updates* them with what was
   learned.

## Installing the Set

These seven skills are designed to be installed together:

```bash
for s in oncall-agent oncall-context-system ticket-triage alarm-correlation \
         incident-response runbook-authoring postmortem evidence-discipline; do
  ln -s "$PWD/skills/$s" ~/.claude/skills/"$s"
done
```

The agent auto-selects among them by `description`, but loading `oncall-agent`
gives it the map of how they fit together.

## Adapting to Your Stack

The specialists are tool-agnostic by design. Point them at your systems once:

- **Ticketing** — wire `ticket-triage`/`incident-response` to your ticket API/CLI.
- **Monitoring** — wire `alarm-correlation` to your metrics/alerting system.
- **CI/CD** — the deploy-correlation step in `incident-response` uses your pipeline tool.
- **Chat** — outage comms in `incident-response` post to your incident channel.
- **Context dir** — set where `oncall-context-system` stores the week folders.

## Tips

- **Route, don't do-it-all.** The orchestrator's job is to pick the right
  specialist and hold the shared contract — not to re-implement triage or
  incident logic inline.
- **Correlate before you investigate.** An alarm storm routed straight to
  per-ticket triage wastes effort; `alarm-correlation` collapses it first.
- **One writer, many readers.** The read-only-sub-agent rule is what lets you
  parallelize triage without corrupting the ledger.
- **`deadlines.md` first, evidence discipline always.** Those two habits carry
  more weight than any single specialist.
- **Live vs. after-action are different modes** — `incident-response` while it's
  burning, `postmortem` once it's out.
