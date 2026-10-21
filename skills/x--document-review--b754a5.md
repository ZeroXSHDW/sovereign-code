---
name: document-review
description: Review and comment on someone else's document or prose (not code) — design docs, proposals, specs, narratives, PR/FAQs. Use when the user asks to review a doc, give feedback on writing, comment on a draft, or do a pre-ship review pass on a document. Produces structured, severity-labeled feedback that improves the doc without rewriting the author's voice.
---

# Reviewing a Document

Reviewing prose is different from reviewing code. The question isn't "does it
compile" but "does it make its case to its reader and drive its decision." Work
top-down — judge whether the doc answers its own question before you touch a
sentence — and leave feedback the author can act on without you in the room.

## Review Top-Down, Not Line-First

Read the whole doc once before commenting. Then evaluate in this order — an
early-level problem makes line edits pointless.

| Level | Question | If it fails |
|-------|----------|-------------|
| **1. Purpose** | Does it answer the question it set out to answer? Is the ask/decision clear? | Everything else is premature. Flag this first. |
| **2. Audience fit** | Right altitude for the reader? Too much/little detail? | Reframe before editing prose. |
| **3. Structure** | Point-first? Do headers alone tell the story? Logical flow? | Suggest a reorder; don't polish a broken outline. |
| **4. Evidence** | Claims backed by data? Numbers sourced and defensible? | Mark unsupported claims and un-sourced numbers. |
| **5. Completeness** | What's missing? Alternatives? Risks? The obvious objection? | Name the gap explicitly. |
| **6. Line level** | Clarity, wording, consistency, typos. | The last pass, not the first. |

## What to Check at Each Level

**Purpose.** Can you state, in one sentence, what decision this doc drives? If
not, that's the top comment. A doc that doesn't move a decision forward needs
reframing, not editing.

**Structure.** Does it lead with the point or bury it? Read the headers alone —
do they convey ~80% of the story? Is the strongest argument first? Are related
ideas together?

**Evidence.** Every precise number ("reduced cost 8 weeks," "~3.5%") should be
sourced or softened to a defensible range — *a specific number invites a
specific question*. Flag adjectives standing in for data ("fast," "scalable,"
"robust" with no metric). Flag claims with no support.

**Completeness — the highest-value review contribution.** Readers can fix
wording; they often can't see their own blind spots. Ask:
- Are alternatives considered and rejected, or just the chosen path asserted?
- Are risks and their mitigations/rollbacks stated?
- What's the obvious objection a skeptic raises — is it addressed?
- Does a reflections/learnings section include at least one honest miss?

**Consistency (cross-section integrity).** This is where most doc bugs hide:
- A headline metric must read identically everywhere it appears.
- One concept, one framing — if privacy is "user control" in the summary and
  "compliance" in the body, that reads as two authors. Flag it.
- One verb per action — don't alternate "writes to" / "syncs with" / "contributes
  to" for the same operation.
- FAQ mustn't commit to specifics the body left abstract (or contradict it).
- Every cross-reference ("see section X," "Appendix Y") still resolves; section
  numbering has no gaps.
- If the doc has a diagram, the prose names exactly the nodes the diagram draws —
  no extras, no omissions.

## Write Actionable, Labeled Comments

Every comment tells the author **what**, **why**, and ideally **how**. Anchor it
to a specific passage. Label severity so the author knows what gates the doc:

- **blocking** — must fix before it ships (wrong claim, unsupported key number,
  missing risk section, contradicts itself, doesn't answer its question).
- **suggestion** — would improve it; author's call.
- **nit** — trivial/optional (typo, phrasing); prefix `nit:` so it's clearly
  non-blocking.
- **question** — you need clarification before you can judge.

**Weak:** "This section is confusing."
**Strong:** "blocking: the summary says this serves all users, but §3 scopes it
to enterprise accounts. Pick one framing and use it in both places — I think you
mean enterprise-only, which is fine, just say so up front."

Prefer a concrete rewrite over a critique. A suggested two-line replacement is
worth ten sentences of description.

## Preserve the Author's Voice

You're improving *their* document, not writing yours.

- Suggest the smallest change that fixes the issue. Don't rewrite a paragraph to
  match your style when a word fixes it.
- Comment on clarity, correctness, and structure — not stylistic preference the
  author is entitled to.
- Frame line edits as suggestions unless they're actually wrong.
- If you'd restructure heavily, say so as a top-level comment and let the author
  drive, rather than silently rewriting.

## Summary Comment Template

Lead with the verdict and the highest-value items:

```
## Review summary
<one-line assessment: does it work, and what's the biggest lever>

### Blocking
- §2 — the "40% faster" claim has no source; either cite it or soften to a range.
- §4 — no alternatives considered; reviewers will ask "why not X?"

### Suggestions
- Lead §1 with the ask; it's currently in the last paragraph.
- Merge the three FAQ entries on pricing into one.

### Nits
- Intro — typo "recieve".
- Acronym "DDR" not expanded on first use.

Strong problem framing in §1 — the customer-first opening lands well.
```

If asked for a full calibration pass, group findings as **must-fix errors →
inconsistencies → style → minor/acceptable**, then name the **top 5 that matter
most**, and offer to produce the corrected draft.

## Don't Over-Flag

- Repeating a key stat across sections is reinforcement, not duplication.
- Minor emphasis differences between summary and body are fine if both are
  correct.
- Not every long sentence is wrong. Flag what impedes the reader, not what
  differs from how you'd write it.

## Collaborative-Editing Hygiene

When editing a shared/live document rather than just commenting:

- **Read the current structure before editing** — never guess at a heading or
  section boundary; work from what's actually there.
- **Make one clean change, not a stack of small patches** — layered partial
  edits drift and produce duplicates. If a section is broken, replace it whole.
- **If edits have already produced duplicates or orphaned sections, stop
  patching** and rebuild the affected section cleanly rather than chasing it.
- **Prefer bullet lists to tables** in tools that render tables poorly, and keep
  formatting simple and portable.

## Tips

- **Judge the doc before the sentences.** A polished paragraph in the wrong
  section is wasted effort.
- **Separate blocking from optional.** Authors stall when they can't tell what
  actually gates the doc.
- **The missing content is the valuable feedback.** Anyone can catch a typo;
  spotting the unaddressed objection is the review that matters.
- **Suggest, don't rewrite.** It's the author's voice and their decision.
- **Praise what works.** It tells the author what to keep doing.
- **Chase every cross-reference and repeated number.** Dead refs and mismatched
  metrics are the most common — and most catchable — errors.
