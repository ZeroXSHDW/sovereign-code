---
name: web-search
description: Web search via DuckDuckGo. Use when the user needs to look up current information online, find documentation, research errors, or discover external resources.
---

# web-search

Web search via DuckDuckGo — a self-contained Node script with **zero
dependencies** (uses the built-in `fetch`, Node 18+). Use for looking up
documentation, researching errors, finding external resources, or any general
web search.

## Usage

```bash
{baseDir}/search.js "query terms"
{baseDir}/search.js -n <count> "query terms"
{baseDir}/search.js --json "query terms"
```

| Flag | Description |
|------|-------------|
| `"query"` | Search query (required) |
| `-n <count>` | Number of results to return (default: 5) |
| `--json` | Machine-readable JSON output (array of `{title, url, snippet}`) |

Returns title, URL, and snippet for each result.

## Examples

```bash
# Basic search
{baseDir}/search.js "rust tokio select macro tutorial"

# More results
{baseDir}/search.js -n 10 "AWS Lambda cold start optimization"

# Error research
{baseDir}/search.js "TypeError cannot read properties of undefined reading map"

# Pipe JSON to jq for the top URL
{baseDir}/search.js --json "postgres jsonb index" | jq -r '.[0].url'
```

## Tips

- Use specific, targeted queries — include library names, error messages, or version numbers.
- Follow up with the **web-fetch** skill to read a result page in full.
- `--json` mode composes well with `jq` when you want to feed a URL into another tool.

## Requirements

- Node.js 18+ (uses the global `fetch`). No `npm install` needed.
