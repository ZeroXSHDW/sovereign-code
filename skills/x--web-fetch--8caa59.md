---
name: web-fetch
description: Fetch a web page and extract readable text content. Use when the user needs to retrieve or read a public web page, documentation, blog post, or any external URL.
---

# web-fetch

Fetch a public web page and extract readable text — a self-contained Node
script with **zero dependencies** (built-in `fetch`, Node 18+).

## Usage

```bash
{baseDir}/fetch.js <url>
{baseDir}/fetch.js <url> --raw
{baseDir}/fetch.js <url> --links
```

| Flag | Description |
|------|-------------|
| `<url>` | URL to fetch (required) |
| `--raw` | Output raw HTML instead of extracted text |
| `--links` | List every link on the page as `text -> absolute-href` |

## Examples

```bash
# Extract readable text (strips scripts, nav, header/footer, boilerplate)
{baseDir}/fetch.js https://nodejs.org/api/fetch.html

# Raw HTML (for parsing structured data, tables, or embedded JSON)
{baseDir}/fetch.js https://example.com --raw

# Enumerate links (relative hrefs are resolved to absolute)
{baseDir}/fetch.js https://example.com --links

# Only need the top of a long page
{baseDir}/fetch.js https://example.com | head -n 60
```

## Tips

- Default mode extracts article/main content — good for docs, blog posts, READMEs.
- Use `--raw` when you need HTML structure (links, tables, forms, embedded JSON).
- Use `--links` to crawl or to find the real URL behind a landing page.
- Pair with the **web-search** skill: search for a page, then fetch it in full.

## Requirements

- Node.js 18+ (uses the global `fetch`). No `npm install` needed.
