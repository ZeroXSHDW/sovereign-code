---
name: technical-writing
description: Write clear long-form technical and business documents — design docs, proposals, decision docs, one-pagers, narratives, and PR/FAQ-style docs. Use when drafting or restructuring a design doc, writing a proposal or strategy doc, converting notes into a narrative, or calibrating a document before it ships to leadership.
---

# Technical & Business Writing

Long-form writing is a decision-making tool, not a formatting exercise. A good
document makes the right decision easy to reach: it leads with the point, backs
claims with data, and is calibrated to exactly one reader making exactly one
decision. This skill covers the structure, the calibration mental models, and a
systematic pre-ship review pass.

## 1. Calibrate Before You Write

Answer three questions first. They determine everything else.

| Question | Why it matters |
|----------|----------------|
| **Who is the reader?** | An executive wants outcomes and risk; a principal engineer wants tradeoffs and alternatives; a teammate wants how-to detail. Wrong altitude = wasted document. |
| **What decision does this drive?** | If the doc doesn't move a decision forward (approve, fund, choose, unblock), cut it or reframe it until it does. |
| **What altitude?** | Match detail to the reader. Strip implementation detail (method names, field names, algorithms) for leadership; keep concrete *scenarios*. Add depth for engineers. |

Tone and length follow from the reader:

| Reader | Focus | Length |
|--------|-------|--------|
| Executive / director | Business outcome, customer impact, risk, the ask | ~1 page |
| Principal / staff engineer | Technical depth, tradeoffs, alternatives rejected | As long as the argument needs |
| Team | Implementation detail, how-to, gotchas | As detailed as useful |
| Partner / away team | Context they lack, a clear ask, timeline | Respect their time |

## 2. Structure: Lead With the Point

Put the conclusion first, evidence after. Readers should get ~80% from the
headers and first sentences alone. A durable general structure:

```
## Problem        — 1-2 sentences, from the reader's/customer's point of view
## Proposal       — the recommendation and the mechanism (what + why), stated up front
## Alternatives   — what else you considered and why you rejected each
## Risks          — what could go wrong, and the mitigation/rollback for each
## Ask            — the specific decision, owner, and date you need
```

Variants worth knowing:

- **Lightweight decision doc** (reversible / two-way-door choices): Problem →
  Assumptions → Constraints → Proposed approach → Alternatives rejected → Key
  risks → Rollback plan. Use for internal APIs, sequencing, feature-flagged
  experiments. *Not* for security boundaries, data contracts, or platform
  choices — those warrant a full design doc.
- **Investigation summary**: Finding (one sentence) → Evidence (2-3 data points)
  → Impact (who/what) → Recommendation → Sources.
- **Narrative / long-form business doc**: prose, not bullets. State the problem
  from the customer's experience, work toward the proposal, address the obvious
  objections inline. Keep a tight FAQ at the end for the predictable questions.
- **PR/FAQ-style doc**: write the "announcement" first (what the reader would
  see if this shipped and succeeded), then an FAQ that answers the hard
  questions a skeptic would ask. Forces you to work backwards from the outcome.

## 3. Writing Principles

1. **Lead with the point.** Conclusion first, then support. Never bury the ask.
2. **Data, not adjectives.** "Reduced p90 latency from 4.5s to 2.0s" beats
   "significantly faster." Words like *fast, scalable, robust* mean nothing
   without a number.
3. **Active voice.** "We cut errors 50%" — not "errors were reduced." Passive
   voice hides who is accountable.
4. **Every sentence earns its place.** Cut redundancy; each sentence should add
   new information.
5. **Expand jargon on first use.** Spell out an acronym the first time, then use
   the short form. Verify any term or system name before you define it — don't
   infer meaning from the name.
6. **Structure for scanning.** Headers, short paragraphs (3-4 sentences),
   inline links with descriptive text, numbers over words ("3 services," not
   "several").
7. **Keep lists short.** If a list runs long, it's probably two lists or a
   table. Bullets for reference material; prose for experience and argument;
   tables only when a table genuinely serves the reader.

**A metric statement worth copying** (states baseline, target, date, method, and
mechanism — so it's defensible):

> "P90 latency will drop from 4.5s to 2.0s by June 30, measured by service
> dashboards, because we split the query into parallel per-type calls."

## 4. Calibration Mental Models

These are the reflexes that separate a shippable doc from a draft. Apply them
proactively.

1. **Source-skepticism on every hard number.** Any precise figure ("8-week
   onboarding cost," "~3.5%") triggers "where did this come from?" If you can't
   source it to a real measurement, soften to a defensible range or cut it. *A
   specific number invites a specific question* — never ship one you can't
   defend.
2. **Cross-reference integrity is your job, not the reader's.** When you move or
   delete a section, hunt down every "see section X" that pointed to it. A dead
   cross-reference is the most embarrassing reviewer-catchable error.
3. **One framing per concept, propagated everywhere.** If you reframe an idea
   (e.g. privacy from "user control" to "compliance"), change it in *every*
   place it appears — summary, body, FAQ. Inconsistent framing reads as two
   authors.
4. **Frame scope as by-design, but only when true.** A targeted result is
   intended scope, not a miss — "serves exactly the population it targets," not
   "only reaches 3%." Don't launder a genuine miss, though; a reflections
   section still needs one honest shortfall.
5. **Concrete examples, plain language, no implementation.** Ground every
   abstract capability in a recognizable scenario, but strip method names, field
   names, and algorithm names for non-engineering readers. Show *what it does*,
   never *how it's coded*.
6. **Compress relentlessly.** Default motion: prose → FAQ → fewer FAQs → table.
   If three questions cover one idea, merge them. Length is a cost, not a virtue.
7. **Explore the format before committing.** Ask "would a table serve this
   better?" before writing into a structure. When useful, offer a granular and a
   light version with a recommendation, rather than silently picking one.
8. **Customer-problem-first, neutral headings.** Lead each problem with what the
   reader/customer experiences, then the cause. Keep headings factual ("Stored
   data carries no confidence signal"), never self-flagellating.
9. **Name things for the framing you want.** A rename carries strategy — the
   headline noun should embody the value, not the plumbing.
10. **Prose must match any diagram.** If a section pairs prose with a diagram,
    the prose references exactly the nodes the diagram draws — same names, no
    extras, no omissions. Re-read both side by side after any edit; this is the
    most common silent drift in architecture docs.

## 5. The Pre-Ship Review Pass

Before sharing, read the whole doc end to end and scan these axes at once.
Report (or fix) findings grouped by severity.

**A. Structural integrity**
- Section numbering runs 1,2,3,4…? A skip means a deletion — renumber and fix
  cross-refs.
- Every "see section X" / "Appendix Y" still resolves.
- No empty stubs (a heading with no body, a dropped diagram placeholder).

**B. Number & metric consistency**
- A headline metric reads identically in every location it appears.
- If a baseline moved, dependent targets ("hold >75%") move with it.
- Every precise number is sourced or softened. Flag every TBD/TK placeholder.

**C. Cross-section consistency**
- One concept, one framing (see mental model #3).
- One verb per action — don't alternate "writes to" / "contributes to" /
  "syncs with" for the same operation.
- FAQ doesn't commit to specifics the body left abstract (or vice versa).
- A reflections/learnings section contains at least one honest miss.

**D. Style**
- Acronyms expanded on first use.
- Length matches the claim — if it's a "one-pager," the core fits one page.
- Prose and diagram agree (node-name parity both directions).

**E. Don't over-flag**
- Repeating a key stat across sections is reinforcement, not duplication.
- Minor emphasis differences between summary and body are fine if both are
  correct.

Close a review by naming **the top 5 issues that matter most**, and offer to
produce the corrected draft.

## 6. Common Conversions

- **Prose → FAQ:** lead each answer with the direct claim, then support. Merge
  related questions when asked for "a single FAQ." Keep high-value tables; push
  the rest to prose.
- **List → table:** phase/deliverable content reads well as `Phase | Deliverable
  | Outcome` rows with a one-line theme per phase. Add a "closes which problem"
  column only if traceability is the goal.
- Either direction: strip code/API names unless the audience is explicitly
  engineering.

## Tips

- **Write the ask first, even if it lands last.** If you can't state the
  decision in one sentence, the doc isn't ready.
- **A reviewer's confusion is your bug, not theirs.** Re-read as the least
  informed reader who still needs to act.
- **Cut your favorite clever sentence.** Clarity beats cleverness every time.
- **Numbers you can't defend are liabilities.** Soften or source every one.
- **Read it out loud once.** You'll hear the passive voice, the run-ons, and the
  buried point.
- **The header outline is the doc.** If the headers alone don't tell the story,
  restructure before you polish prose.
