---
name: postmortem
description: Write, facilitate, or review a blameless postmortem after an incident — timeline, quantified impact, root-cause analysis (5 whys / contributing factors), corrective action items with owners, and cross-team learnings. Use when the user asks to write up an incident, run a postmortem brainstorm, review someone's postmortem for quality, or draft corrective actions.
---

# Blameless Postmortem

A postmortem turns an incident into durable learning. Three modes, one discipline:

- **Author** — you write the postmortem for an incident you were part of.
- **Facilitator** — you run the brainstorm that produces it (ideally as an outside party who wasn't in the incident).
- **Reviewer** — you assess a draft for quality and decide whether it's good enough to publish.

## The Bar (what a good postmortem holds to)

1. **Blameless.** Fix the system that allowed the error — never blame a person. "Human error" is not a root cause; it's a prompt to ask what let the human err.
2. **Maximum learning.** The goal is understanding, not accountability theater.
3. **Actionable and cross-applicable.** Findings should help other teams, not just this one.
4. **Realistically scoped actions.** A short list of meaningful fixes beats a laundry list.
5. **Protects trust.** No customer PII, no confidential data in the write-up.

## Mental Model

An incident is rarely one mistake. It's a latent condition + a trigger + gaps in detection, prevention, and recovery all lining up. If you fix only the trigger, your *next* incident will look completely different but share the same systemic root. So you dig **deep** (why did this happen?) *and* **wide** (where else could this same root surface?).

---

# Authoring / Facilitating

## 1. Timeline

- **Minute-accurate**, and it starts at the **first trigger** (e.g. the bad deploy at 02:14), not when the team got paged. Starting at page-time hides the detection gap.
- **Separate time-to-detect from time-to-mitigate** — they're different metrics with different fixes.
- Any gap over ~10–15 minutes must be explained in the analysis.
- Use one unambiguous timezone (UTC is safest). Watch daylight-saving boundaries.

## 2. Impact — numbers, not adjectives

Drop "significant", "some", "a few". Quantify: **count × duration × magnitude.**

> Good: "From 03:30–10:22 UTC, order success dropped >25% for 46 minutes (est. 3,120 lost orders) and >10% for 311 minutes (est. 14,077 lost orders)."

> Weak: "A significant number of customers were affected for a while."

The test: **could a stranger prioritize this against other work using only your impact statement?** Describe impact in aggregate — never by named individual.

If you embed graphs: annotate the outage start/end, put the sampling interval in the title ("Failed connections per 10 min"), and don't rely on color alone (use distinct line shapes + alt text).

## 3. Root cause — the 5 Whys, deep then wide

- Each "why" must actually follow from the previous — no logical jumps.
- Don't stop at the trigger ("a bad deploy went out"). Reach the systemic gap ("no canary gate existed on this pipeline").
- **Reject "human error."** The system allowed it — fix the system.
- After going deep, do a **second pass going wide:** "Where else could this same root cause surface?" The first pass finds *the* cause; the second finds the *pattern*.

**5 Whys anti-patterns to avoid:**
- Stopping at environmental causes ("it was raining") — ask why rain was a problem.
- Ending only in good intentions ("we'll be more careful") — prescribe tooling that makes the error *impossible*, not promises.
- Ending only in giant long-term projects — find simpler short-term items too.
- Single-cause framing — if you only find what caused it and not what *else* was latent, those latent conditions cause the next incident.

**Narrative alternative** (when a linear 5-Why feels forced), build a four-part picture:
1. **What limited the damage** — sources of resilience (people, automation, process that kept it from being worse).
2. **What risks generalize** across teams — systemic patterns, not just this team's gap.
3. **What conditions existed at the start** — latent conditions that made it possible.
4. **Where mental models differed** — where participants thought the system worked differently. Those gaps are where the next incident hides.

## 4. Contributing factors

List *all* of them, not just the headline. For each, classify: was it a **detection** gap, a **prevention** gap, or a **mitigation-speed** gap? That classification points at the right kind of fix.

## 5. Corrective action items

This is where a postmortem earns its keep.

Every action item must be:
- **Owned** — a named owner and a due date, not "the team will consider." Confirm the owner has actually agreed.
- **Tracked** — linked to a ticket so other teams can follow and learn.
- **Scoped realistically** — completable in weeks, not a 6-month rearchitecture. Big efforts become a tracked backlog item *referenced* by the postmortem, not the action item itself. Aim ~45 days; treat any hard deadline as a ceiling, not a goal.
- **Meaningful & preventive** — it prevents recurrence, not busywork.
- **Right altitude** — a mechanism (alarm, gate, test, mandatory validation), never "be more careful."
- **On the right axis** — is it preventing the failure (reliability: redundancy, automated updates) or containing it (resiliency: retries, blast-radius limits, levers)? Teams conflate these; verify the fix matches what actually failed.

**Quantity is a signal.** Twelve action items usually means the root cause wasn't found — the team is scattered. Push: which 3 actually address the root cause?

Also worth asking: **is there one aggregate "healthy service" alarm** that would have caught this? If not, creating it may itself be a corrective action.

**Action item quality bar:**

| Weak | Strong |
|------|--------|
| "Improve monitoring" | "Add alarm on datastore throttle rate, missing-data=breaching — owner X, due MM/DD" |
| "Be more careful with deploys" | "Add one-box canary + 30-min bake gate to the pipeline — owner X, due MM/DD" |
| "Team will review process" | "Add pre-deploy schema-compat checklist item — owner X, due MM/DD" |
| "Fix the root cause" | "Make the eventTypes filter mandatory; reject unfiltered queries — owner X, due MM/DD" |

## 6. What went well & cross-team learnings

- **What went well** is not a participation trophy. What automation/process reduced duration or impact? What did people do under pressure worth replicating? If nothing went well, say so — that's also a finding.
- **Cross-team learnings:** is this a failure another team could hit? The transferable artifact is usually not the narrative — it's a reusable SOP, lint rule, runbook, or library patch another team can pick up directly.

## 7. Confidentiality

No PII, no confidential business data, no security-sensitive internals in the body. Impact in aggregate, never by named person or account.

---

# Reviewing a Postmortem (as senior reviewer)

You come in as an **objective outsider** who wasn't in the incident (avoid reviewing your own near-team's incidents — proximity bias dampens the finding).

Walk this checklist and produce a verdict:

1. **Timeline** — complete? minute-accurate? starts at the trigger, not the page? detect/mitigate split clear?
2. **Impact** — quantified (count/duration/magnitude), no adjectives?
3. **Root cause depth** — does the 5-Why reach a *systemic* gap, or stop at the trigger / "human error"? Did they also go *wide*?
4. **Contributing factors** — all listed, and categorized (detect/prevent/mitigate)?
5. **Action items** — per item: scoped to weeks? meaningful? owned + dated? linked to a ticket? right altitude (mechanism, not promise)? right axis (reliability vs resiliency)? Is the count suspiciously high?
6. **Cross-team learnings** — flagged, with a transferable artifact?
7. **Confidentiality** — anything that can't be published?
8. **Verdict** — approve, or send back with the specific gaps to close.

## Reviewer Phrasing (blameless in practice)

Steal these for written feedback:
- Opening a hard finding: *"Help me understand what led to [decision]. I want to be sure I'm not missing context."*
- Probing without accusation: *"I notice [gap]. What constraints or information were you working with at the time?"*
- Reframing to systems: *"The process failed here. What would have made it easier to catch this earlier?"*
- Separating team from gap: *"I see this as a gap in [tooling/visibility], not in [person/team]. Here's why…"*
- Delivering severity with respect: *"This is a serious finding. I want to acknowledge the pressure the team was under, and still make sure we close it."*

**Avoid:** "Why did [person] do X?" / "Who approved this?" (blame); "You clearly didn't think about…" (assumes intent); dropping a severe finding without acknowledging operational pressure first; using your reviewer status as a hammer.

---

## Output Formats

**Author mode:** Timeline → quantified Impact → 5 Whys (to systemic root) → all Contributing factors → Action items (owner + date + mechanism) → Cross-team learnings.

**Review mode:** Timeline assessment → Root-cause depth → Contributing factors → per-item Action-item review → Cross-team learnings → Confidentiality flags → Verdict.

## Tips
- **"Human error" is never the root cause** — it's the signal to ask what system allowed it.
- **Start the timeline at the trigger, not the page** — otherwise you erase the detection gap.
- **Numbers, not adjectives.** If a stranger can't prioritize from your impact statement, rewrite it.
- **Deep *and* wide.** The deep pass finds the cause; the wide pass finds the pattern that causes the next one.
- **Too many action items = root cause not found.** Focus on the 3 that prevent recurrence.
- **Mechanisms beat promises.** "Add a gate" prevents; "be more careful" defers.
- **The transferable artifact is the SOP/lint-rule/runbook, not the narrative.** That's what other teams actually adopt.
