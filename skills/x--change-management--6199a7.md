---
name: change-management
description: Plan and execute production changes safely via a change record / change request — what/why, blast radius, rollback, verification, timing, risk tier, and approvals. Use when the user asks to create a change record, schedule a deployment or config change, plan a launch/dial-up, write a rollback plan, or run a change safely in production.
---

# Change Management

A change record (a.k.a. change request / change ticket) is the plan and the
paper trail for a production change. Tool-agnostic — the fields below map onto
any change-management system. The point isn't the form; it's that **someone can
execute the change, verify it, and undo it under pressure, without you in the
room.**

## What a Good Change Record Contains

| Section | Answers | Why it matters |
|---------|---------|----------------|
| **What** | Precisely what changes (which service, config, version, %) | Executor must not guess |
| **Why** | The reason/ticket/goal | Reviewers judge risk vs. value |
| **Blast radius** | Who/what is affected if it goes wrong | Sets the risk tier and the audience |
| **Timing** | Start/end window, timezone, dependencies | Avoids collisions with freezes and other changes |
| **Steps** | Ordered, executable actions | The actual runbook |
| **Verification** | How you confirm each step worked | "Deployed" ≠ "working" |
| **Rollback** | How to undo, per step, fast | The single most important field |
| **Approvals** | Who signed off, at what level | Accountability + a second set of eyes |

## Risk Classification

Tier the change first — it drives how much rigor, how many approvers, and what
timing constraints apply.

| Tier | Looks like | Approval + timing |
|------|-----------|-------------------|
| **Low** | Reversible, small blast radius, well-trodden (flag flip, minor config) | Lightweight review; normal hours OK |
| **Medium** | Customer-facing, moderate blast radius, staged rollout | Peer + owning-manager sign-off; avoid peak traffic |
| **High** | Irreversible or wide blast radius (schema/data migration, infra teardown, security change) | Multi-level approval, explicit rollback rehearsal, off-peak window, extra monitoring |

Escalate a tier when: the change touches data, can't be cleanly rolled back,
crosses team boundaries, or you're unsure.

## Writing the Steps: Act → Verify Pairs

**Every action step must be followed by a verification step** — including the
final one. Never end a change on an unverified action. This structure is what
lets you catch a bad step *before* the next one compounds it.

```
Preflight
  1. Check baseline health (dashboards, error rate, latency)   [verify]
  2. Go/no-go from approvers                                   [gate]

Rollout (Act → Verify pairs)
  3. Dial feature to 10%              (act)
  4. Confirm: 10% active, no error/latency regression   (verify)
  5. Dial to 50%                      (act)
  6. Confirm: 50% active, metrics healthy               (verify)
  7. Dial to 100%                     (act)
  8. Confirm: 100% active, sustained healthy            (verify)

Post-change
  9. Post-launch validation           (act)
  10. Confirm: steady-state healthy over N minutes      (verify)
```

Each **act** step carries its own **rollback** instruction (e.g. "dial back to
previous %"). Each **verify** step names the concrete signal: a specific metric,
threshold, dashboard, or query — not "looks fine".

## The Rollback Plan (non-negotiable)

- **Every action step gets a rollback.** If you can't state how to undo a step,
  you're not ready to run it.
- Prefer changes that roll back **without a redeploy** (flag/percentage flips,
  config reverts) over ones that require rebuilding and shipping.
- For irreversible steps (data migration, deletion), the "rollback" is a
  **restore-from-backup** plan — verify the backup exists and is recent *before*
  the change, not after.
- State rollback time. "Revert takes 30 min" changes the go/no-go calculus.

## Approvals

- **Two levels of eyes:** peer/technical review *and* owning-manager sign-off.
  A change approved only by peers is missing accountability; one approved only
  by a manager may be missing technical scrutiny.
- **Approvers must see the current plan.** If you edit steps after approval, the
  sign-off should re-trigger — approving stale steps is worthless.
- Pull in the on-call / owners of anything in the blast radius as reviewers or
  notify-recipients so they aren't surprised.

## Timing

- Check for **change freezes / blackout windows** (peak seasons, other major
  changes, incident-in-progress) before scheduling.
- Use an unambiguous timezone (prefer UTC) and record both start and end.
- Schedule risky changes for **low-traffic windows** with the people who can
  roll back actually available.

## Running the Change

1. **Preflight:** confirm baseline health and that approvals + backups are in place.
2. **Execute one Act → Verify pair at a time.** Do not proceed past a failed
   verification — roll back that step instead.
3. **Watch the signals**, not just the deploy status. Wire up the relevant
   alarms/monitors so a regression can trigger a rollback automatically or page you.
4. **Log as you go** — annotate the record with what actually happened, timestamps, and anything unexpected.
5. **Close out** with the final state and any follow-ups.

## Tips

- **The rollback plan is the deliverable.** If it's missing or hand-wavy, the change isn't ready — full stop.
- **Verify after every act, and never end on an act step.** The final "did it actually work?" check is the one people skip and regret.
- **Verification means a concrete signal** — a named metric, threshold, or query. "Looks fine" is not verification.
- **Write for an executor who isn't you.** On-call at 3am should be able to run and undo it from the record alone.
- **Prefer no-redeploy rollbacks.** Flag/percentage flips beat rebuild-and-ship when you need to bail fast.
- **Re-approve after edits.** Sign-off on steps that changed afterward is no sign-off.
- **Check for freezes and collisions before you schedule** — a perfect change in a blackout window still gets rejected.
- **Verify backups before irreversible steps**, not after you need them.
