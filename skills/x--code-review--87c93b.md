---
name: code-review
description: Structured code-review workflow for GitHub pull requests. Use when the user asks to review a PR, review changes, give code-review feedback, or check a diff before merge. Fetches the diff, reviews against a rubric, and posts actionable inline comments.
---

# PR Review Workflow

A disciplined workflow for reviewing a pull request: understand the change,
review the diff against a consistent rubric, and leave **actionable** feedback.
Built around the [`gh` CLI](https://cli.github.com/) but the rubric applies to
any review tool.

## 1. Understand the Change First

Never review a diff cold. Read the intent before the lines.

```bash
gh pr view <number>                 # title, description, linked issues
gh pr view <number> --json title,body,files,additions,deletions
gh pr diff <number>                 # the full diff
gh pr checks <number>               # is CI green? don't review red CI unless asked
```

Ask yourself: *What problem does this solve? What's the smallest correct diff
that solves it? Does this PR match that?*

## 2. Review Against a Rubric

Go through the diff with a fixed set of lenses so reviews are consistent and
nothing high-value is missed. Roughly in priority order:

| Lens | What to look for |
|------|------------------|
| **Correctness** | Logic errors, off-by-one, wrong operator, unhandled branches, race conditions |
| **Edge cases** | Null/empty/negative inputs, boundary values, timeouts, partial failures |
| **Error handling** | Swallowed exceptions, missing retries/backoff, unclear error messages, leaks on the error path |
| **Security** | Injection, unvalidated input, secrets in code, authz gaps, unsafe deserialization |
| **Tests** | Do tests cover the new behavior *and* the failure modes? Would they catch a regression? |
| **API/contract** | Backward compatibility, naming, defaults, breaking changes to public surfaces |
| **Readability** | Clarity over cleverness, naming, dead code, comments that explain *why* |
| **Performance** | N+1 queries, needless allocation in hot paths, unbounded growth — only when it matters |

Don't nitpick style a linter/formatter should own. Focus review time on things
tools can't catch.

## 3. Write Actionable Comments

Every comment should tell the author **what** and **why**, and ideally **how**.
A good comment is specific and anchored to a line.

**Weak:** "This could be better."
**Strong:** "This `map` runs a DB query per item (N+1). Batch the IDs and do one
`WHERE id IN (...)` query — otherwise a 100-item list is 100 round trips."

Label severity so the author knows what blocks merge:

- **blocking** — must fix before merge (bugs, security, broken contracts)
- **suggestion** — worth doing, author's call
- **nit** — trivial/optional, prefix with `nit:` so it's clearly non-blocking
- **question** — you need clarification before you can judge

## 4. Post the Review

Inline comments + a summary via `gh`:

```bash
# Approve
gh pr review <number> --approve --body "LGTM — clean retry logic, tests cover the backoff schedule."

# Request changes with a summary
gh pr review <number> --request-changes --body "Two blocking issues (N+1 query, missing null check). Details inline."

# Comment without a verdict
gh pr review <number> --comment --body "A few suggestions, nothing blocking."
```

For line-anchored inline comments, use the GitHub API via `gh api` (the
`gh pr review` command posts a single body; inline comments need the reviews
endpoint):

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments \
  -f body="blocking: this dereferences \`user\` before the null check on line above." \
  -f commit_id="$(gh pr view <number> --json headRefOid -q .headRefOid)" \
  -f path="src/handler.ts" \
  -F line=42 \
  -f side="RIGHT"
```

## 5. Summary Comment Template

Lead with the verdict and the highest-value items:

```
## Summary
<one-line assessment + verdict>

### Blocking
- `src/handler.ts:42` — dereferences `user` before the null check.
- `src/db.ts:88` — N+1 query in the enrichment loop.

### Suggestions
- Extract the retry schedule into a named constant.

### Nits
- `client.ts:15` — typo "recieve".

Nice work on the test coverage for the failure paths. 👍
```

## Tips

- **Review the intent, then the code.** A correct implementation of the wrong thing still fails review.
- **Separate blocking from optional.** Authors stall when they can't tell what actually gates merge.
- **Prefer diffs in comments.** A 3-line suggested change is worth ten sentences.
- **Praise what's good.** It calibrates the author on what to keep doing.
- **Don't review red CI** unless explicitly asked — fix or wait for green first.
- **Timebox large PRs.** If a diff is too big to review well, that's itself the feedback: ask for it to be split.
