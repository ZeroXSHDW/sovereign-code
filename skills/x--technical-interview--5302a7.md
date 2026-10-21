---
name: technical-interview
description: Prepare for and conduct technical interviews — coding rounds, system-design rounds, and the interviewer prep doc. Use when running or preparing a coding or design interview, calibrating a candidate's technical level, writing a technical debrief, building an interview question bank, or coaching a candidate on coding/design rounds.
---

# Technical Interviewing

Technical interviews measure how someone thinks under a real constraint, not
whether they memorized an answer. A coding round tests problem decomposition,
data-structure choice, and code quality; a design round tests handling of
ambiguity, tradeoffs, and non-functional requirements. This skill covers how to
run each, how to calibrate signal to a level, and how to write the debrief — for
both interviewer and candidate.

For the *behavioral* half of a loop (past-behavior stories, STAR, competency
probing), use the **behavioral-interview** skill. This one is the technical
complement.

## Pick the Round Type

| Round | What it actually tests | Don't confuse it with |
|-------|------------------------|------------------------|
| **Coding — problem solving** | Decomposition, algorithm/data-structure choice, edge cases, working code | Trivia; memorized LeetCode |
| **Coding — logical & maintainable** | Clean structure, separation of concerns, naming, error handling | Raw speed |
| **System design** | Ambiguity handling, tradeoffs, scale/perf/security reasoning, API design | A "correct" architecture |
| **Debugging / existing-system** | Root-causing in unfamiliar code, hypothesis-driven investigation | Knowing the codebase already |

Decide up front which one this slot is. Grading a maintainability round on raw
speed (or a problem-solving round on variable naming) produces noise.

## Coding Rounds

### Run it as a collaboration, not an exam

- **Set the frame:** "Think out loud, ask clarifying questions, and it's fine to
  start rough and refine. I care how you get there, not just the final code."
- **Let them clarify first.** A candidate who restates the problem and asks about
  input bounds / edge cases before coding is already showing signal.
- **Give a moment to think.** Only offer a hint if they're genuinely stuck, and
  note that you hinted — it changes the calibration.
- **Probe the *why*:** "Why that data structure?" "What's the complexity?"
  "What breaks at 10× the input?"

### Calibration — the three-bucket model

Grade against the level you're hiring for, using a consistent rubric:

| Signal | What it looks like |
|--------|--------------------|
| **Raises the bar** | Reaches an efficient approach without hints; sees the right abstraction early; identifies edge cases unprompted; clean, idiomatic code |
| **Meets the bar** | Clarifies requirements, arrives at a working solution, writes functional code, handles the obvious cases |
| **Lowers the bar** | Can't identify a suitable data structure; logical errors they don't catch; needs to be steered to their own solution; can't finish in time |

Scale the expectation with seniority: a junior candidate meeting the bar solves
the stated problem cleanly; a senior candidate is expected to *see the
abstraction before starting* and reason about tradeoffs and failure modes on
their own.

### Progressive-milestone questions

The best coding problems have layers, so one question calibrates across levels.
Example shape (a file-finder / tree-traversal problem):

1. Traverse a directory tree and print entries. *(baseline)*
2. Filter by a single criterion (name match). *(baseline)*
3. Abstract "criterion" into a matcher interface. *(mid — abstraction)*
4. Combine criteria with AND/OR. *(mid — composition)*
5. Handle symlinks / cycles / permission errors. *(senior — edge cases)*

Lower levels complete the early milestones with light help; higher levels see
the matcher abstraction *before* coding and handle the hard cases unprompted.

### Red flags (coding)

- Reading from another screen before coding (prepared answers).
- Can't explain *why* they chose a data structure.
- Trades off on only one dimension ("it's faster") and misses the others.
- Needs to be guided to their own solution at every step.
- Logical errors they don't notice even when running through an example.

## System-Design Rounds

### Frame it as a driven conversation

"Treat me as a senior engineer on your team — you drive. Ask clarifying
questions, state your assumptions, and think out loud. I want your reasoning,
not a project you already shipped."

### What to probe, in order

1. **Requirements & scope** — Do they nail down functional needs *and*
   non-functional ones (scale, latency, availability, consistency) before
   drawing? Pushing back on vague requirements is a strong signal.
2. **High-level design** — Components, data flow, API boundaries. Is it coherent?
3. **Data model & storage** — Access patterns, consistency, indexing, hot keys.
4. **Scale & performance** — What breaks at 10×/100×? Caching, sharding,
   queues, backpressure.
5. **Failure modes** — What happens when a dependency is down? Retries,
   idempotency, graceful degradation.
6. **Security & correctness** — AuthN/Z, data protection, input validation.
7. **Tradeoffs** — Can they name what they gave up for what they gained? This is
   the whole round. "It depends, and here's on what" beats a confident wrong
   absolute.

There is no single correct architecture. Grade the *reasoning*: did they surface
tradeoffs, quantify, and adapt when you added a constraint?

## The Interviewer Prep Doc

Build the doc as something you run **top-to-bottom during** the interview, not a
brief you skim once beforehand.

- **Order by the clock, not by topic.** Walk the timeline: intro → Q1 → Q2 →
  wrap. Don't put all questions in one section and all rubrics in another —
  you'll be flipping around mid-interview.
- **Co-locate rubric with each question.** Under each question, put: what a
  strong answer covers, the raises/meets/lowers calibration, and (for design)
  the reference architecture. Grade in place.
- **Use real wall-clock times.** "2:45–2:55 Intro", "2:55–3:20 Coding", …
  anchored to the actual start time — you glance at the clock, not a stopwatch.
- **Mark "read aloud" vs "interviewer-only."** Flag anything you must *not* show
  the candidate — especially internal architecture in a reference answer for an
  external candidate — as "do not read/show."
- **Keep a skim header** on top: candidate snapshot, the one thing to test,
  calibration flags — so you can prime in the last two minutes before they join.

## 60-Minute Structure

- **0–10 — Intro.** Greet, introduce yourself and any shadow, outline the
  structure, explain whether they'll write code / whiteboard and that you'll take
  notes. Hand off to Q1.
- **10–55 — Questions.** One problem at a time. Give thinking time; probe only
  for missing info; take detailed notes on decisions and reasoning, not just the
  final answer.
- **55–60 — Their questions + wrap.** Don't answer things you're unsure of —
  point to the hiring manager/recruiter. Thank them; explain next steps.

## External vs. Internal-Transfer Interviews

An internal transfer is a different format — don't run the external loop on them.

| Aspect | External | Internal transfer |
|--------|----------|-------------------|
| Duration | ~60 min | ~45 min |
| Tone | Structured probing | Conversational, collegial |
| Questions | Abstract problems | Anchored on their real recent work |
| Design portion | Design from scratch | Collaborative sketch of a real team problem |
| Evaluation | Hire / no-hire on fixed signals | Ramp speed, depth, self-awareness, fit |

For internal transfers: anchor on their most complex recent project and probe
depth there; sketch a real problem from *your* team together; assess how fast
they pick up unfamiliar context and whether they know their own gaps.

## Writing the Debrief

- **Lead with the verdict**, then the evidence: *Inclined / Not inclined* (or
  your scale), followed by specific moments — quotes, decisions, what they did
  when you added a constraint.
- **Evidence, not impressions.** "Chose a hash map and explained the O(1)
  lookup tradeoff vs memory" beats "strong coder."
- **Tie to the level.** State what you'd expect at the target level and where the
  candidate landed relative to it.
- **Write it immediately.** Detail decays within minutes of the interview ending.

## Candidate Side (coaching)

- **Clarify before coding.** Restate the problem, ask about input size and edge
  cases. It's signal, not stalling.
- **Think out loud.** Silence reads as being stuck. Narrate your options and why
  you're picking one.
- **Name your tradeoffs.** "I'll use X for O(1) lookups at the cost of memory" is
  exactly what design rounds reward.
- **Start simple, then optimize.** A working brute force you then improve beats a
  clever solution that never runs.
- **Test your own code.** Walk a real example through it before declaring done.

## Tips

- **Decide the round type first.** Half of bad interviews are grading a coding
  round on design criteria or vice versa.
- **Grade the reasoning, not the artifact.** The final architecture/code matters
  less than how they got there and what they traded off.
- **Hints are data.** Note every hint — "solved it, but only after two nudges" is
  a different rating than "solved it cold."
- **One question, many levels.** Layered problems calibrate juniors and seniors
  with the same prompt.
- **Never show internal architecture** in a reference answer to an external
  candidate.
- **Pair this with `behavioral-interview`** for a full loop.
