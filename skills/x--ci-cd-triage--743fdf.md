---
name: ci-cd-triage
description: Diagnose failing CI/CD pipelines — builds, tests, and deployments. Use when a build is red, a deploy failed or is stuck, tests fail in CI but pass locally, or the user asks to investigate a pipeline failure. Provides a structured triage playbook for GitHub Actions, GitLab CI, Jenkins, and similar.
---

# CI/CD Triage

A structured playbook for diagnosing failing continuous-integration and
deployment pipelines. Tool-agnostic — the flow is the same whether it's GitHub
Actions, GitLab CI, Jenkins, CircleCI, or a homegrown pipeline. Examples use the
[`gh` CLI](https://cli.github.com/); swap in your provider's CLI/API as needed.

## Step 0: Classify the Failure First

Don't read logs blindly. Identify *which stage* failed — the fix strategy is
completely different per stage:

| Stage | Symptom | Where the bug usually is |
|-------|---------|--------------------------|
| **Build / compile** | Won't compile, dependency resolution fails | Source, dependency versions, lockfile drift |
| **Test** | Compiles, tests fail | The change under test, or a flaky/environment-dependent test |
| **Package / publish** | Artifact build or upload fails | Build config, registry auth, versioning |
| **Deploy** | Artifact is fine, rollout fails | Infra config, env vars/secrets, capacity, health checks |
| **Infra / provisioning** | IaC apply fails (Terraform/CloudFormation/CDK) | Resource config, permissions, quotas, drift |

## Step 1: Find the Failing Run

```bash
gh run list --branch <branch> --limit 10          # recent runs
gh run view <run-id>                              # summary: which jobs failed
gh run view <run-id> --log-failed                 # logs for only the failed steps
gh pr checks <pr-number>                          # CI status on a PR
```

Get to the **first** failing step. Later failures are often just cascades from
the first one.

## Step 2: Read the Log From the Bottom Up

The real error is usually near the end, but *above* the final "job failed"
noise. Look for:

- The first line containing `error`, `ERROR`, `FAILED`, `Exception`, `panic`, non-zero `exit code`.
- Stack traces — read the **top** frame in your own code, not the framework internals.
- "Caused by:" / "The above exception was the direct cause of" chains — follow to the root.

```bash
# Pull the failed logs and scan for the first hard error
gh run view <run-id> --log-failed | grep -n -iE "error|failed|exception|exit code|panic" | head -20
```

## Step 3: Triage by Stage

### Build failures
- **Dependency drift** — lockfile out of sync with manifest. Regenerate the lockfile, or pin the version. Compare `git diff` on the manifest/lockfile.
- **Version conflict** — two deps demand incompatible transitive versions. Check the resolution error for the conflicting pair.
- **Works locally, fails in CI** — almost always an environment difference: language/runtime version, missing system package, case-sensitive filesystem (Linux CI vs macOS local), or an uncommitted file.

### Test failures
- **Deterministic failure** — reproduce locally with the *same* runtime version. Bisect if it's unclear which commit broke it: `git bisect`.
- **Flaky test** — passes on retry, or fails only in CI. Suspects: timing/sleep assumptions, shared state between tests, test ordering, real network calls, timezone/locale. Quarantine and file a follow-up rather than blindly re-running.
- **Only fails in CI** — parallelism (tests colliding on shared resources), missing fixture/seed data, or an env var set locally but not in CI.

### Deployment failures
- **Health check fails after deploy** — the artifact is fine but the app won't come up. Check app logs on the target, not the deploy logs. Common causes: missing/renamed env var or secret, bad config, failed migration, port mismatch.
- **Stuck / timed out rollout** — capacity (no healthy hosts, quota), a readiness probe that never passes, or a dependency the new version needs that isn't there yet.
- **Rollback loop** — new version crashes on boot; the orchestrator rolls back. Get the crash log from the first failed instance.

### Infra / IaC failures
- **Permission denied** — the CI role lacks an IAM/RBAC permission the change now needs. Read the exact denied action from the error.
- **Quota / limit exceeded** — request a limit increase or reduce the footprint.
- **Drift** — the live resource was changed out-of-band and no longer matches state. Reconcile before re-applying.

## Step 4: Reproduce Locally When Possible

The fastest fixes come from reproducing outside CI:

```bash
# Match the CI runtime version exactly (nvm/pyenv/rbenv/etc.)
# Run the exact failing command from the workflow file
# For container-based CI, run the same image locally:
docker run --rm -it -v "$PWD":/w -w /w <ci-image> bash -c "<the failing command>"
```

## Step 5: Fix, Verify, and Guard

1. **Fix the root cause, not the symptom.** Re-running until it's green isn't a fix.
2. **Verify** by re-running the exact failed step locally, then in CI.
3. **Guard against recurrence** — if it was flaky, deflake or quarantine with a tracking issue. If it was config drift, add a check. If it was a missing env var, document it in the pipeline config.

## Tips

- **Classify before you read logs.** Knowing it's a *deploy* failure vs a *test* failure saves you from reading the wrong 2,000 lines.
- **First error, not last.** Scroll up from the bottom to the first hard error — everything after is usually noise.
- **"Works on my machine" = environment diff.** Chase runtime version, OS, filesystem case sensitivity, and env vars.
- **Re-running a flaky test is not a fix** — it's a deferral. Note it, quarantine it, and file the follow-up.
- **Read app logs for deploy failures, not pipeline logs.** The pipeline just reports that health checks failed; the app knows why.
