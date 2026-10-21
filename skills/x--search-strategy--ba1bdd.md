---
name: search-strategy
description: How to search effectively across any corpus — code, docs, and chat/knowledge bases. Pick the right source for the question, craft precise queries, iterate (broaden/narrow), apply structural filters (path/lang/date/author), and know when to switch from keyword to semantic search. Use when a search returns too many or zero results, when you're unsure which tool to search with, or when you need to find code, docs, or discussions efficiently.
---

# Search Strategy

A tool-agnostic method for finding things fast in any corpus. The moves are the same
whether you're using `ripgrep`, `git grep`, GitHub code search, a docs site, or a
team chat search — only the syntax changes. The core loop:

**pick the source → craft a precise query → iterate (broaden/narrow) → filter structurally → switch modes if stuck.**

## Step 1: Pick the Right Source

The single biggest time-saver is searching the *right corpus* first.

| You want… | Search… | With |
|-----------|---------|------|
| How *this* project does X | The local codebase | `rg`, `git grep` |
| How *anyone* does X, examples in the wild | Public code | GitHub code search |
| What a tool/API/service does | Official docs | docs site search, `web-search` skill |
| A design decision or "why did we do this" | Project docs / notes / commit history | `rg` over `docs/`, `git log --grep` |
| A recent decision, announcement, or gotcha | Team chat / knowledge base | your team's chat/wiki search |
| Whether something even exists | Package registry / repo search | registry search, GitHub repo search |

If unsure, start with the broadest source, see where the good hits come from, then
re-search that source specifically.

## Step 2: Craft a Precise Query

Good queries are **specific and short**. Search engines rank on relevance; you supply
distinctiveness.

- **Use the most distinctive token** — an exact identifier, error string, or symbol name
  beats a generic word (`"connectWithRetry"` beats `retry`).
- **Quote multi-word / exact phrases** — otherwise most engines OR the words:
  `"connection reset by peer"`, `"class RetryPolicy"`.
- **Keywords, not sentences** — `raft leader election timeout` not `how does leader
  election work in raft`. (Full-sentence questions are for semantic search — see Step 5.)
- **Add a version or year for fast-moving topics** — `tokio select 2024` filters stale hits.
- **Match how it appears in the corpus** — search `def process_order` for a Python
  definition, `import process_order` for its call sites, `class Foo` for a type.

## Step 3: Iterate — Broaden or Narrow

Almost never nail it on the first query. Read the result count and adjust:

| Symptom | Move | How |
|---------|------|-----|
| **Zero results** | Broaden | Drop a term, remove quotes, try a synonym or the canonical name, search a wider scope |
| **Thousands of results** | Narrow | Add a distinctive term, quote a phrase, add a path/lang filter, scope to one dir/repo |
| **Wrong kind of hit** | Redirect | Exclude noise (`-test`, `-vendor`), switch definition↔usage phrasing |
| **Right area, missing the exact line** | Zoom | Search within the found file/dir; widen to see surrounding context (`-C`) |

Rule of thumb: **start narrow, broaden only on zero results.** A broad-then-narrow sweep
wastes time wading through noise.

## Step 4: Use Structural Filters

Filters cut the corpus before matching — the highest-leverage way to kill noise.

**ripgrep (local):**
```bash
rg "RetryPolicy" --type py                 # language/type filter
rg "RetryPolicy" -g '!**/test/**'          # exclude a path glob
rg "RetryPolicy" -g '*.go' src/            # glob + directory scope
rg -n -C3 "backoff"                        # line numbers + 3 lines of context
rg -i "timeout" --stats                    # case-insensitive + match stats
```

**git grep (tracked files / history):**
```bash
git grep -n "RetryPolicy" -- 'src/**/*.ts'         # path-scoped, tracked files only
git grep -n "backoff" $(git rev-list --all)        # search all of history
git log -S "RetryPolicy" --oneline                 # commits that added/removed the string
git log --grep="retry" --oneline                   # commits whose message mentions it
```

**GitHub code search (public code):**
```
RetryPolicy language:go                    # language filter
"maxAttempts" repo:org/name                # scope to one repo
backoff path:src/ NOT path:test            # path include / exclude
retryPolicy org:some-org stars:>500        # org + popularity filter
```

**Docs / chat / knowledge bases** — the concepts port even when syntax differs:
- **Scope**: restrict to a section/channel/space (`in:#channel`, a docs path prefix, a site: filter).
- **Author**: `from:@person` / `author:` narrows to a known expert.
- **Date**: `after:2024-01-01` / sort-by-recency surfaces current answers over stale ones.
- **Exact phrase**: quote multi-word identifiers so they aren't tokenized apart.

## Step 5: Keyword vs Semantic — Know When to Switch

| Use **keyword / regex** search when | Use **semantic / natural-language** search when |
|-------------------------------------|--------------------------------------------------|
| You know an exact token: symbol, error string, filename, config key | You don't know the vocabulary the corpus uses |
| You need every literal occurrence (refactor, audit) | You want *conceptually* related material, not literal matches |
| Precision matters more than recall | The idea can be phrased many ways ("auth" vs "login" vs "session") |
| Corpus is code or structured text | Corpus is prose, tickets, docs, chat |

If keyword search keeps returning zero because you're guessing the wrong word, **stop
guessing and go semantic** (or vice-versa: if semantic search returns fuzzy junk and you
actually know the exact string, switch to grep). A common winning combo: semantic search
to discover the real identifier, then keyword search on that identifier for every hit.

## Worked Examples

**"Find who implements `OrderValidator`" (local):**
```bash
rg -n "class OrderValidator" --type py          # the definition
rg -n "OrderValidator\(" -g '!**/test/**'       # instantiation / call sites
```

**"Does anyone in the org call the deprecated `oldAuth()`?" (public code):**
```
"oldAuth(" org:my-org language:typescript NOT path:test
```

**"When and why was this retry cap changed?" (history):**
```bash
git log -S "maxAttempts" --oneline -- src/retry.ts   # commits touching that literal
git show <sha>                                       # read the change + message
```

## Tips

- **Right source first.** Searching the wrong corpus perfectly still fails — pick the corpus before the query.
- **Distinctive token wins.** One exact identifier beats five generic words.
- **Quote multi-word identifiers** so the engine doesn't OR them apart.
- **Start narrow; broaden only on zero results.** Don't wade through 10k hits by choice.
- **Filters before terms.** Path/lang/date filters cut noise faster than more keywords.
- **Switch modes when stuck.** Keyword for known strings, semantic for unknown vocabulary — flip if one keeps failing.
- **Definition vs usage are different queries.** `class Foo` finds the type; `Foo(` / `import Foo` finds callers.
