---
name: incident-response
description: Handle a live high-severity incident (sev1/sev2) as on-call — from the first alarm to resolution. Use when you're paged for a sev1/sev2, an alarm just fired with customer impact, you need to quantify impact, link related tickets, post an outage update, or write a resolution summary before resolving. This is the real-time complement to the `postmortem` skill (after-action) and `oncall-context-system` skill (the file-based ledger and logs).
---

# Incident Response

Live handling of a high-severity incident, from page to resolved. This skill is
the **real-time** playbook; two siblings pick up around it:

- **`oncall-context-system`** — where you keep the ledger, the daily log, and the per-incident file this skill writes into.
- **`postmortem`** — the after-action write-up you produce once the incident is closed.
- **`alarm-correlation`** — how to cluster a burst of alarms and link sev3 symptoms to a sev2 (used in linking + wrap-up below).

Tool-agnostic: "the ticket" means your ticketing system, "recent deployments"
means your CI/CD system, "the dashboard" means your metrics system, "the outage
channel" means your incident/outage comms channel.

## Mental Model

An alarm is a **symptom with a clock running**. Your job in order: stop the
bleeding, quantify who's bleeding, and leave a trail precise enough that someone
else could take over mid-incident. Two reflexes separate fast resolutions from
long ones:

1. **Check recent deployments and change records FIRST.** A large share of
   sev2s are self-inflicted by a deploy. If the alarm's first-breach time lines
   up with a rollout, rollback is usually the fastest fix — faster than
   diagnosing the code.
2. **Quantify impact in real numbers, always.** "Degraded" is not an answer.
   Every high-sev incident must end with *how many* and *how bad*.

---

## New sev2 Checklist

Run this top-to-bottom on a fresh page:

1. **Acknowledge / check in** on the ticket so others know it's owned.
2. **Set status** → `Investigating` (or your equivalent of "actively working").
3. **Add it to the ledger** — a row in your on-call incidents table (see `oncall-context-system`).
4. **Log it** — timestamped entry: what fired, when, first hypothesis.
5. **Check recent deployments + change records FIRST.** Compare the alarm's
   first-breach timestamp against recent rollout times in your CI/CD system and
   any change records in the window. **Deployment-correlated alarm → strongly
   consider rollback before deep diagnosis.**
6. **Investigate via the service runbook** — follow its ranked-likelihood
   investigation, not a cold read of logs.
7. **Quantify customer impact** with real numbers (next section) — this is not optional.
8. **Open a per-incident file** (see `oncall-context-system`) if it's non-trivial.

## Impact Quantification (the recurring gotcha)

**Never resolve with "it was degraded."** Answer two questions to single-digit
accuracy:

1. **How many?** Customers / requests affected — traffic counts **summed across
   the whole incident window**, not a single spot reading.
2. **How bad?** What degraded experience did they actually see — latency
   baseline vs. spike, error rate, and *what broke visually or functionally*.

Get these from your metrics system: pull the affected metric over the incident
window (first-breach → recovery), sum the impacted requests, and compare against
the healthy baseline just before first-breach.

**Format example:**

```
Customer Impact: ~12,400 checkout requests over 34 min (14:02–14:36 UTC).
Error rate rose from a 0.1% baseline to 18% peak; P90 latency 220ms → 3.1s.
Customers saw spinning "Place order" buttons and intermittent 5xx error pages;
~2,200 orders failed outright and had to be retried.
```

If you genuinely cannot measure one axis, say so explicitly and give a bounded
estimate ("no per-request metric; bounded by ≤ total traffic of ~40k in window")
— an honest bound beats a vague adjective.

---

## Primary / Secondary Linking

When multiple tickets share **one** root cause, don't run parallel
investigations. Designate a single tracker:

- **PRIMARY TRACKER** = the ticket **closest to the root cause**. The full
  investigation, timeline, and resolution summary live here.
- **Secondaries** = comment pointing to the primary; no separate investigation.
- **One incident file per primary** — secondaries reference it, they don't get their own.
- **Related sev3s** that fired in the same window → link to the primary, set to
  `Pending`/`Monitoring`, and **resolve as duplicates** when the root cause
  resolves. (See `alarm-correlation` for clustering the swarm.)

## Linking a NEW sev2 to an EXISTING Incident

Co-timing is **not** proof of relation. Before you fold a new sev2 into an
existing incident:

1. **Confirm the shared root cause first.** Research the dependency path — does
   the existing incident's root cause actually explain this new alarm? Don't
   assume "fired at the same time" = "same cause."
2. If confirmed, run an **abbreviated checklist**:
   - Skip re-investigation and re-quantification — the primary already has them.
   - **Confirm the dependency path** (how this symptom traces to the known root cause).
   - **Add it to the existing incident file** as a linked symptom.
   - Set status to `Pending`/`Monitoring`, linked to the primary.

**What NOT to do when linking:**

- ❌ Don't create a separate incident file.
- ❌ Don't post a separate outage update (fold it into the existing thread).
- ❌ Don't leave it sitting in `Assigned` — link it or it looks unhandled.
- ❌ Don't re-quantify the same impact twice — point to the primary's numbers.

---

## Mandatory High-Severity Resolution Summary

**Hard gate: you may not resolve ANY sev1/sev2 without answering all six fields
— even a false alarm** (a false alarm still answers every field; that's how you
prove it was false). Mirror this summary into the incident file.

| Field | Answer |
|-------|--------|
| **Customer Impacting?** | Y / N |
| **Broader-incident related?** | Y / N (linked to a primary tracker? which?) |
| **Issue Description** | What actually broke, in one or two plain sentences |
| **Customer Impact** | **Quantified** — how many + how bad (see above), or "None (false alarm)" |
| **How resolved** | Rollback / config revert / dependency recovered / no action needed / etc. |
| **Auto-cut?** | Alarm-generated vs. human-raised |

If any field is blank, you're not ready to resolve.

## Wrap-Up Checklist

Before you consider the incident closed:

1. **Final ticket sweep** across every queue for the incident window — **new
   sev3s often fire late**, after you thought it was over.
2. **Batch-link + resolve** related sev3s against the primary (resolve as duplicates).
3. **Resolve the primary** with the full resolution summary attached.
4. **Update the ledger, incident file, deadlines, and daily log** (see `oncall-context-system`).
5. **Create follow-up tasks** if the incident was recurring or systemic — a
   permanent fix, a guardrail, an alarm tuning.
6. **Update the runbook** with what you learned — new symptom, faster shortcut,
   undocumented dependency (see the `runbook-authoring` skill).
7. **Consider a postmortem** for anything customer-impacting or systemic (see `postmortem`).

---

## Outage Communications

**When to post:** any **sev2+ with confirmed customer impact**. If impact is
confirmed, communicate — don't wait until you've resolved it.

**Where:** your incident/outage channel. Post the initial update as a top-level
message; **post every subsequent update as a threaded reply** so the whole
incident reads as one thread.

**Status progression:** `Ongoing` → `Mitigated` → `Resolved`. Update the status
line on each reply.

**Structured update format:**

```
[Status: Ongoing | Mitigated | Resolved]

Summary:         One line — what's broken and who's affected.
Description:     What's happening in a bit more detail.
Current Status:  Ongoing / Mitigated / Resolved + what you're doing now.
Systems Impacted: Which services/components.
Regions:         Which regions/stages.
Timeline:        HH:MM first breach · HH:MM detected · HH:MM mitigated (UTC).
Root Cause:      Known cause, or "under investigation".
Customer Impact: Quantified — how many + how bad.
Ticket:          TICKET-1234 (primary tracker)

Posted by <your on-call> (AI-assisted)
```

Sign updates as AI-assisted so readers know an assistant drafted them. Keep the
quantified impact in **every** update — leadership reads the impact line first.

## Tips

- **Check deployments and change records before you read a single log line.** A deploy-correlated alarm is a rollback, not a whodunit.
- **"Degraded" is not an answer.** Every high-sev incident ends with *how many* and *how bad*, in numbers, summed across the window.
- **One root cause, one primary tracker.** Full investigation on the primary; secondaries just point to it.
- **Co-timing ≠ causation.** Confirm the dependency path before folding a new sev2 into an existing incident.
- **The resolution summary is a gate, not paperwork.** No sev1/sev2 resolves with a blank field — false alarms included.
- **Sweep the queues again at the end.** Late sev3s are the ones that reopen a "closed" incident.
- **Confirmed impact → communicate now.** Don't wait for resolution to post the first outage update.
