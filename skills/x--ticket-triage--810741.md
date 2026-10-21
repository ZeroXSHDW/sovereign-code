---
name: ticket-triage
description: Triage a queue of open oncall/support tickets — categorize, prioritize, de-stale, and investigate in parallel. Use when you cover one or more oncall queues and need to work down a backlog, do a start-of-shift sweep, or figure out what to look at first. Provides a categorization scheme, a priority order, staleness rules, and a parallel sub-agent investigation pattern.
---

# Ticket Triage

A repeatable playbook for working down a queue of open tickets across the
teams/queues you cover. The goal of triage is not to *solve* everything — it's
to know, in one pass, what each ticket is, how urgent it is, and what happens
next. Tool-agnostic: use your ticketing system's API/CLI wherever this says
"fetch" or "update."

## Mental Model

Triage is a **funnel**, not a solve-loop. One pass to see everything, categorize,
and rank; a second pass (often parallel) to investigate the ones that need it;
a final pass to record decisions. Don't rabbit-hole on ticket #1 while forty
others sit unread — breadth before depth.

## Step 1: Fetch the Open Backlog

Pull open tickets across every queue you cover. Include statuses **Assigned,
Researching, In Progress, Pending**; sort by **last-updated**; cap at ~100 so
one runaway queue doesn't drown the rest.

```
# Pseudocode — map to your ticketing system's API/CLI
list_tickets(queues=[...], statuses=[Assigned, Researching, InProgress, Pending],
             sort=last_updated_desc, limit=100)
```

## Step 2: Categorize Into Exactly One Bucket

Every ticket gets **one** bucket. Detect by title markers and keywords first;
open the body only when the title is ambiguous.

| Bucket | Signals | What it is |
|--------|---------|------------|
| **ALARM** | auto-generated title, monitoring-tool prefix, metric/threshold language | Cut automatically by a monitoring system |
| **ACTION-REQUIRED** | "action required", a deadline/date, policy/security/compliance ask | Someone needs you to *do* a specific thing by a date |
| **COMPLIANCE** | audit, certificate/dependency expiry, mandatory upgrade, patch | Recurring obligation, usually with a due date |
| **BUG/ISSUE** | error, broken, regression, stack trace, "not working" | A defect to reproduce and fix |
| **REQUEST** | access, quota/limit increase, onboarding, "can you" | A fulfillment ask, low investigation |

If two buckets seem to fit, pick the one with the **hardest deadline / highest
blast radius** (ACTION-REQUIRED over BUG, ALARM over REQUEST).

## Step 3: Prioritize in This Order

1. **sev2 / impact-2** — highest severity, active customer impact. Always first.
2. **Alarms created today** — could be a live, still-firing issue.
3. **ACTION-REQUIRED past its deadline** — already late, escalating cost.
4. **Aging sev3 (> 7 days)** — quietly rotting; pull forward before they go stale.
5. **Low-priority batch** — requests, nits, informational. Handle in bulk.

## Step 4: Don't Leave Triaged Tickets in "Assigned"

"Assigned" means *nobody has looked yet*. Once you've triaged one, move it so the
queue reflects reality:

| Move to | When | Note the reason |
|---------|------|-----------------|
| **Researching** | Actively investigating, no root cause yet | — |
| **Pending** | Waiting on something | `Monitoring` / `Verifying-Fix` / `Code-Review` |

A queue full of "Assigned" is a queue nobody can trust. Status is how the next
person (or the next you) knows what's already handled.

## Step 5: Apply Staleness Rules

Sweep for tickets rotting past their last-updated date:

| Age since last update | Action |
|-----------------------|--------|
| 14–29 days ⚠️ | Nudge — add a status note or ping the owner |
| 30–89 days 🔴 | Close if resolved, or escalate if genuinely stuck |
| 90+ days 💀 | Mandatory review — close, or justify in writing why it's still open |

## Step 6: Parallel Investigation With Sub-Agents

**This is the key pattern.** When **3+ tickets** need real research, don't
investigate sequentially — spawn parallel sub-agents (Claude Code's Agent tool),
one per ticket or one per related cluster. A shift's backlog that takes an hour
serially finishes in minutes fanned out.

**Batching strategy:**
- **sev2 / impact-2** → one sub-agent each (they deserve full attention).
- **Alarm clusters** → one sub-agent per cluster of related alarms.
- **Low-priority** → batch 3–5 similar tickets into one sub-agent.

**Give each sub-agent a self-contained prompt** — it can't see your context:

```
Investigate TICKET-1234.
1. Fetch the ticket: description, correspondence, linked tickets.
2. Run the per-bucket investigation for its category (see below).
3. If it references a build/deploy, check your CI/CD system for that run.
4. Return a structured summary — nothing else:
   - id + title
   - status + severity/impact
   - root cause (if found) or leading hypothesis
   - next action
   - related/duplicate tickets
   - recommended priority: URGENT | MONITOR | LOW | CLOSE
```

**Hard constraint — sub-agents are READ-ONLY.** They fetch, read, and report.
**Only the main agent writes**: updates statuses, posts comments, records
decisions. This keeps writes serialized, auditable, and free of races between
agents editing the same ticket.

**After they return:**
1. **Cross-reference** the summaries — duplicate root causes, dependency chains
   (one ticket blocks another), contradictions between findings.
2. **Update the ledger in ONE pass** — statuses, comments, priorities together,
   so the queue ends in a consistent state.

**Fallback:** if sub-agents aren't available, do the same investigation
sequentially, highest priority first.

## Step 7: Per-Queue Summary

Close the loop with a short summary per queue:

- Total open
- Count by bucket (ALARM / ACTION-REQUIRED / COMPLIANCE / BUG / REQUEST)
- Highest impact open ticket
- Stalest ticket (and its age)
- **"All clear" callouts** — say explicitly when a queue has nothing urgent, so
  a clean queue reads as *checked*, not *ignored*.

## Tips

- **Breadth before depth.** Categorize and rank the whole backlog before you deep-dive any single ticket.
- **One bucket per ticket.** Overlap goes to the hardest deadline / biggest blast radius.
- **Status reflects reality.** Never leave a triaged ticket in "Assigned" — move it to Researching or Pending with a reason.
- **Fan out at 3+.** Sequential investigation is the bottleneck; parallel sub-agents are the whole point.
- **Sub-agents read, main agent writes.** Serialize every mutation through one actor.
- **Self-contained prompts.** A sub-agent knows only what you tell it — hand it the ticket ID and the exact output shape.
- **"All clear" is a result.** Reporting a quiet queue is how people know you actually looked.
