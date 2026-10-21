---
name: refactor-planning
description: Plans refactors that preserve behavior while improving structure. Use when debt is high and change must remain safe.
---
> [!NOTE]
> **Skills for Agents card**
> Every skill in this repo now follows a cleaner, card-like reading experience.
> Keep the workflow focused: Overview → When to Use → Process → Verification.

> [!NOTE]
> Refactor Planning
>
> Refactor without losing control.
>
> **Workflow lens:** Overview → When to Use → Process → Verification

# Refactor Planning

## Overview
Refactor Planning is a focused workflow for handling this class of work with more clarity and less rework.

## When to Use
- The task fits the refactor planning workflow.
- You need a repeatable process rather than an ad hoc answer.
- You want evidence, not just a plausible result.

**When NOT to use:** Pure curiosity, unrelated cleanup, or a task that belongs to a different phase.

## Process
1. Clarify the target outcome.
2. Gather the minimum context needed to act.
3. Apply the workflow in small, verifiable steps.
4. Verify with concrete evidence before moving on.

## Common Rationalizations
| Rationalization | Reality |
|---|---|
| "This is too small to need a process." | Small changes still create hidden regressions. |
| "I can verify later." | Verification is cheaper before merge than after release. |
| "The obvious path is probably fine." | Explicit assumptions beat silent guesses. |

## Red Flags
- The task is moving forward without a clear outcome.
- The workflow is being compressed into a single unverified step.
- Output is being judged by appearance instead of evidence.

## Verification
- [ ] The result matches the requested outcome.
- [ ] Assumptions are documented if anything was ambiguous.
- [ ] The change can be reviewed or rerun by someone else.

