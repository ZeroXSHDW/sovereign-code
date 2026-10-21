---
name: fact-check
description: Verify a claim or assertion against multiple independent sources and return a structured verdict (Supported / Refuted / Partially-supported / Unverifiable) with confidence and citations. Use when the user says "verify that…", "is it true that…", "confirm…", "double-check…", "fact-check this", when a claim needs corroboration before you act on it, or before asserting something you're not certain of.
---

# Fact Check

Verify claims by corroborating them across **multiple independent sources**, then
return a structured verdict with an evidence chain. The discipline is: don't trust one
source, prefer primary sources, and actively hunt for contradictions — not just
confirmations.

This is the verification-focused sibling of the **`deep-research`** skill. Where
deep-research *learns a topic*, fact-check *adjudicates a claim*. Use **`web-search`**
and **`web-fetch`** as the discovery/extraction primitives, and **`search-strategy`**
for query craft.

## Proactive Verification (the default posture)

**Before asserting anything you're not sure of, verify it first.** A 10-second search is
cheaper than a confident wrong answer. Verify proactively when:

- You're about to state a fact, version number, API signature, or behavior as true and
  haven't confirmed it this session.
- You're recommending a pattern or config you've "seen before" but aren't 100% current on.
- The topic moves fast (library APIs, pricing, released features) so training data may be stale.
- The claim will be acted on externally (shared with stakeholders, put in a doc, shipped in code).

Skip verification only for general knowledge, things already established in this session,
or trivial operations.

## Step 1: Extract the Checkable Claim

Restate the assertion as something **specific and falsifiable**, then break it into
independent sub-claims if it bundles several facts.

> Claim: "Library X's default retry policy backs off exponentially and caps at 5 attempts."
> Sub-claims:
> 1. X retries by default (retries are on unless disabled).
> 2. The backoff is exponential (not fixed/linear).
> 3. The attempt cap is 5.

Each sub-claim should be independently verifiable — one failing shouldn't invalidate the
others.

## Step 2: Find 2+ Independent Sources per Sub-claim

**Rule: a "Supported" verdict needs at least 2 *independent* sources that agree.** Two
blog posts that both cite the same original aren't independent — trace to the origin.

| Source type | Where | Best for |
|-------------|-------|----------|
| **Primary / official** | official docs, spec, standard, the paper | Intended behavior, canonical definitions |
| **Source code** | the project's repo (`web-fetch` a file, or `rg` locally) | What it *actually* does, vs what docs claim |
| **Runtime evidence** | run it, read logs/output, a test | Ground truth for "does it behave this way" |
| **Reputable secondary** | maintainer blog, changelog, release notes | Corroboration, history, rationale |
| **Community** | Q&A sites, issue trackers, team chat | Edge cases, known bugs, gotchas docs omit |

Prefer primary over secondary. When intent and implementation might differ (docs say one
thing, code does another), **check both** — that gap is often the real answer.

## Step 3: Cross-Check (confirm *and* refute)

For each sub-claim, gather evidence from independent sources. Run independent checks in
parallel when they don't depend on each other:

```bash
# Confirm behavior from the docs, and independently from the source
{web-search}/search.js -n 5 "libraryX retry policy default exponential backoff"
{web-fetch}/fetch.js https://github.com/org/libraryX/blob/main/src/retry.ts --raw
rg -n "maxAttempts|backoff|retry" ./node_modules/libraryX/dist   # runtime truth locally
```

Actively search for the *counter*-claim ("libraryX retries disabled by default",
"libraryX backoff is fixed"). If you only look for confirmation, you'll find it — that's
confirmation bias, not verification.

## Step 4: Rate and Return a Verdict

Rate each sub-claim, then roll up to an overall verdict.

| Verdict | Criteria |
|---------|----------|
| ✅ **Supported** | 2+ independent sources corroborate; no credible contradiction |
| ⚠️ **Partially-supported** | Some sub-claims hold, others don't, or only 1 source confirms |
| ❌ **Refuted** | Credible evidence contradicts the claim |
| ❓ **Unverifiable** | Insufficient/inaccessible evidence — note it; do *not* treat absence of evidence as refutation |

Overall: **Refuted** if any load-bearing sub-claim is refuted; **Partially-supported** if
mixed; **Supported** only if all hold; **Unverifiable** if too many gaps.

## Step 5: Output Format

```markdown
## Fact Check: <original claim>

**Verdict: ✅ Supported** — confidence: High / Medium / Low

### Sub-claims
| # | Sub-claim | Verdict | Sources |
|---|-----------|---------|---------|
| 1 | <claim>   | ✅ | official docs, source code |
| 2 | <claim>   | ⚠️ | one blog only |
| 3 | <claim>   | ❌ | source code contradicts |

### Evidence
**Sub-claim 1:** <finding> — <url/path>; corroborated by <finding> — <url/path>
**Sub-claim 3:** docs say 5, but `retry.ts:42` sets `maxAttempts = 3` — <url/path>

### Gaps & Caveats
- <what couldn't be verified, assumptions made, recommended follow-up>
```

## Tips

- **Two independent sources minimum** for a Supported verdict — and check they're *actually* independent, not echoes of one origin.
- **Primary over secondary.** Docs, source, spec, the paper — before anyone's summary of them.
- **Hunt contradictions.** Search the negation of the claim, not just the claim.
- **Intent ≠ implementation.** "Designed to work this way" and "actually works this way" are different checks; do both when it matters.
- **Absence of evidence isn't refutation.** If you can't find it, that's ❓ Unverifiable, stated plainly — not ❌ Refuted.
- **Date your evidence.** For fast-moving topics, note when the source was published/updated.
