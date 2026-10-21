---
name: git-workflow
description: Git and GitHub pull-request workflow. Branching, conventional commits, rebasing, conflict resolution, and creating/updating PRs with the gh CLI. Use when the user asks about git strategy, branch management, rebasing, conflict resolution, or opening a pull request.
---

# Git & PR Workflow

A clean, reviewable git workflow built around short-lived feature branches and
GitHub pull requests via the [`gh` CLI](https://cli.github.com/).

## Branch Strategy

```bash
# Check current state
git branch -a
git log --oneline -10
git status

# Create a feature branch off the default branch
git switch main
git pull
git switch -c feat/my-feature

# Switch back to the trunk
git switch main
```

- **main** (or `master`/`trunk`) — always deployable.
- **feat/**, **fix/**, **refactor/**, **chore/** — short-lived branches, one per unit of work.
- Merge via PR approval, not local `git merge` into main.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): add new feature
fix(scope): fix bug description
refactor(scope): restructure code
docs(scope): update documentation
test(scope): add/update tests
chore(scope): maintenance tasks
```

Examples:

```bash
git commit -m "feat(api): add retry logic for rate-limited requests"
git commit -m "fix(handler): correct null check in enrichment step"
git commit -m "refactor(client): extract HTTP call into wrapper"
git commit -m "chore(deps): bump axios to 1.7.5"
```

## Staging and Committing

```bash
git add -A                       # stage everything
git add src/handler.ts           # stage a specific file
git add -p                       # interactive hunk staging
git commit -m "feat: description"
git commit --amend               # fix the last commit before pushing
```

## Opening a Pull Request

Push the branch, then create the PR with `gh`:

```bash
git push -u origin feat/my-feature

# Interactive
gh pr create

# Non-interactive with a full body
gh pr create --title "feat(api): add retry logic" --body "$(cat <<'EOF'
## Problem
Requests fail hard when the upstream returns 429.

## Solution
Add exponential backoff with jitter, capped at 5 attempts.

## Testing
- Unit tests for the backoff schedule
- Manual test against the staging endpoint
EOF
)"

# Open as a draft
gh pr create --draft --title "wip: spike retry logic"
```

## Updating an Existing PR

Just push more commits to the same branch — the PR updates automatically:

```bash
git add -A
git commit -m "fix: address review comment on jitter bounds"
git push
```

To keep history clean, amend or squash **before** pushing (see Rebase below).
Avoid rewriting history that others may have pulled.

## Reviewing PR State

```bash
gh pr status                     # PRs relevant to you
gh pr view                       # current branch's PR
gh pr view 123 --comments        # a specific PR with comments
gh pr checks                     # CI status for the current PR
gh pr diff                       # the PR diff
```

## Conflict Resolution

```bash
# Rebase your branch onto the latest main
git fetch origin
git rebase origin/main

# Find conflicted files
git diff --name-only --diff-filter=U

# After resolving each file
git add <resolved-file>
git rebase --continue
```

When resolving conflicts:
1. Read both sides of the conflict.
2. Understand the intent of each change.
3. Resolve with minimal edits that preserve both intents.
4. Re-run the build/tests after resolution.

## Interactive Rebase

Clean up commits before opening or updating a PR:

```bash
git rebase -i HEAD~3             # last 3 commits
git rebase -i origin/main        # everything since main
```

Common operations: **squash** (combine), **reword** (fix message),
**drop** (remove), **edit** (stop to amend).

After rewriting history on a branch that's already pushed:

```bash
git push --force-with-lease      # safer than --force
```

## Useful Commands

```bash
git diff main --stat             # what changed vs main
git log main..HEAD --oneline     # commits on this branch
git log --format='%an' -5 -- <file>   # recent authors of a file
git log HEAD..origin/main --oneline    # am I behind main?
git stash && git stash pop       # shelve/unshelve changes
git switch -                     # jump back to previous branch
```

## Tips

- **`--force-with-lease`, never `--force`** — it refuses to clobber commits you haven't seen.
- **Rebase onto main before opening a PR** — reviewers see a clean, current diff.
- **One logical change per PR** — smaller PRs get reviewed faster and merge cleaner.
- **Let CI gate the merge** — check `gh pr checks` before requesting review.
