---
name: evidence-discipline
description: Ground every factual claim in a traceable source, label its evidence tier, and never present correlation as causation — for operational work where a confident wrong claim causes wrong action. Use when investigating incidents, root-causing, writing ticket comments / incident reports / handoffs, validating a claim, or any time an assertion will drive a real decision (resolving a sev, reassigning to another team, paging someone).
---

# Evidence Discipline

Operational conclusions drive real actions — resolving a sev-2, reassigning to a
dependency team, posting an outage report, paging a human. A wrong claim made
confidently causes wrong action. So every factual claim you make must be
traceable to a source. This is non-negotiable, and it's a discipline, not a
vibe: it changes *how* you write, not just how careful you feel.

## The Core Rule

**If you can't name where a claim came from, don't state it as fact.**

Every factual assertion — in chat, a ticket comment, an incident file, a handoff
— names its exact origin with a link where one exists: a specific ticket field,
a metric/log query you ran, a log line, a code path, a CR diff, a doc. "The
service is throttling" is not a claim; "`ReadThrottleEvents` = 1,240 over
14:00–14:15 on the `orders` table ([metric link])" is.

Prior findings, recurring patterns, and auto-generated summaries are **inputs to
help you root-cause — not facts**. They earn factual status only once you confirm
them against a primary source.

## Label the Evidence Tier

Be explicit about *what kind* of evidence backs each claim. Three tiers:

| Tier | What it is | Strength |
|------|-----------|----------|
| **Observed (primary)** | Raw data you read directly — the alarm payload, a metric you queried, a log line, the CR diff | Strongest |
| **Derived** | Numbers you computed from primary data — error rate, request counts, durations | Strong, if you show the arithmetic |
| **Inferred / secondary** | Auto-generated summaries, "similar tickets," pattern-matches against prior incidents | Correlation, **not proof** |

For **derived** claims, show the inputs and the math: `1,023 errors / 744,829
requests = 0.137%`. A number with no visible derivation is just an assertion.

For **inferred** claims, say so: "the auto-summary lists a co-occurring
deployment — a hypothesis, not confirmed."

## Never Present Correlation as Causation

A recurring pattern, a co-occurring deploy, or a tool's "related items" list is a
**hypothesis until confirmed**. Language encodes this:

- ✅ "likely / consistent with / pattern-matches / co-occurs with"
- ❌ "caused by / because of / due to" — unless you actually proved the mechanism

Note when the tooling itself made no attribution (e.g., the correlation engine
reported "related dependencies: 0"). Absence of a link is evidence too.

## Read Severity Tiers Before Attributing

Don't blame the loudest line. Distinguish:

- **ERROR vs WARN** — a WARN is often a handled fallback, not the fault.
- **Fault vs handled-fallback** — a caught-and-retried error may be invisible to customers.
- **Error-count vs error-rate** — 1,000 errors is scary until you see it's 0.01% of traffic.
- **Service errors vs sidecar/daemon noise** — infrastructure chatter isn't your service failing.

An ERROR-count alarm is not explained by pointing at an unrelated WARN spike.

## State What You Could NOT Verify

Gaps are part of the report, not something to paper over. If access is blocked
(permissions, portal-only data, expired credentials), say so plainly, log it, and
never let the gap silently promote a guess to a stated fact. Offer the path to
confirm ("would need read access to the prod metrics account to verify").

## When Stakes Are High, Go to the Primary Source

Before an irreversible or cross-team action — resolving a sev-2, reassigning to a
dependency team, posting to an outage channel, paging someone — prefer the actual
metric / log query / code over an auto-generated summary. If you can't reach the
primary source, **downgrade your confidence explicitly** and say why.

## When Asked to Validate

Map each claim → source → link, separated by tier (observed / derived /
inferred), and call out anything unverified:

```
Claim: The latency spike was caused by the 14:02 deploy.
- Observed: P90 rose 120ms → 1,400ms at 14:03 [metric link]
- Observed: deploy completed 14:02 [pipeline link]
- Inferred: timing correlation only — no code path traced yet
- Unverified: whether the deploy touched the latency-sensitive path
Verdict: consistent with a deploy-caused regression; NOT confirmed. Next step: diff the deploy.
```

Correct your own earlier overstatements when a closer read warrants it — an
honest correction beats a confident error.

## Tips

- **Name the source or don't say it.** This one habit prevents most bad
  operational calls.
- **Show the math on derived numbers.** "0.137%" with `1023/744829` beside it is
  checkable; without it, it's a guess in a lab coat.
- **"Likely," not "because,"** until you've traced the mechanism.
- **Auto-summaries are leads, not verdicts.** Great for pointing you at the
  primary source — never a substitute for reading it.
- **Log what you couldn't verify.** A named gap is useful; a silent one becomes
  someone else's wrong assumption.
- Pairs naturally with `incident-response` (high-stakes actions), `fact-check`
  (claim verification), and `deep-research` (source-grounded synthesis).
