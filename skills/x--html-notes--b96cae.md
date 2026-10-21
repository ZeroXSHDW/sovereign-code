---
name: html-notes
description: Use when producing specs, plans, research notes, reports, code reviews, design explorations, or interactive editors that the user will read end-to-end. Default to a single self-contained HTML file with inline CSS and (when needed) inline JS, following the Anthropic-style design system extracted from Thariq's html-effectiveness gallery. Skip this skill for short conversational replies, simple commands, or markdown source files in code repos where diff reviewability matters more than render quality.
category: writing
triggers:
  - html notes
---

# HTML Notes — Output Pattern Skill

This skill captures patterns extracted via Playwright from <https://thariqs.github.io/html-effectiveness/> (20 examples, 9 categories). When generating a "note" (spec / plan / report / research / code review / design / editor), produce a **single self-contained HTML file** following the conventions below.

**Portability principle:** this public skill must not assume a particular user, vault, bot, host, private network, or note taxonomy. Treat paths, hosted URLs, wiki routing, and companion conventions as project-specific; use placeholders like `<workspace>`, `<notes-dir>`, `<wiki-root>`, and `<served-url>` unless the current project explicitly defines them.

## When to Use This Skill

✅ **Use HTML for:**
- Specs / implementation plans / brainstorms with multiple options to compare
- Code reviews / PR writeups / module maps
- Research reports / concept explainers / weekly status / incident timelines
- Design explorations / component variants / animation sandboxes
- Custom one-off editors (triage boards, prompt tuners, config UIs)
- Conference / study notes that already exist as Markdown and would benefit from a polished reading layer
- Anything with tables, diagrams, or > 100 lines of content the user will *read*

❌ **Do NOT use HTML for:**
- Short replies, chat responses, command outputs
- Replacing the Markdown source-of-truth for live notes or wiki/vault pages
- Source files in code repos that need to diff cleanly in git
- Plain data dumps that have no narrative
- Chat-platform messages (chat has its own formatting and length constraints)

## Anti-Patterns to Avoid

Per Thariq: *"I'm a little bit afraid that people will read this article and turn it into a /html skill."* The risk is mechanical overuse. Guardrails:

- **Do not** wrap one-paragraph answers in HTML scaffolding
- **Do not** generate HTML when a markdown file in the repo is the right artifact
- **Do prefer** markdown when the file lives in git and reviewers diff-read it
- **Default to HTML only** when the user reads the artifact rendered (private HTTP server, browser, S3/static-host link)

## Markdown Notes → HTML Reading Layer

When asked to "turn notes into HTML" or when a live conference/study note is created:

1. **Preserve Markdown as source of truth.** Do not replace or delete the `.md`; the Markdown remains best for wiki links, workspace search, live editing, grep, and future patches.
2. **Generate HTML by default for every substantive wiki note** when the project uses rendered reading layers — conference notes, concept notes, career/strategy notes, design decisions, research writeups. The artifact pair is `<dir>/<slug>.md` plus `<dir>/_html/<slug>.html`. **The `_html/` folder MUST be a sibling of the markdown's OWN directory** — `notes/concepts/foo.md` pairs with `notes/concepts/_html/foo.html`, not a distant parent `_html/` directory; many wiki/static-site routers only check the sibling path, so misplaced companions may silently fail to pair. Exception: MOC/index/navigation pages stay markdown-only — they change with every new note and a rendered companion goes stale immediately. Do not wait for a second prompt unless the user explicitly says markdown-only.
3. **Generate HTML as a rendered reading layer.** Prefer a sibling served/rendered path such as `<notes-dir>/_html/<same-slug>.html` for workspace notes unless the user specifies another location.
4. **Keep the note language and structure.** Convert the existing sections faithfully; do not invent new claims while rendering. Improving layout is allowed; changing the underlying content is not.
5. **Use conference-note affordances:** left/table-of-contents navigation, `The whole talk in N lines`, concept cards, collapsed deeper sections, open threads, related links, and optional SVG diagrams when they clarify the system.
   - For live notes, treat the top SVG as a living synthesis artifact. When later slides reveal the final primitive set, causal chain, or architecture, rewrite the hero diagram rather than leaving an earlier generic diagram in place.
6. **QA both desktop and mobile.** At minimum verify file existence, self-contained HTML, viewport meta, no external dependencies, key sections present, served URL returns 200, Listing routes prefer the HTML when applicable, and no horizontal overflow at desktop and ~390px mobile width.
7. **Report both artifacts and the browser-openable URL.** Tell the user the `.md` remains the source and provide the generated `.html` path **plus a browser-openable dashboard or static-server URL** when available. Do not stop at `file://` links when the user needs to open the artifact on another device. If a dashboard/static server is already reachable, verify the served HTML URL returns 200 and give that link. If no dashboard/wiki server is reachable but the artifact lives under `<wiki-root>`, use the ad-hoc static-server fallback in `references/ad-hoc-static-server.md`: bind to a reachable host/interface, serve the chosen URL path convention, verify `curl -I` returns 200, then give the browser-openable URL.
8. **For synthesized strategy/concept notes, include one diagram by default unless it would be a disguised list.** If the note distills a framework, career strategy, architecture, system map, workflow, or causal model, add a relationship-bearing inline SVG diagram near the top that captures the TL;DR. Follow `references/diagram-standard.md`: nodes need title + payload, edges need verbs, one focal node, and mobile horizontal scroll. Do not wait for the user to ask “没有diagram么”.
9. **Link back to raw Markdown from every HTML companion.** Add a visible link near the header such as `View raw Markdown source →` pointing to `<served-md-url>`, so the polished reading layer never hides the editable/source note.
10. **Keep generated HTML patchable.** Conference-note HTML is a living artifact during a live session, so write it with stable section boundaries, readable line breaks around concept cards/details blocks, and non-minified major sections. Avoid making the whole body one giant line: later slide-photo patches must be surgical and reliable.
## Cross-skill trigger pitfall

If another note-taking skill (`study-notes`, `podcast-notes`, career/conference note capture) is already loaded and the task creates a substantial HTML reading layer, load and apply `html-notes` as the rendering-quality layer. Do not let the upstream note skill hand-roll a minimal HTML companion. The division of responsibility is:

- upstream note skill = what content to capture and where the Markdown source lives;
- `html-notes` = polished rendered artifact, diagram requirement, raw-source link, mobile/browser QA, and browser-openable served URL.

## Output Conventions

1. **Single file**: one `.html` with inline `<style>` and inline `<script>`. No external CSS/JS dependencies. No `<link>` to fonts (use system font stack).
2. **Self-contained**: opens correctly via `file://` and over a static HTTP server. No build step.
3. **Mobile-friendly**: include `<meta name="viewport" content="width=device-width, initial-scale=1">`; use `display: grid` with `minmax()` so it reflows under 768px.
4. **Research reports are not Q&A transcripts**: do not show the raw user prompt as the hero or first visible box for research notes. Translate the request into a professional `Research Scope`, `Question`, or `Mandate` block. If provenance matters, put the raw prompt in a collapsed appendix or HTML comment.
5. **Title = h1 + eyebrow line**: serif h1 with smaller uppercase eyebrow above (date / category / context).
6. **Save inside the active project** unless explicitly asked for a served artifact. For a shared wiki/vault, save under that workspace. Do not write into unrelated local memory directories.
7. **Public research notes require publish metadata in `<head>`**: include exactly one each of `<meta name="post:title" content="{{Title}}">`, `<meta name="post:summary" content="{{One sentence summary}}">`, `<meta name="post:published" content="{{YYYY-MM-DD}}">`, and `<meta name="post:tags" content="{{comma,separated,tags}}">`.
8. **Public-facing body copy must stay portable**: avoid absolute local file paths, wiki links, and private-only source references in visible body copy.

## Research Report Quality Bar

For investment research, strategy notes, market maps, supplier maps, and technical roadmaps, the rendered page should read like a report, not a chat answer.

Required structure:
- **Header**: eyebrow, report title, concise dek, and a small metadata panel such as `Research Scope`, `Coverage`, or `Last Updated`.
- **Key Findings**: 3-5 short findings with consistent visual weight.
- **Evidence Sections**: tables or matrices with confidence labels (`Direct`, `Strong clue`, `Ecosystem`, `Unproven`).
- **Interpretation**: explicit investment or technical read, separated from evidence.
- **Sources Appendix**: source links at the bottom.

Avoid:
- Raw prompt blocks at the top of research reports.
- Section names like `Executive answer`, `What you asked`, or other Q&A phrasing.
- Nested cards. A card inside another card is usually why boxes look misaligned.
- Long prose inside KPI tiles. Use short labels and move details into tables or normal sections.
- Tables without an overflow wrapper.

Use:
- `.table-wrap { overflow-x: auto; }` around every wide table.
- For reports that may be read on mobile, prefer responsive table-to-card rules over narrow squeezed columns. Use table-specific classes and `td:nth-child(n)::before` labels under `@media (max-width: 720px)`.
- In table-to-card mode, make each `td` `display: block` with the label in `td::before`; avoid CSS grid inside `td` because inline elements such as `<code>` can become separate grid items.
- `grid-template-columns: repeat(n, minmax(0, 1fr))` for equal columns.
- `min-width: 0`, `overflow-wrap: anywhere`, and `hyphens: auto` for panels that may contain long product names, URLs, tickers, or part numbers.
- Flat report panels (`.panel`) for analysis sections and repeated cards (`.finding`) only for small, uniform items.

## Career Strategy / Framework Notes

When capturing career advice, agent-native engineering essays, or career or strategy transition frameworks into durable notes, follow `references/career-strategy-note-pattern.md`. In short: preserve Markdown source, generate an HTML reading layer, include a relationship-bearing system-map diagram by default, update the workspace index, and report a browser-openable dashboard or static-server URL.

## Wiki Dashboard Companions

When converting workspace wiki notes into polished HTML, especially AI conference notes, keep markdown as the source of truth and write a companion HTML file instead of replacing the note. See `references/wiki-dashboard-html-companions.md` for the exact path convention, served URL pattern, and verification checklist.

### Moving or recategorizing existing notes

When moving an existing note between folders, do a small relocation audit instead of only moving the `.md` file:

1. Search by exact title, likely aliases, and distinctive phrases; a requested title may already exist under a synthesized title (for example a career-advice essay captured as a principles note).
2. Move the Markdown source and its sibling `_html/<same-stem>.html` companion together.
3. Patch the HTML companion's visible raw Markdown link from the old `/w/.../<note>.md` path to the new served path.
4. Patch backlinks that referenced the old location, especially cross-folder wikilinks and index/tracker entries.
5. For strategy notes, update any workspace index or active-artifacts list if that convention exists.
6. Verify old paths are gone when appropriate, new Markdown + HTML paths exist, and served URLs for both return 200 before reporting done.

When asked to HTML-ize a batch of conference or study notes, audit the date-scoped source notes first, then generate only missing companions. Verification must cover: no missing `_html/<same-stem>.html`, each companion has a visible raw Markdown link, each HTML is self-contained with viewport metadata, direct `<served-html-url>` URLs return 200, and directory/listing routes prefer HTML links where companions exist. Use `references/batch-conference-notes-htmlization.md` for the full audit/generate/verify workflow and the listing-route pitfall.

For conference-note diagrams, do **not** draw a table-of-contents or section-order flow. The diagram should express the talk’s core architecture / system idea: central primitive, runtime loop, cross-cutting rails, feedback loop, bottleneck, or ecosystem topology. Only use a linear diagram when the talk itself is explicitly a pipeline or staged rollout. Use `references/conference-note-architecture-diagrams.md` for the detailed pattern and examples.

For raw-note → diagram conversion, aim for a presentation overview slide in an architecture-diagram style: one thesis sentence, a central primitive/system, 4–6 surrounding components, 2–3 cross-cutting rails, and clear relationship lines. It must be understandable at a glance on mobile. Prefer the existing diagram toolchain (`mermaid-diagram` for structured architecture diagrams; `canvas-design`/frontend polish when the reader benefits from a more presentation-like visual). But do **not** stop at a simple Mermaid graph if it fails to express the note’s core meaning; the final reading-layer diagram should be visually designed as a polished overview board with pressure/failure modes, control surface, rails, and takeaway when appropriate. Do **not** hand-code wide ad-hoc SVGs unless they are visually checked and demonstrably cleaner than Mermaid. Use `references/presentation-overview-diagrams.md` for the detailed extraction schema, anti-patterns, rendering choices, and visual QA checklist.

## AI Ecosystem Company Maps

When turning conference expo maps, sponsor lists, speaker JSON, or startup logos into an AI market-map HTML note, use `references/ai-ecosystem-company-maps.md`. Key rule: do not imply the categories are a strict linear call chain; draw a runtime-loop topology with cross-cutting rails for security, evals/observability, and developer productivity.

For live conference notes specifically, if a live-note skill is also in use, ensure: every later content patch updates both Markdown and HTML, important slide frameworks stay visible (not only collapsed), and cache-busted URLs are used when the user cannot see a recent update.

For conference ecosystem / market-map notes built from expo screenshots plus official schedule data, follow `references/conference-ecosystem-map-from-expo-and-schedule.md`: combine official JSON with OCR, dedupe company names, mark OCR uncertainty, avoid overclaiming exhibitor coverage, and render a layered ecosystem diagram plus full company table.

## Browser QA Requirement

Before calling an HTML note finished:
- Open or inspect it in a browser at desktop width and a mobile width when feasible.
- Check that no text overflows outside boxes.
- Check that same-row boxes align or intentionally differ.
- Check that tables scroll horizontally on narrow screens.
- Check that the first viewport reads like a finished artifact, not a prompt replay.
- **Tag balance / layout-container integrity (bug class caught a prior layout bug):** count `<div` vs `</div>` — they must match, and in the rendered DOM the sidebar `nav` (Contents) must be a child of the `.page` grid (`document.querySelector('.page').contains(document.querySelector('nav'))`). One stray `</div>` inside `<header>` closes `.page` early, the parser hoists `nav`/`main` to `<body>`, and the sticky TOC floats full-width over the article. Editing a header section (e.g. swapping a diagram `div` for a `section`) is the typical source of the orphan closer.

## The Anthropic-Style Design System (Extracted from Thariq's Examples)

Drop this `<style>` block into every HTML note unless instructed otherwise:

```html
<style>
:root {
  /* Anthropic palette */
  --ivory:    #FAF9F5;
  --slate:    #141413;
  --clay:     #D97757;   /* primary accent */
  --oat:      #E3DACC;
  --olive:    #788C5D;   /* positive / success */
  --rust:     #B14A3A;   /* warning / negative */
  --gray-150: #F0EEE6;
  --gray-300: #D1CFC5;
  --gray-500: #87867F;
  --gray-700: #3D3D3A;
  --white:    #FFFFFF;

  --serif: ui-serif, Georgia, 'Times New Roman', serif;
  --sans:  system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --mono:  ui-monospace, 'SF Mono', Menlo, Monaco, monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--sans);
  background: var(--ivory);
  color: var(--gray-700);
  line-height: 1.55;
  padding: 56px 32px 120px;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 1120px; margin: 0 auto; }

/* Header chrome */
header.page-head { margin-bottom: 48px; max-width: 820px; }
.eyebrow {
  font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--gray-500); margin-bottom: 12px;
}
h1 {
  font-family: var(--serif); font-weight: 500; font-size: 38px;
  line-height: 1.15; color: var(--slate); margin-bottom: 18px;
  letter-spacing: -0.01em;
}
h2 { font-family: var(--serif); font-weight: 500; font-size: 24px; color: var(--slate); margin-bottom: 16px; }
h3 { font-size: 16px; font-weight: 600; color: var(--slate); margin-bottom: 10px; }

.prompt-box {
  background: var(--gray-150); border: 1.5px solid var(--gray-300);
  border-radius: 12px; padding: 16px 20px; font-size: 14.5px; color: var(--gray-700);
}
.prompt-box .label {
  font-family: var(--mono); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--gray-500); display: block; margin-bottom: 6px;
}

section { margin-bottom: 64px; }
.sec-head { display: flex; align-items: baseline; gap: 14px; margin-bottom: 16px; }
.sec-head .num {
  font-family: var(--mono); font-size: 12px; color: var(--gray-500);
}

/* Cards / panels */
.card {
  background: var(--white); border: 1px solid var(--gray-300);
  border-radius: 14px; padding: 24px;
  min-width: 0; overflow: hidden;
}
.card + .card { margin-top: 16px; }

/* Tables */
.table-wrap { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; min-width: 720px; border-collapse: collapse; font-size: 14.5px; }
th { text-align: left; font-weight: 600; color: var(--gray-500);
     font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
     padding: 12px 16px; border-bottom: 1.5px solid var(--gray-300); }
td { padding: 14px 16px; border-bottom: 1px solid var(--gray-150);
     overflow-wrap: anywhere; hyphens: auto; }

/* Status pills */
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: 11px; font-weight: 600; letter-spacing: 0.04em; }
.pill.pos { background: rgba(120,140,93,0.15); color: var(--olive); }
.pill.neg { background: rgba(177,74,58,0.12); color: var(--rust); }
.pill.warn { background: rgba(217,119,87,0.15); color: var(--clay); }
.pill.muted { background: var(--gray-150); color: var(--gray-500); }

/* Code */
pre, code { font-family: var(--mono); font-size: 13px; }
pre { background: var(--gray-150); padding: 16px; border-radius: 10px;
      overflow-x: auto; line-height: 1.5; }

/* Collapsible details */
details { background: var(--white); border: 1px solid var(--gray-300);
          border-radius: 10px; padding: 12px 16px; }
details summary { cursor: pointer; font-weight: 600; color: var(--slate); }
details[open] summary { margin-bottom: 12px; }

/* Grid layouts */
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }

/* Mobile */
@media (max-width: 720px) {
  body { padding: 32px 16px 80px; }
  h1 { font-size: 30px; }
  .page-head { margin-bottom: 32px; }
  section { margin-bottom: 40px; }
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
</style>
```

## Reading Typography — Lil'Log calibration

For long-form notes, this style replicates the comfortable reading experience of lilianweng.github.io (Hugo PaperMod). Measured from her live stylesheet — apply to the BODY TEXT of every note-style HTML (keep the Anthropic palette for chrome/accents):

- **Font**: pure system stack — `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen,Ubuntu,Cantarell,"Open Sans","Helvetica Neue",sans-serif` (renders as SF Pro on Apple devices; NO webfonts).
- **Body**: `16px / line-height 1.6`, `word-break:break-word`, near-black `#1F1F1F` text on white content surface.
- **Measure**: content column **720px max** — this narrow measure is most of the "comfortable" feel; don't let article text run 850px+ wide.
- **Paragraph rhythm**: `p { margin-bottom:20px }` (one clear gap, no indents); `li { margin-top:5px }`; lists `padding-inline-start:20px`.
- **Headings**: sans bold, modest scale — h1 28px, h2 24px, h3 18px; h2 margins ~24px top / 16px bottom (h2 may keep a hairline top border as section divider).
- **Code**: inline `#F5F5F5` bg, 5px radius; blocks dark `#1C1D21`, 8px radius.
- **Links**: `box-shadow: 0 1px 0 <accent>` bottom-edge underline, not text-decoration.
- Reference implementation: see `examples/15-research-concept-explainer.html`.

## Pattern Catalogue (Use Case → Layout)

Every pattern below was reverse-engineered from a Thariq example. Pick the closest one as a starting point.

### 1. Specs / Implementation Plan (`exploration`)

- Numbered sections with a concise context box at the top
- Use `<details>` for sub-tasks / risks
- Include a "data flow" SVG if the spec involves moving parts
- Mockups inline as code-snippet `<pre>` or rendered HTML cards
- Reference: `16-implementation-plan.html` (28 KB)

### 2. Multi-Option Comparison (`exploration` for code or design)

- `.grid-2` or `.grid-3` of cards, each card = one option
- Each card has: title, label of the tradeoff, mockup/snippet, pros/cons
- User reads side-by-side, picks one
- Reference: `01-exploration-code-approaches.html`, `02-exploration-visual-designs.html`

### 3. PR Writeup / Code Review (`code-review`)

- Diff with margin annotations: render diff lines as `<pre>` with line-number gutter, annotation pills floating right
- Use `<details>` per file for collapsible sections (3-6 typical)
- Color-code by severity: `.pill.neg` (blocker), `.pill.warn` (consider), `.pill.muted` (nit)
- Reference: `03-code-review-pr.html` (25 KB, 3 details)

### 4. Module Map / Code Understanding (`code-review`)

- SVG box-and-arrow diagram at top
- Table of modules with role, dependencies, risk
- `<details>` for deeper dives per module
- Reference: `04-code-understanding.html`

### 5. Status Report (`reports`)

- One table: "What shipped / What slipped / Risks"
- Use `.pill.pos / .pill.warn / .pill.neg` for status indicators
- Eyebrow = week (`WEEK 19 · 2026`)
- Reference: `11-status-report.html`

### 6. Incident Timeline / Post-Mortem (`reports`)

- Vertical timeline using a left-border + flex layout
- Each event: time (mono), severity pill, summary, expandable detail
- Bottom: "What we'd do differently" and "Action items" tables
- Reference: `12-incident-report.html`

### 7. Concept Explainer / Research Note (`research`)

- For research reports, use report chrome: title, dek, metadata panel, key findings, evidence tables, interpretation, sources
- For concept explainers, a hero question is acceptable, but do not use raw prompt text as the opening artifact
- SVG diagram for the core concept or stack map
- 3-5 key findings annotated inline
- "Gotchas" or "Open Questions" section at bottom with `<details>`
- Reference: `14-research-feature-explainer.html`, `15-research-concept-explainer.html`

### 8. Diagram-Heavy Note (`diagrams`)

- Mostly SVG with HTML annotations between
- Each SVG should use `currentColor` for theme adaptability
- Captions in small mono text below each diagram
- Reference: `10-svg-illustrations.html` (3 SVGs), `13-flowchart-diagram.html`

### 9. Slide Deck (`decks`)

- Each `<section class="slide">` is full-viewport
- JS for arrow-key navigation: `document.addEventListener('keydown', ...)`
- Slide counter in corner
- Reference: `09-slide-deck.html`

### 10. Custom Editor / Throwaway Tool (`editors`)

- Inline `<script>` with `var DATA = [...]` at top — keep data + UI in one file
- Pattern: render → user interacts → "Copy as JSON" / "Copy as Markdown" / "Copy as Prompt" button at bottom
- Use `data-` attributes for state on DOM elements
- Drag-and-drop: HTML5 native (`draggable="true"` + `dragstart`/`drop` listeners)
- Reference: `18-editor-triage-board.html`, `19-editor-feature-flags.html`, `20-editor-prompt-tuner.html`

## Skeleton Template

When in doubt, start with this 30-line skeleton and grow:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{Title}}</title>
<meta name="post:title" content="{{Title}}">
<meta name="post:summary" content="{{One sentence summary}}">
<meta name="post:published" content="{{YYYY-MM-DD}}">
<meta name="post:tags" content="{{comma,separated,tags}}">
<style>/* Paste design-system block from above */</style>
</head>
<body>
<div class="page">
  <header class="page-head">
    <div class="eyebrow">{{Date}} · {{Category}}</div>
    <h1>{{Title}}</h1>
    <div class="prompt-box">
      <span class="label">{{Research Scope / Context / Mandate}}</span>
      {{Professional one-line scope. Do not paste raw prompt text in research reports.}}
    </div>
  </header>

  <section>
    <div class="sec-head"><span class="num">01</span><h2>{{Section title}}</h2></div>
    <!-- content -->
  </section>

  <!-- more sections -->
</div>
</body>
</html>
```

## Markdown-to-HTML reading layer

For live conference / wiki notes, keep markdown as the **source of truth** and generate HTML as the **reading layer**. Do not replace the `.md` unless explicitly asked to abandon source Markdown/wiki semantics.

Recommended convention:

```text
<notes-dir>/<note>.md              # source of truth
<notes-dir>/_html/<note>.html      # hosted/wiki-readable polished artifact
```

If the HTML is opened from the wiki/static dashboard, prefer a hosted/wiki-native version that blends with the wiki shell. If the HTML is for external sharing / portfolio, a standalone report style is fine. When a listing still opens Markdown, the fix belongs in the wiki/static-site link routing: prefer `_html/<same-stem>.html` when it exists.

## Where to Save

| File type | Path |
|---|---|
| Research notes | `<workspace>/analysis/<area>/...html` |
| Tool / skill docs | `<workspace>/docs/<area>/...html` |
| Project specs | Use the active project root unless a served artifact is requested |
| Throwaway editors | Use a project-local `_scratch/` or `docs/` folder |

After writing, give the user the local file path. Only give a reachable static-server URL if the artifact was explicitly placed under a served directory.

## Editor-Specific Tip: The "Copy" Button Pattern

For custom editors, always end with an export button so user can paste back into Claude Code:

```html
<button id="export">Copy as JSON</button>
<script>
document.getElementById('export').addEventListener('click', () => {
  const state = serializeWhateverYouHave();
  navigator.clipboard.writeText(JSON.stringify(state, null, 2));
  // Toast: "copied"
});
</script>
```

## Reference Examples (Bundled With This Skill)

The 20 Thariq examples are bundled here (not just linked) so this skill is fully self-contained and survives without internet. When picking a starting point, **Read** the closest matching example HTML — it has the actual CSS / SVG / JS you can copy from.

| Category | Slug | Local file | Use when |
|---|---|---|---|
| exploration | 01-exploration-code-approaches | `examples/01-exploration-code-approaches.html` | Compare 3 code-architecture approaches side-by-side |
| exploration | 02-exploration-visual-designs | `examples/02-exploration-visual-designs.html` | 6 design directions in a grid for the user to pick |
| exploration | 16-implementation-plan | `examples/16-implementation-plan.html` | Full implementation plan with milestones, timeline, mockups |
| code-review | 03-code-review-pr | `examples/03-code-review-pr.html` | Annotated PR diff with severity-coded findings |
| code-review | 17-pr-writeup | `examples/17-pr-writeup.html` | PR author writeup: motivation + design choices |
| code-review | 04-code-understanding | `examples/04-code-understanding.html` | Module map of unfamiliar code, boxes + arrows |
| design | 05-design-system | `examples/05-design-system.html` | Color/type/spacing tokens reference |
| design | 06-component-variants | `examples/06-component-variants.html` | Every size × state × intent of a component |
| prototyping | 07-prototype-animation | `examples/07-prototype-animation.html` | Isolated animation with sliders to tune |
| prototyping | 08-prototype-interaction | `examples/08-prototype-interaction.html` | Clickable flow across 4 screens |
| diagrams | 10-svg-illustrations | `examples/10-svg-illustrations.html` | Multiple SVG diagrams (3 in this one) |
| diagrams | 13-flowchart-diagram | `examples/13-flowchart-diagram.html` | Annotated flowchart with branching |
| decks | 09-slide-deck | `examples/09-slide-deck.html` | Arrow-key slide deck, JS for navigation |
| research | 14-research-feature-explainer | `examples/14-research-feature-explainer.html` | Explain how a feature works (rate limiter etc.) |
| research | 15-research-concept-explainer | `examples/15-research-concept-explainer.html` | Teach a concept (e.g. consistent hashing) |
| reports | 11-status-report | `examples/11-status-report.html` | Weekly status: shipped / slipped / risks |
| reports | 12-incident-report | `examples/12-incident-report.html` | Post-mortem with minute-by-minute timeline |
| editors | 18-editor-triage-board | `examples/18-editor-triage-board.html` | Drag-drop ticket triage, copy-as-markdown export |
| editors | 19-editor-feature-flags | `examples/19-editor-feature-flags.html` | Feature flag editor with dependency warnings |
| editors | 20-editor-prompt-tuner | `examples/20-editor-prompt-tuner.html` | Side-by-side prompt + sample inputs + token counter |

**DOM signal analysis** (which examples use SVG / details / data-attr / scripts / dark mode etc.) is at `examples/_analysis.json` — useful for picking the right starting template.

**Screenshots** of all 20 (1440×900 viewport, full page) are at `screenshots/` when present.

## How to Browse Examples

Directly read examples from this skill folder:

```
Read skills/html-notes/examples/16-implementation-plan.html
```

## Source / Reference

- Skill source: this skill directory (`skills/html-notes/SKILL.md`)
- If needed, symlink this skill folder into the local Claude or Codex skills directory for discovery
- Source patterns: 20 HTML examples scraped from <https://thariqs.github.io/html-effectiveness/> via Playwright on the scrape date — bundled into `examples/` subfolder
- Inspired by: Thariq's article "Using Claude Code: The Unreasonable Effectiveness of HTML"

## Critical (do not skip)

- **Single self-contained `.html`** — inline `<style>`/`<script>`, no external CSS/JS/font deps; must open via `file://`.
- **Never lead a research report with the raw prompt** — translate it into a professional Research Scope / Mandate block.
- **HTML is for human-read artifacts, never for chat messages** (chat platforms have their own formatting) or for git-diffed repo source.
- After writing, give the user the local file path.

## Diagrams (MANDATORY reference)
Before drawing ANY diagram in an HTML note, read `references/diagram-standard.md` — relationships-not-lists, two-layer nodes, verb-labeled edges, one focal node, TL;DR coverage check, inline SVG. Born from a pill-list diagram failure; worked example inside.

For career, strategy, operating-principle, or decision-framework notes, also consult `references/career-strategy-diagrams.md`. Do not default to a generic hub-and-spoke concept map; use a flywheel / pipeline / trap-branch diagram that shows how value compounds and where the local optimum sits.
