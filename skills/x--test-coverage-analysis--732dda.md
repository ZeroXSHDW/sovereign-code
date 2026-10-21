---
name: test-coverage-analysis
description: Read and act on test-coverage reports and CI test-run results — interpret line/branch and new-code coverage, understand coverage gates/regressions, root-cause a failed CI run, and prioritize which gaps actually matter by risk. Use when given a coverage report or CI test-run URL, when a coverage gate fails, when tests are red in CI, or when asked "what should I test" / "why did this run fail".
---

# Coverage and Test Reports

Two related jobs: **reading a coverage report to decide where to add tests**, and
**reading a failed CI test run to find the root cause**. The unifying principle
for both: **chase risk, not a percentage.** 100% coverage of trivial code and a
green-after-retry flaky suite are both illusions of safety.

## Part 1: Reading Coverage Reports

### Metrics — what they actually tell you

| Metric | Means | Watch out for |
|--------|-------|---------------|
| **Line coverage** | % of lines executed by tests | A line can run without its behavior being asserted |
| **Branch coverage** | % of decision paths (if/else, switch) taken | Far more honest than line coverage for logic |
| **New-code / diff coverage** | Coverage of lines *changed in this PR* | The metric most gates enforce — it stops fresh gaps |
| **Method/function coverage** | % of functions entered at all | Coarse; a called-once function reads as "covered" |

**Coverage proves code *ran*, not that it was *checked*.** A test that exercises
a line but asserts nothing still counts. Read coverage as "where are we
definitely blind," not "where are we safe."

### Gates and regressions

- A **coverage gate** blocks a change when a metric falls below a threshold —
  most commonly **new-line coverage on the diff** (e.g. "90% of changed lines
  must be covered"). This is usually the actionable failure.
- A **regression** = overall coverage dropped vs. the baseline. Often it's not
  new untested code but *deleted tests* or *moved code* — check the diff before
  writing new tests.
- **Exclusions** matter: generated code, DTOs/models, error classes, and DI
  wiring are commonly excluded and don't count toward the gate. Confirm what's
  excluded before chasing a number.

### Workflow: a gate failed on new-code coverage

1. **Read the summary** — which metric failed, threshold vs. actual.
2. **List the exact uncovered new lines** — the report should name files and
   line numbers on the diff. That's your precise to-do list.
3. **Open each uncovered file** and read the uncovered lines *in context* — is it
   real logic (needs a test) or a trivial/guard line (candidate for exclusion)?
4. **Write tests for the logic**, targeting branches, not just line hits.
5. Re-run and confirm the gate clears.

### Workflow: improving overall coverage (no gate)

1. **Summary** → overall line/branch numbers.
2. **Worst files by missed lines** → but re-rank by *risk*, not raw count.
3. **Drill into the highest-risk files** and add branch-covering tests.

### Prioritize by risk, not by chasing 100%

Rank coverage gaps by **impact × likelihood of a bug**, not by line count:

| Prioritize (test these first) | Deprioritize |
|-------------------------------|--------------|
| Core business logic, money/auth/data-integrity paths | Getters/setters, `toString`, boilerplate |
| Complex branching, error handling, edge cases | Auto-generated code, simple DTOs |
| Code that changed recently / churns often | Stable code untouched for years |
| Public API / integration boundaries | Trivial one-line delegators |

A well-tested 75% on the critical paths beats 95% padded with trivial-getter
tests. Stop when the *remaining* gaps are low-risk.

## Part 2: Reading a Failed CI Test Run

### Triage order

1. **Summary first** — status (`SUCCEEDED`/`FAILED`/`TIMED_OUT`/`CANCELLED`),
   total vs. failed count, duration.
   - 1 failure in hundreds → suspect flaky, but still investigate.
   - Many unrelated failures → suspect infrastructure, not your code.
   - Unusually long / timed out → resource contention or a hung dependency, not necessarily a logic bug.
2. **Find the first failure.** Search logs for `FAILED|ERROR|Exception|AssertionError`.
   Later failures are often cascades of the first.
3. **Read the top stack frame in your own code** — not the framework internals.
4. **Check artifacts** (JUnit XML, result files, screenshots) for the precise
   assertion and expected-vs-actual.

### Failure-pattern cheat sheet

| Signal in logs | Likely cause |
|----------------|--------------|
| `AssertionError` / comparison failure | Real logic bug, or a stale test expectation |
| `SocketTimeout` / connection refused | Downstream service or network — often not your code |
| `OutOfMemoryError` | Resource leak or test data too large |
| Dependency/version errors (`NoSuchMethod`, `ClassNotFound`, resolution failures) | Build/version mismatch, not a test bug |
| Passes on retry / only fails in CI | Flaky: timing, shared state, test ordering, real network, timezone/locale |
| Many unrelated suites fail at once | Infrastructure/env problem |

### Deterministic vs. flaky

- **Deterministic:** reproduce locally with the *same* runtime version; bisect if
  unsure which commit broke it. Fix the root cause.
- **Flaky:** passes on retry or only fails in CI. **Re-running is a deferral, not
  a fix.** Quarantine it and file a follow-up; don't let it mask the next real
  break. Common roots: timing/sleep assumptions, shared state between tests, test
  ordering, real network calls, timezone/locale.

## Tips

- **Coverage measures execution, not verification.** A line that ran with no assertion is still a blind spot — read the tests, not just the number.
- **New-code / diff coverage is the gate that matters most** — it stops fresh gaps and is the most actionable failure to fix.
- **Chase risk, not 100%.** Test money/auth/data-integrity and complex branches; skip getters and generated code. Well-covered critical paths beat a padded overall number.
- **A coverage regression is often deleted/moved tests**, not new untested code — check the diff before writing anything.
- **First failure, in your own code.** Read from the top of the stack in your code; later failures are usually cascades.
- **Re-running a flaky test is not a fix.** Quarantine and file a follow-up so it can't hide the next real failure.
- **Many unrelated failures ≈ infrastructure.** Don't debug your logic when the whole suite fell over.
