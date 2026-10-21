---
name: runbook-authoring
description: Write and maintain high-quality, agent-consumable service runbooks — the operational docs an on-call (human or AI) reads mid-incident. Use when creating a runbook for a service, adding an alarm-definition or investigation section, upgrading a stale/skeleton runbook, or capturing what you learned from an incident. Emphasizes ranked-likelihood investigation and agent-routing metadata so a ticket-handler can pattern-match against it.
---

# Runbook Authoring

A runbook is the doc an on-call opens at 3am with a clock running. The bar here
is higher than "readable prose": the whole point is a runbook an **AI agent can
pattern-match against** — structured so a ticket-handler can auto-route to it and
an investigator can stop at the first matching row, not read 30 minutes of text.

Runbooks are **how-to guides** in [Diátaxis](https://diataxis.fr/) terms —
goal-oriented, assume-you-know-the-basics, get-you-through-a-task. Not tutorials,
not explanations. Keep them that way.

## SOP vs. Runbook

| | **SOP** | **Runbook** |
|--|---------|-------------|
| Scope | One known, recurring issue | A service's whole investigative surface |
| Shape | Linear: symptom → steps → resolution | Branching: many symptoms, ranked hypotheses |
| When | You've seen this exact thing before | You're diagnosing from first principles |
| Where it lives | As a **triage shortcut inside** the runbook | The document itself |

SOPs are the fast paths *inside* a runbook. When a recurring issue gets its own
linear fix, capture it as a triage shortcut, not a separate doc.

## Required Sections (in order)

1. **Header block** — links to wiki/dashboards/pipeline/owning team. One place, at the top.
2. **Agent Routing metadata** — see below. Put it high so routing logic finds it.
3. **Overview** — what the service does, **who its customers are**, where it fits in the system. Be specific; "handles requests" helps no one.
4. **Key Packages / components** — the code that matters, with locations.
5. **Alarms** — the critical section. One **Alarm Definition block** per alarm.
6. **Dependencies table** — dependency → owning team → how to reach them.
7. **Logs** — where they are, which query answers what, 3–5 common queries.
8. **Deployment** — how to deploy, roll back, and emergency-patch.
9. **Resolution Criteria** — checklist of exit conditions (when is it *actually* over).
10. **Changelog** — append-only, dated.

## Alarm Definition Block (per alarm)

The single most valuable section for an on-call. For each alarm:

| Field | Content |
|-------|---------|
| **Pattern** | Glob/regex matching the alarm name(s) — so a handler can match a ticket to this block |
| **Metric** | What's measured (error rate, P99 latency, queue depth) |
| **Threshold** | The exact number that trips it |
| **Evaluation Period** | Over what window / how many datapoints |
| **Severity** | sev2 / sev3 |
| **Triggers When** | **Human-readable business meaning — the MOST important field.** What real-world condition this represents |
| **Definition link** | Link to the alarm-definition code/config |

`Triggers When` is what turns a cryptic metric into an actionable signal:

```
Alarm: OrderApi-P99Latency-High
Pattern:            OrderApi-P99Latency-*
Metric:             P99 latency, /placeOrder
Threshold:          > 2000ms
Evaluation Period:  3 of 5 datapoints, 1-min periods
Severity:           sev2
Triggers When:      Checkout is slow enough that customers see spinners and
                    start abandoning carts. Usually means the pricing dependency
                    is degraded or the DB connection pool is saturated.
Definition:         <link to alarm-as-code>
```

## Ranked-Likelihood Investigation (the key idea)

**Do not write a flat numbered list of things to check.** Write a table ranked
by likelihood so the reader goes top-down and **stops at the first match**. This
is what turns a 30-minute investigation into a 2-minute pattern-match — and it's
exactly the structure an AI agent consumes best.

| Likelihood | Symptom Pattern | Root Cause | Action |
|------------|-----------------|------------|--------|
| **Most likely** | Alarm fired within ~15 min of a deploy | Bad rollout | Check recent deploys; **roll back** if correlated |
| **Likely** | Latency + errors on one dependency's calls | Dependency degraded | Check dependency dashboard; page its owner (see Dependencies) |
| **Less likely** | Gradual latency climb, no deploy, rising traffic | Capacity / pool saturation | Check connection-pool + host metrics; scale out |
| **Noise** | Single datapoint, single host, self-recovered | Transient blip | Monitor; don't page. Resolve if not recurring |

Order matters: put the cause you'd bet on first. The reader shouldn't have to
read row 4 to rule out row 1.

## Agent Routing Metadata

So a ticket-handler agent can auto-route an incoming ticket to the right runbook.
List the signals, most-precise first; the agent matches **exact → partial →
keyword → alarm-name → fallback**:

```
## Agent Routing
Category patterns:   <your category/classification codes for this service>
Title keywords:      order, checkout, placeOrder, cart-submit
Queues / groups:     <the on-call queues that own this service>
Alarm-name patterns: OrderApi-*, Checkout-*
Fallback:            If only keywords match and severity is sev2, route here and flag low-confidence.
```

## Sections That Elevate Quality

- **Dependency deep-dives** — for critical dependencies: a dependency-chain
  diagram, a "how to confirm it's *this* dependency" decision guide, and current
  team contacts. This is what lets an on-call trace a downstream failure fast.
- **Clients / downstream consumers** — who calls you, so you know the **blast
  radius** when you're the one that's broken.
- **Throttling / capacity config** — limits, quotas, scaling knobs, and where they're set.
- **Known recurring patterns** — the SOP-style triage shortcuts for issues you've seen before.

## Updating During On-Call

Update the runbook **while the context is fresh** — right after you resolve, not
"later." Update when you hit:

- A new alarm pattern not yet documented.
- An undocumented dependency chain you had to trace.
- A faster shortcut than the runbook currently describes.
- A recurring pattern worth a triage shortcut.
- Ownership you had to rediscover (fix the stale contact).
- Useful log queries you built during the investigation.

After resolving an incident, add a dated entry:

```
### Recent incident (2026-07)
Symptom:      OrderApi-P99Latency-High, sev2, ~12k requests over 34 min.
Root cause:   Pricing dependency deploy introduced a 3s timeout path.
How it was found:  Alarm first-breach lined up with the pricing rollout time —
                   confirmed on their dashboard before reading any OrderApi logs.
Lesson:       Add pricing deploy times to the "Most likely" investigation row.
```

**`How it was found` is mandatory** — the *method* is more reusable than the
cause. Then: append to the section, add a Changelog line, and commit.

## Quality Tiers

| Tier | Bar |
|------|-----|
| **Tier 1 — Battle-tested** | All required sections + 3+ alarms with full definition blocks + ranked-likelihood investigation + recent-incident entries + at least one dependency deep-dive + agent routing + updated in the last 30 days |
| **Tier 2 — Functional** | Required sections present + at least one alarm definition + a basic investigation section; may lack deep-dives, recent incidents, or routing |
| **Tier 3 — Skeleton** | Header + overview + a list of alarms, but no definitions, no ranked investigation, no routing |

**Upgrade 3 → 2:** add an Alarm Definition block (with `Triggers When`) for each
alarm, and convert any flat check-list into a ranked-likelihood table.

**Upgrade 2 → 1:** add Agent Routing metadata, a dependency deep-dive for your
most critical dependency, and start logging recent-incident entries (with `How
it was found`) as they happen — then keep it under 30 days stale.

## Anti-Patterns

| Anti-pattern | Fix |
|--------------|-----|
| "Check the dashboard" with no *what to look for* | Name the metric, the healthy baseline, and the threshold |
| Linking a wiki page **as** the step | Wikis go stale — inline the critical steps; link for depth only |
| Recent incident with no `How it was found` | The method is the reusable part — always capture it |
| Stale ownership ("ping Team X" that moved) | Confirm current owner on update |
| Vague thresholds ("wait a while", "if it's high") | ">30 min", "> 2000ms" — concrete numbers |
| Flat numbered investigation list | Ranked-likelihood table, most-likely first |
| No changelog | Append-only, dated — so readers trust its freshness |
| Alarms listed with no definition blocks | Every alarm gets Metric + Threshold + `Triggers When` |

## Tips

- **Write for an agent pattern-matching at 3am.** Ranked tables and alarm patterns beat prose every time.
- **`Triggers When` is the highest-value field you'll write** — it turns a metric into a decision.
- **Rank hypotheses; don't list them.** The reader should stop at the first match, not read all ten.
- **Capture `How it was found`, not just the cause.** The method generalizes to the next incident; the cause won't.
- **Inline the critical steps** — a runbook that's just links is a stale runbook waiting to happen.
- **Concrete thresholds only.** "A while" and "high" are not operational instructions.
- **Update while it's fresh.** The best time to improve a runbook is right after it just failed you.
