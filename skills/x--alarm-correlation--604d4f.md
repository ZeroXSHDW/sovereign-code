---
name: alarm-correlation
description: Correlate a burst of monitoring alarms into a small number of root causes instead of chasing each one alone. Use when multiple alarm tickets fire at once, an alarm spans regions or services, you need to link sev3 symptoms to a sev2 incident, or you're tracing a downstream dependency failure. Provides extraction, clustering, severity, and dashboard drill-down methods.
---

# Alarm Correlation

Alarms rarely fire alone. Ten tickets are often **one** incident seen from ten
angles. This playbook turns a wall of alarms into a handful of root causes so you
fix the cause, not each symptom. Tool-agnostic — "query the dashboard" means your
metrics/monitoring system (CloudWatch is a fine public example).

## Mental Model

An alarm is a **symptom at a point in the system**. Correlation reconstructs the
underlying failure from the pattern of symptoms: *what do these alarms share, and
what single thing upstream would explain all of them?* Group first, diagnose the
group — never triage identical alarms as unrelated one-offs.

## Step 1: Extract Metadata From Each Alarm

Normalize every alarm ticket into the same fields so they're comparable:

| Field | Examples |
|-------|----------|
| **Service** | the service that owns the alarm |
| **Component** | queue, endpoint, table, worker |
| **Alarm type** | DLQ, Latency (P90–P99), Availability, Throttles, Fault-Count, Error |
| **Region** | which region/stage fired |
| **Severity** | sev2 / sev3, impact level |

## Step 2: Cluster Related Alarms

**Rule:** group alarms that share **(Service + Component)** but differ by **region**
or **alarm type**. The shape of a cluster tells you the class of failure:

| Pattern | What it means |
|---------|---------------|
| Same alarm across **multiple regions** | Systemic — a code or config change, *not* regional infra |
| **Multiple alarm types** on one component | Cascading failure / degradation (latency → errors → availability) |
| **Single region + single alarm** | Likely transient — watch before escalating |
| Same alarm **recurring across tickets** over time | Chronic — needs a real root-cause fix, not another restart |

## Step 3: Assess Severity by Pattern

| Pattern | Assessment |
|---------|------------|
| DLQ, single region | Low — likely transient |
| DLQ, **3+ regions** | High — systemic, treat as one incident |
| Latency + Error, same service | High — active degradation |
| DB read-throttles | Medium — capacity/scaling issue |
| Availability drop | High — direct customer impact |

## Step 4: Correlate Across Services

Alarms in **different queues** can trace to **one shared backend**. Before you
open N investigations, ask: could these be downstream symptoms of a single
upstream failure? Link the downstream-symptom alarms to the upstream root-cause
ticket and investigate the cause once.

## Step 5: Link sev3 Alarms to a sev2 Incident

During an active sev2, a swarm of sev3s is usually collateral, not new problems:

1. Search for sev3 alarms that fired **in the same time window** across your queues.
2. Treat them as **downstream symptoms** of the sev2 until proven otherwise.
3. **Link** each to the primary incident tracker; set to **Pending / Monitoring**.
4. When the root cause resolves, **resolve them as duplicates** in one sweep.

This keeps the sev2 as the single source of truth and stops five people from
separately investigating the same outage.

## Step 6: Trace Cross-Team Dependencies

When your alarms point *downstream* — into a dependency you don't own — trace the
full chain to the root-cause service and its owning team:

- **Search by service-name keywords**, not just category codes — codes miss related alarms.
- **Look for aggregate / roll-up alarms** — they signal a widespread issue, not a one-off.
- **Don't trust stale ownership docs** — confirm current ownership before paging a team.
- **Build a dependency-chain map** so the blast radius is explicit:

```
Customer → ServiceA → ServiceB → DependencyC (root cause)
```

## Step 7: Dashboard Drill-Down

Generic method for tracing latency/errors through a gateway or service mesh from a
top-level dashboard down to the failing call:

1. **Start at the top-level dashboard** — identify the slowest or most-errored contributor.
2. **Drill into that contributor** — one level down the call graph.
3. **Check the error-path breakdown** — pinpoint the exact failing call/operation/field.
4. **Trace to the root-cause downstream service** — follow the failing call to its owner.
5. **Quantify client impact** — how many requests/customers, over what window.

> Always **confirm region/stage before querying** — the right graph in the wrong
> region tells you nothing. Start with **wide time ranges, stats-only** to see the
> shape, then **narrow** once you've found the window.

## Tips

- **Group first, diagnose the group.** Identical alarms treated as one-offs waste the whole shift.
- **Multi-region = systemic.** The same alarm everywhere is a code/config change, not regional infra.
- **Multiple types, one component = cascade.** Find the *first* symptom in the chain; the rest follow.
- **sev3 swarm during a sev2 = symptoms.** Link to the primary tracker and resolve as duplicates on fix.
- **Trace to the owner, don't trust the doc.** Ownership drifts; confirm before you page.
- **Confirm region/stage first, then narrow the time range.** Wide-and-stats-only before deep-and-detailed.
