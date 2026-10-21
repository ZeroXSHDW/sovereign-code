---
name: writing-style-transfer
description: Extract a specific person's or brand's writing voice from samples and reproduce it when drafting. Use when the user asks to "write this in my voice," "match my style," "sound like our brand," draft an email/post the way someone usually writes, or build a reusable style guide from example messages.
---

# Writing-Style Capture

A method for reverse-engineering someone's writing voice from real samples,
distilling it into a reusable **style card**, and applying that card when
drafting on their behalf. Works for an individual's emails and messages or a
brand's public copy. The goal is a draft the person would send as-is.

## The Workflow

```
1. Gather representative samples
2. Extract style dimensions (measure, don't guess)
3. Build a style card
4. Draft against the card
5. Diff the draft against the samples and correct
```

## 1. Gather Representative Samples

Voice varies by context, so sample across it. Collect 5-15 pieces spanning:

- **Audience** — messages to a manager, a peer, a report, an external party.
- **Length** — a one-line reply and a longer explanatory message.
- **Register** — a routine update and a high-stakes or delicate message.
- **Recency** — prefer the last 6-12 months; voice drifts.

Prefer *sent* messages (what they actually write) over drafts or things others
wrote for them. If you only have a narrow slice (e.g. all short replies), say so
in the style card — don't extrapolate a formal voice from casual samples.

## 2. Extract Style Dimensions

Go through the samples against a fixed checklist so the profile is consistent
and nothing high-signal is missed. Measure where you can; cite an example line
for each observation.

| Dimension | What to look for |
|-----------|------------------|
| **Sentence length & rhythm** | Short and clipped? Long and compound? Mixed? Count words/sentence in a sample. |
| **Formality** | Contractions? Slang? Corporate register? Academic? |
| **Greeting** | "Hi [name]," vs "Hey," vs "Dear" vs none. Team vs individual openers. |
| **Sign-off** | "Thanks, [name]" vs "Best" vs "Cheers" vs nothing. Is the name on its own line? |
| **Structure habits** | Leads with the point or builds up? Bullets vs prose? Uses headers? States assumptions explicitly? |
| **Vocabulary & tics** | Recurring words, hedges ("I think," "roughly"), intensifiers, transitions ("that said," "to be clear"). |
| **Punctuation & mechanics** | Em-dashes? Exclamation points? Emoji? Oxford comma? ALL-CAPS emphasis? |
| **Directness** | States the ask up front or softens it? Asks specific questions or "please advise"? |
| **What they never do** | Absences are signal. No emoji, no filler openers, no "per my last email," never CC-alls. |

The negative space (dimension: *never does*) is often the strongest fingerprint.
A voice is defined as much by what it omits as by what it includes.

## 3. Build a Style Card

Distill the extraction into a compact, reusable card. Keep it short enough to
paste into a prompt. Template:

```markdown
# Style Card — <person / brand>

## Voice in one line
<e.g. "Concise, direct, technical; states assumptions then invites correction.">

## Rules
- Greeting: <pattern>
- Sign-off: <pattern>
- Sentence length: <short / mixed / long — with a number>
- Formality: <level, with a marker: contractions yes/no>
- Structure: <leads with conclusion / bullets over prose / etc.>
- Directness: <up-front ask / specific questions>

## Vocabulary
- Uses: <recurring phrases, with examples>
- Hedges/intensifiers: <list>

## Never does
- <no emoji / no filler openers / no passive-aggressive phrasing / …>

## By audience
| Audience | Tone | Typical length |
|----------|------|----------------|
| <manager> | <brief, commitment + context> | <2-3 sentences> |
| <peer>    | <direct, no formality>        | <1-5 sentences> |
| <external>| <context-heavy, clear ask>    | <5-10 sentences> |

## Sample lines (anchors)
> "<one real representative sentence>"
> "<another>"
```

Keep 2-3 real sample lines in the card as anchors — concrete examples steer a
draft better than adjectives.

## 4. Draft Against the Card

When drafting, apply the card in this order:

1. Pick the audience row → set tone and target length.
2. Open with the person's greeting pattern.
3. Structure the body their way (lead with the point if they do; bullets if
   they bullet).
4. Match sentence rhythm and formality.
5. Insert characteristic vocabulary sparingly — a tic or two, not a parody.
6. Close with their exact sign-off.
7. Run the "never does" list as a final filter.

## 5. Diff and Correct

Before delivering, compare the draft against the anchor samples:

- Read a real sample, then your draft. Do they sound like the same author?
- Check the mechanics: greeting, sign-off, punctuation, emoji policy.
- Over-styling is the common failure — a caricature with every tic at once.
  Dial it back until it reads natural.
- If the draft's context (audience, stakes) falls outside your samples, flag the
  uncertainty rather than inventing a register you never observed.

## Tips

- **Absences are the strongest fingerprint.** "Never uses emoji" and "never
  opens with filler" identify a voice faster than any positive trait.
- **Anchor with real lines, not adjectives.** "Sounds like this: <quote>" beats
  "sounds professional."
- **Match structure before vocabulary.** Readers register *how the point is
  organized* before they notice word choice.
- **Don't over-apply tics.** A voice uses a signature phrase occasionally, not
  in every sentence.
- **Re-sample when the voice drifts.** Refresh the card if the person's role,
  audience, or medium changes.
- **Keep the card versioned** alongside the samples so you can see what changed
  and why.
