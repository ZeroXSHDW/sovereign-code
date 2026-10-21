"""Task-domain routing: pick the right specialist model, skill and answer protocol.

A prompt is classified into one or more domains (code, legal, ethics, vision,
forensics, ...). Each domain maps to a stable gateway alias, an optional skill
template, and a system prompt that forces a *definite* answer: every specialist
reply must end with ``VERDICT:`` so a long automated cycle can tell when a
question has actually been settled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERDICT_RE = re.compile(r"^\s*\**VERDICT\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
CONFIDENCE_RE = re.compile(r"^\s*\**CONFIDENCE\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

DEFINITIVE_PROTOCOL = (
    "Answer protocol (mandatory): reason step by step, then finish with exactly these lines:\n"
    "VERDICT: <one definite sentence that answers the question; never 'it depends' without "
    "stating which branch applies>\n"
    "CONFIDENCE: <high|medium|low> - <why>\n"
    "OPEN QUESTIONS: <none, or the specific facts still missing>\n"
    "If information is missing, state the assumption you made and still give a verdict."
)

FORCE_VERDICT = (
    "Your previous answer did not end with a VERDICT line. Using your analysis above, reply "
    "with ONLY the three protocol lines (VERDICT, CONFIDENCE, OPEN QUESTIONS)."
)


@dataclass(frozen=True)
class Domain:
    key: str
    label: str
    alias: str  # gateway alias that serves this specialist
    fallback: str  # alias used when the primary is not routable
    skill: str | None
    keywords: tuple[str, ...]
    system: str


DOMAINS: dict[str, Domain] = {
    "code": Domain(
        "code",
        "Software engineering",
        "local-code",
        "local-agent",
        "code-review",
        (
            "bug",
            "function",
            "functions",
            "functional",
            "functionality",
            "class",
            "classes",
            "classmethod",
            "subclass",
            "refactor*",
            "implement*",
            "compile*",
            "test*",
            "api*",
            "python",
            "typescript",
            "javascript",
            "rust",
            "swift",
            "golang",
            "sql",
            "build*",
            "lint*",
            "endpoint*",
            "cli",
            "script*",
            "repo",
            "repos",
            "repository",
            "repositories",
            "code",
            "stack trace",
            "exception*",
        ),
        "You are a principal software engineer. Prefer minimal, correct, tested changes.",
    ),
    "legal": Domain(
        "legal",
        "Legal and compliance",
        "local-reasoning-deep",
        "local-reasoning",
        "legal-review",
        (
            "contract*",
            "clause*",
            "license*",
            "licence*",
            "gdpr",
            "liability",
            "terms of service",
            "copyright*",
            "patent*",
            "trademark*",
            "complian*",
            "lawsuit*",
            "indemn*",
            "nda",
            "privacy policy",
            "regulat*",
            "statute*",
            "legal*",
            "jurisdiction*",
        ),
        "You are a careful legal analyst. Cite the clause or principle you rely on. "
        "You are not a lawyer; flag what a qualified professional must confirm.",
    ),
    "ethics": Domain(
        "ethics",
        "Ethics and safety",
        "local-reasoning-deep",
        "local-reasoning",
        "ethics-review",
        (
            "ethic*",
            "bias",
            "harm*",
            "consent",
            "consents",
            "consented",
            "consenting",
            "consensual",
            "consensually",
            "moral*",
            "fairness",
            "responsibility",
            "responsible",
            "misus*",
            "dual-use",
            "surveillanc*",
            "discriminat*",
            "safety risk",
            "societ*",
        ),
        "You are an applied-ethics reviewer. Weigh stakeholders, harms and mitigations "
        "explicitly, then commit to a recommendation.",
    ),
    "vision": Domain(
        "vision",
        "Image and visual analysis",
        "local-vision-deep",
        "local-vision",
        "vision-analysis",
        (
            "image*",
            "screenshot*",
            "photo*",
            "picture*",
            "diagram*",
            "ocr",
            "chart",
            "charts",
            "charted",
            "charting",
            "ui mockup",
            "visual*",
            "scan of",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".heic",
        ),
        "You are a meticulous visual analyst. Describe only what is observable, then infer.",
    ),
    "forensics": Domain(
        "forensics",
        "Forensics and incident analysis",
        "local-reasoning-deep",
        "local-reasoning",
        "forensics",
        (
            "forensic*",
            "incident*",
            "log analysis",
            "timeline*",
            "malware",
            "breach*",
            "evidence*",
            "provenance",
            "tamper*",
            "root cause",
            "postmortem*",
            "artifact*",
            "hash mismatch",
            "intrusion*",
            "ioc",
            "metadata analysis",
        ),
        "You are a digital-forensics analyst. Separate evidence from inference, keep a "
        "timeline, and rate each conclusion's strength.",
    ),
    "security": Domain(
        "security",
        "Application security",
        "local-reasoning",
        "local-agent",
        "security-review",
        (
            "vulnerab*",
            "cve",
            "xss",
            "csrf",
            "inject*",
            "secret",
            "secrets",
            "secretly",
            "auth bypass",
            "exploit*",
            "threat model",
            "sandbox*",
            "hardening",
            "owasp",
            "crypto*",
            "token leak",
        ),
        "You are an application-security engineer. Rank findings by exploitability.",
    ),
    "browser": Domain(
        "browser",
        "Browser research and navigation",
        "local-browser-nav",
        "local-agent",
        None,
        (
            "browse*",
            "website*",
            "web page",
            "scrape*",
            "navigat*",
            "click*",
            "login form",
            "fill the form",
            "url*",
            "http://",
            "https://",
            "search the web",
            "crawl*",
        ),
        "You drive a web browser step by step. Prefer the smallest action that makes progress.",
    ),
    "research": Domain(
        "research",
        "Research and synthesis",
        "local-reasoning",
        "local-chat",
        "research",
        (
            "research*",
            "compare",
            "compares",
            "compared",
            "comparing",
            "comparison",
            "comparisons",
            "comparable",
            "survey",
            "surveys",
            "surveyed",
            "surveying",
            "literature",
            "summar*",
            "find out",
            "alternative*",
            "evaluat*",
            "pros and cons",
            "market*",
            "benchmark*",
            "investigat*",
        ),
        "You are a research analyst. Separate established facts from inference and say "
        "what would change your conclusion.",
    ),
    "finance": Domain(
        "finance",
        "Financial analysis",
        "local-reasoning",
        "local-chat",
        "financial-analysis",
        ("budget*", "revenue*", "valu*", "cash flow", "pric*", "invoic*", "roi", "forecast*"),
        "You are a financial analyst. Show the arithmetic and state every assumption.",
    ),
    "general": Domain(
        "general",
        "General",
        "local-chat",
        "local-agent",
        None,
        (),
        "You are a precise, direct assistant.",
    ),
}


def _compile(keyword: str) -> re.Pattern[str]:
    """Match one keyword.

    A keyword ending in `*` is a stem (`ethic*` matches "ethics", "ethical").
    Everything else must match whole words, otherwise "code" matches
    "decode", "api" matches "rapid" and "cli" matches "click".

    Stems are prefix matches on a word boundary, so they over-reach: `repo*`
    also matched "report" and `chart*` matched "charter". Stems whose prefix
    is also the start of an unrelated word are therefore spelled out as
    whole words instead of being written as a stem.
    """
    stem = keyword.endswith("*")
    if stem:
        keyword = keyword[:-1]
    if not keyword:
        return re.compile(r"(?!)")
    body = re.escape(keyword)
    prefix = r"\b" if keyword[:1].isalnum() else ""
    if stem:
        return re.compile(prefix + body, re.IGNORECASE)
    suffix = r"\b" if keyword[-1:].isalnum() else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    key: [_compile(word) for word in domain.keywords] for key, domain in DOMAINS.items()
}


def classify(text: str, limit: int = 3) -> list[Domain]:
    """Rank domains for ``text``; always returns at least ``general``."""
    order = list(DOMAINS)
    scored: list[tuple[int, str]] = []
    for key in DOMAINS:
        score = sum(len(pattern.findall(text)) for pattern in _PATTERNS[key])
        if score:
            scored.append((score, key))
    scored.sort(key=lambda item: (-item[0], order.index(item[1])))
    picked = [DOMAINS[key] for _, key in scored[:limit]]
    return picked or [DOMAINS["general"]]


def system_prompt(domain: Domain) -> str:
    return f"{domain.system}\n\n{DEFINITIVE_PROTOCOL}"


def verdict(text: str) -> str | None:
    """Return the verdict sentence, or None when the answer never committed."""
    matches = VERDICT_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].strip().strip("*").strip() or None


def confidence(text: str) -> str | None:
    matches = CONFIDENCE_RE.findall(text or "")
    return matches[-1].strip().strip("*").strip() if matches else None
