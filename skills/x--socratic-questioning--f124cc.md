---
name: socratic-questioning
description: Structured questioning to reach shared understanding BEFORE taking action. Use when the user wants to think through a plan, align on an approach, poke holes in a design, or figure out decisions before committing — triggers like "before we start", "think this through", "what am I missing", "poke holes", "help me decide", "let's align", "grill me", "challenge this", "what should I consider".
---

# Socratic Questioning

Before acting on an ambiguous or high-stakes request, the fastest path is often
to ask, not to build. This skill is a discipline for reaching **shared
understanding** first: walk the decision tree one branch at a time, ask **one
focused question** per turn, surface hidden assumptions, and stop the moment you
know enough to act. The goal is not interrogation for its own sake — it's to
avoid confidently building the wrong thing.

## Mental Model: Grill vs. Just Act

Every request lands somewhere on a spectrum. Questioning is *insurance*, and
insurance is only worth buying when the risk is real. Weigh three things:
**ambiguity** (do you actually know what they mean?), **cost** (how expensive is
the work?), and **reversibility** (can you cheaply undo a wrong guess?).

| Signal | Just act | Grill first |
|--------|----------|-------------|
| **Ambiguity** | Request is clear and specific | Vague, underspecified, or multiple readings |
| **Cost of work** | Cheap — minutes, a few lines | Expensive — large change, lots of effort |
| **Reversibility** | Easily undone (edit, revert) | Hard/impossible to undo (deletion, migration, sent message, public release) |
| **Blast radius** | Affects one file / you only | Affects others, prod, data, money |
| **Confidence** | You'd bet on your interpretation | You're guessing at intent |
| **Cost of a wrong guess** | Trivial rework | Wasted days, damage, lost trust |

**Rule of thumb:** clear + cheap + reversible → **act now**, don't stall behind
questions. Ambiguous *or* high-cost *or* irreversible → **grill first**. When two
or more risk signals fire, always grill. When uncertain whether it's
irreversible, treat it as if it is.

The failure mode in both directions is real: over-questioning a trivial task is
annoying and wastes the user's time; under-questioning a costly, irreversible
one burns hours or does damage. Calibrate to the stakes.

## Ask ONE Question at a Time

Do not fire a checklist of ten questions. A wall of questions gets skimmed,
half-answered, and forces the user to context-switch across unrelated decisions.

- Ask the **single most decision-unblocking** question — the one whose answer
  changes what you'd ask (or do) next.
- **Offer your recommended answer** with each question. "I'd default to X because
  Y — does that hold?" is faster to react to than an open prompt, and it shows
  your reasoning so the user can correct the premise, not just the conclusion.
- Wait for the answer, integrate it, then ask the next one. Later questions often
  dissolve once an earlier one is answered.

## Walk the Decision Tree, Branch by Branch

Treat the plan as a tree of decisions with dependencies. Resolve the **root**
decisions before the leaves — a leaf question is wasted if the branch it hangs
on gets pruned.

1. Identify the decisions the work depends on.
2. Order them: what must be settled before other questions even make sense?
3. Walk down one branch at a time. Fully resolve a branch before switching.
4. When an answer prunes a branch, drop every question that lived on it.

Example: don't debate which database index to add before you've established
whether the slow query is even the bottleneck. "Where's the actual latency?"
gates "which index?" — ask it first.

## Answer From Evidence, Not the User, When You Can

If a question can be answered by reading the code, the docs, the logs, or prior
context — **go find out instead of asking.** The user's attention is the scarce
resource. Only ask questions that genuinely require *their* judgment, intent, or
information you can't obtain yourself.

Before asking, check what's already been decided earlier in the conversation or
in project notes. If it's settled, **confirm rather than re-ask**: "Earlier you
said X — still the plan?" Re-asking a settled question erodes trust.

## Surface and Check Hidden Assumptions

The most dangerous assumptions are the ones nobody said out loud. Make them
explicit and get them confirmed or killed.

- **State the assumption you're operating under** and ask if it's true: "I'm
  assuming this runs only in the internal network — is that right?"
- Probe the unspoken: scope boundaries ("does this include X, or just Y?"),
  constraints ("any deadline / budget / compat requirement I should know?"),
  and success criteria ("how will we know this worked?").
- Watch for words that hide a decision: "just", "simply", "obviously", "handle
  it", "make it work". Each usually conceals an unmade choice.

## Said vs. Meant vs. Needs

The literal request is rarely the whole picture. Separate three layers:

| Layer | Question to ask yourself |
|-------|--------------------------|
| **Said** | What are the literal words of the request? |
| **Meant** | What outcome are they actually picturing? |
| **Needs** | What would actually solve their underlying problem — even if unrequested? |

When these diverge, name the gap: *"You asked for a retry loop (said), which
tells me you want this to survive flaky network calls (meant) — but the real fix
might be idempotency so retries are safe at all (needs). Which layer do you want
me to work at?"* The XY-problem pattern — user asks about their attempted
solution rather than their real goal — lives here. Ask "what are you ultimately
trying to do?" when the request smells like a workaround.

## Knowing When to Stop

Questioning has diminishing returns. Stop when the next question wouldn't change
what you do. You have enough understanding when:

- You can **state the plan back** in one or two sentences and the user would nod.
- The **remaining unknowns are cheap and reversible** — safe to decide as you go.
- Further questions would only refine details you could adjust later anyway.

Then **summarize the decisions and proceed.** Explicitly hand control back:
*"Okay — here's what I'll do: [1-line plan]. Starting now."* If the user says
"enough" or "just do it" at any point, stop immediately, summarize what's been
decided, and act. Respect that override; the questioning serves them, not you.

## Example Question Sequences

**Ambiguous feature request** — "Add caching to the API."
1. "What problem is caching solving — latency, cost, or rate limits? I'd guess
   latency given the recent slow-response reports. Right?"
2. (latency) "Which endpoints are actually slow? I can pull the p99s myself —
   hold on." → *answer from evidence, don't ask.*
3. "These 3 endpoints dominate. Their data changes ~hourly, so I'd cache with a
   short TTL rather than invalidate on write. Acceptable staleness?"
4. → Plan is clear. "I'll add a 5-min TTL cache on those 3 read endpoints.
   Starting."

**Irreversible / high-cost** — "Delete the old users table, we migrated off it."
1. "Anything still reading from it? I'll grep the codebase before we touch it." →
   *check evidence first.*
2. "Two cron jobs still query it. Migrate those first, or are they dead too?"
3. "Given it's irreversible, I'd snapshot the table before dropping it. OK?"
4. → "Confirmed dead, snapshot taken. Dropping now." *(Grilled because
   irreversible + affects data — even though the request was short.)*

**Clear + cheap + reversible** — "Fix the typo in the README heading."
→ No questions. Just fix it. Grilling here would be noise.

## Tips

- **Match questioning to stakes.** Clear + cheap + reversible → act. Ambiguous or
  costly or irreversible → grill. Two risk signals → always grill.
- **One question at a time, with your recommended answer attached.** A wall of
  questions gets skimmed; a single sharp one gets answered.
- **Explore before you ask.** If code, logs, or context hold the answer, go get
  it — spend the user's attention only on genuine judgment calls.
- **Resolve root decisions before leaves.** A leaf question is wasted if its
  branch gets pruned.
- **Name your assumptions out loud.** The unspoken one is the one that sinks you.
- **Separate said / meant / needs.** The literal request is rarely the whole
  problem; watch for the XY problem.
- **Stop when the next question wouldn't change what you do.** Then state the
  plan back and proceed.
- **"Just do it" is a hard stop.** Summarize decisions and act — the questioning
  serves the user, not the ritual.
