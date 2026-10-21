---
name: agent-retrospective
description: An AI agent analyzing its own recent session transcripts to find friction, missed user corrections, and redundant work, then proposing durable improvements to its prompts, skills, and workflow. Use when asked to "self-improve", "run a retrospective", "what did I get corrected on", "find friction in my sessions", or to review and improve an agent's own behavior from its logs.
---

# Agent Retrospective

An agent getting better by reading its own transcripts. The goal is to convert
scattered in-session friction into **durable changes** — edits to system prompts,
skills, or workflow — so the same mistake doesn't recur. **Bias toward missing a
weak pattern over inventing a bad rule:** a wrong "lesson" is worse than no lesson.

## When to Run

- On a schedule (e.g. daily/weekly) over recent sessions.
- On demand: "self-improve", "run a retrospective", "what did I get wrong today".
- After a session that went badly, to capture the lesson while it's fresh.

## Step 1: Gather Sessions

Collect recent transcripts (session logs / JSONL / chat history). For each,
extract the user and assistant turns and the tool calls between them. Focus on:

- User corrections and friction signals.
- Multi-step workflows that succeeded (reuse candidates).
- Tool-call sequences — especially failures, retries, and redundancy.
- Explicit requests to remember something or "make a skill for this".

## Step 2: Detect Signals

### Correction signals (highest value)

| Strength | Look for |
|----------|----------|
| **Explicit** | "no", "wrong", "actually…", "not that", "I said", "I meant", "don't do X", "stop doing X", "never/always X", "like I told you" |
| **Implicit** | User repeats the same instruction; user undoes the agent's action (reverts a file, cancels a command); terse/frustrated replies after agent output |
| **Rephrasing** | User has to restate the request 2–3 times before the agent gets it |

### Friction signals

- **Dead ends:** the agent went down a path, hit nothing, backed out.
- **Redundant tool calls:** the same read/search/command repeated, or a
  wandering search that could have been one targeted query.
- **Thrash:** editing the same file back and forth; re-deriving something it
  already knew earlier in the session.
- **Wrong tool for the job:** a manual multi-step slog where one command/skill existed.

### Skill/prompt signals

- Agent **had a relevant skill but still erred** → the skill needs a clearer
  gotcha or anti-pattern.
- Agent **didn't load a relevant skill** when it should have → the skill's
  triggers/description are too weak.
- **Same 3+ step workflow appeared in 2+ sessions** → candidate for a *new* skill.
- Skill referenced a stale tool/URL/API, or was contradicted by what actually
  happened → needs a factual fix.

## Step 3: Categorize Findings

Sort each finding so the fix lands in the right place:

| Category | Root | Fix target |
|----------|------|-----------|
| **Behavioral correction** | Agent did X, user wanted Y, repeatedly | Prompt/rules or a lesson |
| **Missing knowledge** | Agent didn't know a fact/convention | Skill content or memory |
| **Missing capability** | No skill for a recurring workflow | New skill |
| **Weak triggering** | Skill exists but wasn't invoked | Skill description/triggers |
| **Inefficiency** | Correct result, wasteful path | Workflow guidance / tool-use tip |
| **Stale content** | Skill/prompt now factually wrong | Correct or delete |

## Step 4: Set an Evidence Bar

Before proposing a change, require enough evidence:

- **Explicit correction** → high confidence, act on a single instance.
- **Implicit friction** → needs a **repeat** (≥2 sessions, or twice in one) before
  you generalize it into a rule.
- **New skill** → needs the pattern in **2+ sessions**, or an explicit user ask.
- **One-off / user-specific quirk** → capture as a narrow note, don't promote it
  into a general rule.

No false positives. A cluttered rule set that fires on the wrong situations is
worse than a lean one.

## Step 5: Turn Findings into Durable Changes

Match the change to the durability you need:

- **Prompt / rules edit** — for behavioral corrections that should always apply.
  Phrase as a crisp, testable directive ("prefer X over Y because Z"), not a
  vague reminder.
- **Skill edit** — add a gotcha/anti-pattern to an existing skill, fix a stale
  fact, or sharpen its triggers so it fires when it should.
- **New skill** — only for a proven recurring multi-step workflow. Start
  minimal: triggers, procedure, a couple of anti-patterns, one concrete example.
- **Memory/note** — for durable facts and preferences that aren't a whole skill.
- **Delete/merge** — prune stale rules and skills; fold duplicates together. Cleanup is improvement.

For each proposed change, record: **the evidence** (which session, what
happened), **the change**, and **where it lands**.

## Step 6: Apply, Then Report

Apply the changes, then summarize what changed and why so the human stays aware:

```
Retrospective — <N sessions reviewed>
• Corrected: <behavior> → updated <prompt/skill>        [evidence: session X]
• New skill: <name> — <one-line purpose>                [seen in sessions X, Y]
• Updated:  <skill> — added gotcha about <thing>        [evidence: session Z]
• Pruned:   <skill/rule> — stale (<reason>)
```

## Step 7: Keep the Skill Set Healthy

Adding skills without curating them produces an overlapping, unfireable mess.
Periodically (e.g. a weekly pass, not every run) step back from individual
findings and tend the whole set.

### Extract shared patterns

When the same procedure shows up in multiple skills, that duplication is itself a
finding — factor it out:

- **Threshold:** the same pattern in **3+ skills** → extract it into its own skill.
- **Granularity:** extract at the *capability* level ("how to search a codebase
  effectively"), not the *step* level ("step 3 of workflow Y"). A good extracted
  skill answers "how to do X well," reusable by any workflow that needs X.
- **Reference, don't copy:** once extracted, parent skills *link* to it and delete
  the duplicated content. Note the relationship in both directions (what this
  skill references, and what references it) so the graph stays navigable.

### Maintain a clean hierarchy

Aim for three tiers, so skills compose instead of colliding:

```
Building-block skills   → how to use one tool/source/technique well
Orchestrator skills     → when/why to combine building blocks for a goal
Standalone skills       → self-contained domain or project workflows
```

(The oncall set in this repo is the worked example: building blocks like
`ticket-triage` and `alarm-correlation`, composed by the `oncall-agent`
orchestrator.)

### Run periodic audits

| Audit | Question | Action if it fails |
|-------|----------|--------------------|
| **Trigger** | Did this skill's triggers ever fire in recent sessions? | Never fired in weeks → its description/triggers are weak, or it's dead weight |
| **Accuracy** | When a skill *was* used, did the agent follow it correctly? | Errors despite the skill → the instructions are unclear; add a gotcha |
| **Coverage** | Which recurring workflows have *no* skill? | Repeated uncovered pattern → new-skill candidate |
| **Duplication** | Do any two skills overlap >~30%? | Merge, or extract the shared part per above |

## Tips

- **Explicit corrections are gold** — mine "no / actually / I said" first; they're unambiguous and high-value.
- **Require a repeat before generalizing.** One weird moment is noise; the same friction twice is a pattern worth a rule.
- **Redundant tool calls are a quiet, huge cost.** Repeated searches and re-reads signal a missing note, skill, or plan step.
- **Land the fix at the right altitude:** always-true behavior → prompt/rule; domain fact → skill/memory; recurring workflow → new skill.
- **A wrong lesson is worse than no lesson.** When unsure, capture it as a narrow note, not a broad directive.
- **Pruning counts.** Deleting a stale rule or merging duplicate skills makes the agent better, not just adding new ones.
- **Write directives to be testable.** "Prefer X over Y because Z" beats "be more careful."
- **Duplication is a finding too.** The same procedure in three skills isn't three skills — it's one building block waiting to be extracted and referenced.
