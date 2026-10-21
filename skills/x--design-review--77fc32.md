---
name: design-review
description: Review a technical design/architecture doc against a rigorous rubric, or defend your own design under review. Use when the user shares a design doc, RFC, one-pager, or architecture proposal for critique, asks to "review this design", or asks for help responding to reviewer comments and "defending" their design decisions.
---

# Design Review & Defense

Two modes that share one rubric:

- **Mode A — Reviewing others' designs.** You're the reviewer. Find the problems that matter, at the right altitude, and phrase them so the author can act.
- **Mode B — Defending your own design.** You're the author. Anticipate objections, back decisions with rationale + tradeoffs, and contain scope.

Pick the mode from the request: "review this" / "give feedback" → A. "help me respond to comments" / "prepare to defend this" → B.

## Mental Model

A design review is not a bug hunt on prose. It is a test of *judgment*: does the design solve the right problem, with the simplest thing that could work, and does the author understand the tradeoffs they've made? Most weak designs fail on **problem framing** and **alternatives**, not on the technical details reviewers love to argue about. Review in that order.

The single most valuable question you can ask: **"What is the smallest change that solves the actual problem?"** Everything above that line needs justification.

---

# Mode A: Reviewing a Design

## The Review Rubric

Go top-to-bottom. Earlier categories gate later ones — don't debate scaling if the problem isn't real.

| Lens | Core question | Red flags |
|------|---------------|-----------|
| **Problem clarity** | What problem, for whom, how big? | Solution stated before problem; no quantification ("some customers"); bundles several unrelated problems |
| **Requirements & constraints** | What's actually required vs assumed? | Requirements phrased as solutions; missing SLA/latency/scale/budget numbers; implicit constraints |
| **Prior art** | Has this been solved already — here or elsewhere? | No survey of existing systems; rebuilds a capability that exists; parallel proposals not consolidated |
| **Alternatives considered** | Why this option and not the obvious others? | Only one option; strawman alternatives; no rejection criteria |
| **Architecture fit** | Is the logic in the right layer? Fewest moving parts? | New service where a library would do; extra hops/intermediaries with no added value; rendering layer doing orchestration |
| **Scalability** | What breaks at 10x? Where's the bottleneck? | Central proxy/aggregator with no scaling story; capacity sized to average not peak; no back-pressure |
| **Failure modes** | What happens when each dependency is slow/down? | No timeout/fallback per dependency; single point of failure in a fan-out; no blast-radius analysis |
| **Data** | Is data modeled by what it *is*, not its size? Freshness? | Magic-number thresholds switching behavior; static and dynamic data conflated; staleness ignored for cached/indexed data |
| **Contracts & boundaries** | What are the delivery/durability guarantees? | Undefined "at-least-once vs exactly-once"; single-item API that will need batch; create path with no delete path |
| **Security** | AuthN/AuthZ, data classification, secrets, blast radius | Relies on network isolation alone (no data-layer authz); PII without encryption story; secrets handling unstated |
| **Operability** | Can you run it? Monitor it? Roll it back? | No metrics/alarms named; no rollback; config that can break prod with no review rigor |
| **Cost** | Is the solution proportional to the problem? | Production-grade infra for an A/B test; cache with unknown hit rate; imposes engineering-hours on other teams without quantifying |
| **Testing & validation** | How do we know it works before we build it? | No offline eval before standing up infra; hypothesis untested; failure paths untested |

## High-Signal Review Moves

These catch the most consequential problems:

- **Decompose the problem.** Is this one problem or several bundled? Independent problems deserve independent solutions that ship separately. Often "Phase 1: unblock, Phase 2: build" beats one monolith.
- **Separate requirement from solution.** "Summary-first UX" is a solution; "customer can find the problem item quickly" is the requirement. Review against the requirement.
- **Quantify before solving.** "What % of traffic hits this?" Investment must match impact — don't build for 0.1% of traffic unknowingly.
- **Challenge existence.** Before accepting a redesign, ask whether the thing should exist at all, and whether the *new* version fundamentally changes behavior or just moves code around.
- **Fix-before-bypass.** Can the existing capability be improved instead of built around? Divergent implementations become permanent maintenance debt.
- **Minimize new components.** Prefer reduce > compress > externalize. Burden of proof is on the proposer to justify new infrastructure. Prefer a library over a service when you can.
- **Follow the full call chain.** A change in one layer often forces changes in layers 2, 3, 4. Trace downstream before blessing a deviation from established patterns.
- **Stress-test constraints.** "What changes if the SLA were 1s? 100ms?" Varying the key constraint exposes hidden assumptions.
- **Vary the worst-case consumer.** Design for the hardest consumption pattern (the one needing *all* the data), not the average one.
- **Temporary → permanent.** Every "temporary" workaround needs a sunset mechanism with an owner and date, or it becomes permanent.
- **Watch presentation bias.** Why is one option colored red and another green? Why compare against *that* baseline? Framing can smuggle in conclusions.

## Altitude-Appropriate Feedback

Match the depth of feedback to the maturity of the decision and the seniority of the venue. Not every comment deserves equal weight — say which is which.

| Altitude | When | Example |
|----------|------|---------|
| **Blocking / one-way door** | Decision is hard to reverse and wrong | "This makes the event contract single-item; retrofitting batch later is a breaking change. Design `PublishEvents` now." |
| **Significant** | Real risk, author should address or consciously accept | "No per-dependency timeout — one slow provider blocks all results. Add fallback." |
| **Suggestion** | Would improve it; author's call | "Consider extracting the retry schedule into a named policy." |
| **Question** | You need context before judging | "What's the cache hit rate? If it's low, the cache may be net cost." |

Rules for feedback that lands:
- **Challenge ideas, not people.** "I'm not sure this handles X" — not "you didn't think about X."
- **Lead with the assumption you're testing**, so the author can correct your premise instead of defending a conclusion.
- **Prefer the smallest reframing** that unblocks: give the "Phase 1" that lets them proceed while the bigger question stays open.
- **Create room for junior voices.** In a review with mixed seniority, ask the quiet people what concerns them before you deliver your own verdict.

## Review Output

1. **Problem decomposition** — the N independent problems you see.
2. **Minimum viable path** — fewest changes to unblock the core use case.
3. **Findings by lens** — each tagged blocking / significant / suggestion / question.
4. **Prior art** — what exists that should be reused.
5. **Open questions** — what the doc doesn't address but should.

---

# Mode B: Defending Your Design

Being reviewed well is a skill. The goal isn't to "win" — it's to surface the real tradeoffs so the decision is sound and durable.

## Preparation

Before the review:
1. **Anticipate the top 3–5 objections.** For each, prepare a response.
2. **Gather production precedent.** What existing, running system proves your tradeoff works? Evidence beats theory.
3. **Have the numbers ready.** Latency, volume, cost, team count, hit rate. Numbers end debates opinions can't.
4. **State scope explicitly.** What's in, what's out, and *why*. Undefended narrow scope reads as an oversight.
5. **Build an alternatives table.** Options considered, and the rejection criteria — not just the winner.

## Defense Patterns

| Reviewer move | Your response |
|---------------|---------------|
| Factual challenge ("this won't scale") | Cite data or a production precedent that already does it |
| Scope expansion ("what about channel X?") | Acknowledge, then contain: "Intentionally out — X is 5% of volume; tracked separately." |
| "Why not approach X?" | Show the alternatives table with rejection criteria |
| Architecture challenge | Show minimum hops and the downstream consumer/query patterns you designed for |
| Uncertainty probe | Separate confidence levels: "Data model is locked; caching is a hypothesis we'll validate in beta." |

Core techniques:
- **Assumption-first.** "My assumption is X; if that's wrong, the design changes to Y." Transparent reasoning invites correction of the *premise*, not a fight over the conclusion.
- **Quantify the tradeoff.** "Option A adds 200ms P99 for 3% of calls; Option B is 50ms at 95% coverage." Show the math.
- **Acknowledge and redirect.** When a valid concern is out of scope: "Great point — tracked as a follow-up. For this doc we're focused on the core path."
- **Show your work on alternatives.** Present what you rejected and why. It preempts half the questions.
- **Leverage what you get for free.** "Using version control gives us history, diffs, and authorship — a custom registry would rebuild all of that."
- **Don't defer out of hierarchy.** If you think a senior reviewer is wrong, state your view with evidence. Deferring silently produces bad designs.

## Defense Output

1. **Anticipated objections** — top 3–5.
2. **Prepared responses** — evidence, numbers, precedent per objection.
3. **Scope statement** — explicit in/out with justification.
4. **Alternatives table** — considered and rejected, with criteria.
5. **Parking lot** — valid concerns to acknowledge and defer.

## Tips

- **Framing before details.** A technically flawless solution to the wrong problem still fails review.
- **The smallest correct diff is the baseline.** Everything above it needs a reason.
- **Quantify or it doesn't count.** "% of traffic", "P99", "hit rate" turn opinion into decision.
- **Every create needs a delete; every temporary needs a sunset.** Lifecycle completeness is where designs quietly rot.
- **Design for the worst-case consumer,** not the average one.
- **As the author, make your assumptions attackable.** State them first — it's faster than defending conclusions.
- **Separate what's locked from what's a hypothesis.** Reviewers calibrate their scrutiny to your stated confidence.
