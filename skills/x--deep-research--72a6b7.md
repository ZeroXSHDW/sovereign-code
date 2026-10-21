---
name: deep-research
description: Multi-source parallel research orchestration — decompose a question, fan out searches across the web, the local codebase, and docs, read the best sources, refine on gaps, and synthesize a cited answer. Use when the user asks to research a topic, investigate how something works, compare options (X vs Y), survey a landscape, dig into a question, or produce a well-sourced write-up that no single search answers.
---

# Deep Research

A disciplined loop for answering a question that no single search can: **decompose
→ fan out → read → refine → synthesize**. The value is in triangulating multiple
independent sources and iterating until you're actually confident — not in dumping
the first page of search results.

Built on two primitives already in this repo:

- **`web-search`** skill — find pages by keyword query.
- **`web-fetch`** skill — pull the readable content of a specific URL.

Plus ordinary local tools for code and files: `ripgrep` (`rg`), `git grep`, `find`,
and `Read`. For query craft across any corpus, lean on the sibling
**`search-strategy`** skill.

## When to Use

| Use it when | Skip it when |
|-------------|--------------|
| The question needs context from several sources (web + code + docs) | The answer is a single lookup you already know where to find |
| "Compare X vs Y", "what's the latest on X", "how does X work" | It's a trivial follow-up in the current conversation |
| A claim needs corroboration before you act on it | You're being asked to *do* something (write/edit code), not *find* something |
| You're unsure and want to verify before asserting | The answer is already in front of you |

If the goal is specifically to *verify a claim* rather than *learn a topic*, use the
**`fact-check`** skill instead (it's the verification-focused sibling of this one).

## Step 1: Decompose the Question

Break the question into 2–4 **specific sub-queries**, each targeting a different
facet. Generic questions get generic answers; specific sub-queries get sources.

| Facet | Sub-query shape |
|-------|-----------------|
| **What is it?** | definition, overview, canonical name |
| **How does it work?** | architecture, implementation, internals |
| **Who uses it / how?** | adoption, case studies, real configs |
| **How does it compare?** | alternatives, tradeoffs, benchmarks |

Write the sub-queries down before searching. They become your fan-out plan and, later,
the section headings of your synthesis.

## Step 2: Pick Sources per Sub-query

Match each sub-query to the source most likely to hold the answer. Don't search every
source for every sub-query.

| Source | Tool | Best for |
|--------|------|----------|
| **Public web** | `web-search` → `web-fetch` | Definitions, docs, comparisons, current state of the art |
| **Local codebase** | `rg`, `git grep`, `Read` | How *this* project actually does it — configs, call sites, contracts |
| **Local docs / notes** | `rg` over `docs/`, `*.md`, READMEs | Design decisions, runbooks, prior write-ups in the repo |
| **Team knowledge / chat** | your team's chat-search or wiki tool | Recent decisions, "why did we do it this way", known gotchas |

## Step 3: Fan Out in Parallel

Independent sub-queries have no dependencies between them — run them concurrently.
Two ways, depending on scale:

**Lightweight (1–3 sub-queries):** issue the searches yourself in a single batch, then
fetch the top hits.

```bash
# Fan out three keyword searches at once (each is independent)
{web-search}/search.js -n 5 "raft consensus leader election"
{web-search}/search.js -n 5 "raft vs paxos tradeoffs"
rg -n "raft|consensus|election" --type go ./internal
```

**Heavyweight (a broad landscape, or each leg needs its own read+summarize):** spawn one
sub-agent per sub-query so each does its own search → fetch → summarize and returns only
the distilled findings. Give each sub-agent: (1) the sub-query, (2) exactly what facts to
extract, (3) the format to return (bullets with source URLs/paths).

Rule of thumb: parallelize when legs are independent (comparison, landscape survey);
stay sequential when each step depends on what the last one found (a focused deep dive).

## Step 4: Read the Best Sources

For each promising hit:

1. `web-fetch <url>` to read the full text; `--raw` when you need tables/structured
   data, `--links` to find the real page behind a landing page.
2. Prefer **primary sources** — official docs, the project's own README/source, spec
   or standard, the paper itself — over blog summaries of them.
3. Record the URL/path **and the date** for every fact you'll cite. Recency matters;
   a 2-year-old answer in a fast-moving area may be stale.
4. Pick the 2–3 most authoritative sources per sub-query. Don't fetch ten pages.

Credibility ladder (highest first): official docs / source code → standards & papers →
reputable engineering blogs → Q&A sites (check date + votes) → forum/thread opinions.

## Step 5: Iterate Until Confident

This is the loop that separates deep research from a single search pass.

```
LOOP (max ~2–3 refinement rounds):
  1. Lay findings against the original question. What's still missing or contradictory?
  2. If a gap exists → formulate a REFINED query using terminology you just learned
     (canonical names, version numbers, exact identifiers), and search again.
  3. If sources disagree → seek a tiebreaker: go to the most primary source, or find
     a third independent source.
  4. If confident and sources converge → exit and synthesize.
STOP when: sources converge, OR 2–3 rounds yield diminishing returns (say so explicitly).
```

Confidence checklist before exiting:
- [ ] Every claim in the answer is backed by at least one source (2+ for anything contested).
- [ ] I searched for *contradictions*, not just confirmations.
- [ ] I noted the recency of time-sensitive facts.
- [ ] Remaining unknowns are named, not hidden.

## Step 6: Synthesize a Cited Answer

Never hand back raw search results — always distill.

```markdown
## <the question, answered in one line up top>

<2–4 short paragraphs or sections mirroring your sub-queries, each claim cited inline>

### Sources
- <url or path> — what it contributed
- <url or path> — what it contributed

### Confidence: High / Medium / Low
<why — source agreement, recency, primary vs secondary>

### Gaps
- <what you couldn't find or verify, and where you'd look next>
```

When sources conflict, say so and state which you trust more and why (e.g. "the source
code shows X; a 2024 blog claims Y — trusting the source").

## Tips

- **Decompose before you search.** A vague question searched verbatim returns vague pages.
- **Parallelize independent legs, serialize dependent ones.** Comparison → parallel; deep dive → sequential.
- **Primary sources first.** Read the docs/source/paper, not a blog's summary of them.
- **Triangulate.** Never let a single blog post be ground truth — confirm across 2–3 sources.
- **Refine with learned vocabulary.** Your second query should use the exact terms the first one taught you.
- **Cap refinement at 2–3 rounds.** Past that, report what you have and name the gaps.
- **Cite everything, date time-sensitive facts, and surface uncertainty** rather than papering over it.
