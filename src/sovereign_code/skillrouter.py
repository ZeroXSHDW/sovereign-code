"""Pick skills for a task without loading their bodies.

With 22k skills, the hard question is not "what does this skill say" but "which
one do I need". Loading ten bodies to find out costs more context than the task
itself: the median skill is 5 KB, the largest here is 192 KB.

``route`` returns compact cards - name, one line, category, token cost and risk
- ranked against the task text. The agent loads a body only after a card looks
right, by calling ``get_skill`` or ``load_skills``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache

from .skills import SYNONYMS as _SYNONYMS
from .skills_safety import scan

_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_CARD_TOKENS = 40
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "about",
        "over",
        "under",
        "this",
        "that",
        "these",
        "those",
        "its",
        "our",
        "your",
        "their",
        "are",
        "was",
        "were",
        "been",
        "being",
        "does",
        "did",
        "doing",
        "have",
        "has",
        "had",
        "how",
        "what",
        "why",
        "when",
        "which",
        "who",
        "can",
        "could",
        "should",
        "would",
        "will",
        "may",
        "might",
        "must",
        "need",
        "needs",
        "using",
        "use",
        "make",
        "made",
        "please",
        "help",
        "want",
        "new",
    }
)


@dataclass(frozen=True)
class SkillCard:
    name: str
    description: str
    category: str
    tokens: int
    risk: str
    matched: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# These prefixes are collections (curated bundles), not categories.
_COLLECTIONS = frozenset({"x", "x2", "agent", "addy", "jpeetz", "anthropic"})


def category(name: str) -> str:
    parts = name.split("--")
    if len(parts) == 1:
        return "general"
    if parts[0] in _COLLECTIONS and len(parts) > 2:
        return parts[1]
    return parts[0]


def _terms(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        seen.setdefault(word, None)
        for synonym in _SYNONYMS.get(word, ()):
            seen.setdefault(synonym, None)
    return list(seen)


def _variants(term: str) -> list[str]:
    """A cheap singular form, so "forensics" also finds "forensic"."""
    if len(term) > 4 and term.endswith("s") and not term.endswith("ss"):
        return [term, term[:-1]]
    return [term]


def _description_line(text: str, limit: int = 200) -> str:
    head = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "…"


# Category prefixes that belong to each routing domain. A forensics task should
# not return an image-generation skill just because both contain "image".
DOMAIN_PREFIXES: dict[str, tuple[str, ...]] = {
    "forensics": ("forensic", "legal--breach-forensics", "x--linux-server-forensics"),
    "finance": ("financial", "startup-business-analyst", "x--startup-business-analyst"),
    "legal": ("legal--", "hr-legal-compliance--", "x2--data-processing"),
    "security": (
        "security",
        "security-scanning",
        "security-auditor",
        "security-and-hardening",
        "secure",
        "secrets-management",
        "auth-implementation",
        "kubernetes",
        "owasp",
        "pentest",
        "penetration",
        "x--k8s",
        "x2--kubernetes",
        "x2--cloud-security",
        "x--cloud-penetration",
        "x--aws-penetration",
        "x--penetration",
        "x--pentest",
        "x2--pentesting",
        "x2--attack",
        "x2--threat",
        "x2--blue-team",
        "x2--blueteam",
        "x2--detection",
        "x2--anomaly",
        "x2--soc",
        "x2--purpleteam",
        "x2--malware",
        "x2--owasp",
        "x--aws-iam",
        "agent--backend-security-coder",
        "agent--frontend-security-coder",
        "agent--security-auditor",
        "agent--malware-analyst",
        "attack-tree",
        "threat-modeling",
        "incident-response",
        "reverse-engineering",
    ),
    "code": (
        "write-tests",
        "test-driven",
        "code-review",
        "incremental",
        "frontend",
        "react",
        "api-and-interface",
        "python-development",
        "backend-development",
        "developer-essentials",
        "planning-and-task-breakdown",
        "spec-driven-development",
        "code-simplification",
        "performance-optimization",
        "observability-and-instrumentation",
        "documentation-and-adrs",
        "documentation-generation",
        "debugging-and-error-recovery",
        "git-workflow-and-versioning",
        "shipping-and-launch",
        "security-and-hardening",
    ),
    "research": ("research", "documentation"),
    "ethics": ("ethics",),
    "vision": ("vision",),
}


_ENGINEERING_HINTS = (
    "api",
    "architecture",
    "code",
    "database",
    "debug",
    "deploy",
    "design",
    "docs",
    "documentation",
    "feature",
    "function",
    "migration",
    "performance",
    "plan",
    "pull request",
    "python",
    "refactor",
    "review",
    "spec",
    "sql",
    "test",
)

_LEGAL_PREFIXES = ("legal--", "hr-legal-compliance--")


def _affinity(task: str) -> tuple[str, ...]:
    from .domains import classify

    lowered = task.lower()
    domains = list(classify(task, limit=3))
    keys = {domain.key for domain in domains}
    prefixes: list[str] = []
    for domain in domains:
        prefixes.extend(DOMAIN_PREFIXES.get(domain.key, ()))
    # Domain classification is deliberately conservative; an engineering task
    # phrased without "code" still belongs to the code family. Do not apply
    # this when the task already matched a specialist domain such as legal.
    if keys <= {"general", "code"} and any(hint in lowered for hint in _ENGINEERING_HINTS):
        prefixes.extend(DOMAIN_PREFIXES["code"])
    if "security" in lowered:
        prefixes.extend(DOMAIN_PREFIXES["security"])
    return tuple(dict.fromkeys(prefixes))


@lru_cache(maxsize=128)
def _search(query: str, limit: int) -> tuple[tuple[str, str], ...]:
    """Cached skill search: one task repeats the same terms across routes."""
    from .skills import search_skills

    return tuple(search_skills(query, limit=limit))


def _in_affinity(name: str, affinity: tuple[str, ...]) -> bool:
    flattened = name.lower().replace("-", " ").replace("_", " ")
    return any(flattened.startswith(prefix.replace("-", " ")) for prefix in affinity)


def _weights(pool: dict[str, str], terms: list[str]) -> dict[str, float]:
    """Rarer terms matter more: "kubernetes" should beat "review"."""
    total = max(1, len(pool))
    weights: dict[str, float] = {}
    for term in terms:
        seen = sum(
            1
            for name, description in pool.items()
            if term in name.lower() or term in description.lower()
        )
        weights[term] = max(0.25, min(4.0, (total / max(1, seen)) ** 0.5))
    return weights


def _rank_skill(
    name: str,
    description: str,
    terms: list[str],
    phrase: str,
    weights: dict[str, float],
    affinity: tuple[str, ...] = (),
) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    flattened = name.lower().replace("-", " ").replace("_", " ")
    lowered_desc = description.lower()
    if phrase and phrase in flattened:
        score += 8.0
    for term in terms:
        weight = weights.get(term, 1.0)
        if term in flattened:
            score += 3.0 * weight
            matched.append(term)
        elif term in lowered_desc:
            score += 1.0 * weight
            matched.append(term)
    if affinity and _in_affinity(name, affinity):
        score += 2.0
    if len(matched) >= 2:
        score *= 1.2
    return score, matched


def playbook(task: str) -> list[str]:
    """The ordered top prompts for a task, before any skill body is loaded."""
    lowered = task.lower()

    def has(*words: str) -> bool:
        return any(word in lowered for word in words)

    if has("security", "threat", "vulnerab", "exploit", "secret"):
        return [
            "Map the trust boundaries and threats (security-scanning / stride-analysis-patterns).",
            "Run /audit and separate confirmed issues from hardening notes.",
            "Fix the root cause and add a regression test.",
            "Run /check and re-audit the touched path.",
        ]
    if has("debug", "bug", "fail", "broken", "error", "crash", "regression"):
        return [
            "Reproduce with the smallest command and capture the exact error (/debug).",
            "Write a failing regression test that proves the bug (/tdd).",
            "Fix the root cause, then run the focused test.",
            "Review the diff and run /check.",
        ]
    if has("slow", "performance", "optimi", "latency", "memory", "speed"):
        return [
            "Define the metric, workload, and a repeatable benchmark (/perf).",
            "Record a baseline and profile the hot path.",
            "Change one thing and re-measure with the same command.",
            "Add a tolerant regression guard and run /check.",
        ]
    if has("migrat", "upgrade", "deprecat", "legacy", "moderni"):
        return [
            "Inventory every call site, schema, and stored format (/migrate).",
            "Add the new path while keeping the old one working (expand).",
            "Test both paths and roll forward on real data.",
            "Remove the old path only after the rollout window (/simplify).",
        ]
    if has("docs", "document", "readme", "adr", "api reference"):
        return [
            "Read the code and tests; document what exists, not what was planned (/docs).",
            "Write the smallest useful doc with a runnable example.",
            "Run every command and example you wrote.",
            "Update AGENTS.md or an ADR if a future maintainer needs the decision.",
        ]
    if has("test", "coverage", "pytest", "spec", "tdd"):
        return [
            "State the behaviour and edge cases to prove.",
            "Add a failing test first (/tdd).",
            "Make the smallest change that passes; refactor while green.",
            "Run /check and report coverage honestly.",
        ]
    if has("plan", "feature", "design", "architect", "spec", "build", "add "):
        return [
            "Write the goal, non-goals, and acceptance criteria (/spec).",
            "Read the touched modules and tests, then order small steps (/plan).",
            "Implement one slice at a time with tests (/tdd).",
            "Review the diff (/review), then run /check.",
        ]
    return [
        "Route the task to the best skills first.",
        "State the smallest useful change and how it will be verified.",
        "Implement it with a test or a measured check.",
        "Review the diff and run /check.",
    ]


def route(
    task: str,
    *,
    limit: int = 6,
    max_tokens: int = 1200,
    scan_risk: bool = True,
    per_category: int = 2,
) -> tuple[list[SkillCard], str]:
    """Rank skills against ``task`` and stay inside a card budget."""

    needle = task.strip()
    if not needle:
        raise ValueError("task is empty")
    terms = _terms(needle)
    phrase = " ".join(needle.lower().split())
    # Search the content terms separately: one AND query over a sentence
    # matches almost nothing, and the rare term is the one that matters.
    pool: dict[str, str] = {}
    queries = [" ".join(terms) if terms else needle]
    for term in terms[:4]:
        queries.extend(_variants(term))
    for query in dict.fromkeys(queries):
        if not query.strip():
            continue
        for name, description in _search(query, max(12, limit * 4)):
            pool.setdefault(name, description)
        if len(pool) >= 200:
            break

    from .skills_install import get_skill, load_curated

    # The index stores a short first heading; the installed profile carries the
    # real frontmatter description. Prefer the latter so routing can see that a
    # skill covers "optimize", "slow" and "performance" even when its name does
    # not.
    curated = load_curated(profile="quality")
    for skill in curated:
        pool[skill.name] = skill.description

    weights = _weights(pool, terms)
    affinity = _affinity(needle)
    curated_names = {skill.name for skill in curated}
    ranked: list[tuple[float, str, str, list[str]]] = []
    for name, description in pool.items():
        score, matched = _rank_skill(name, description, terms, phrase, weights, affinity)
        if score <= 0:
            continue
        if name in curated_names:
            score += 0.5
        ranked.append((score, name, description, matched))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if affinity:
        # Keep the task's domain coherent. Specialist domains (legal, finance,
        # forensics) admit only their own prefixes; a shared word such as
        # "agreement" is not enough. Engineering domains allow a strong
        # three-term outsider so a useful cross-domain skill can still appear.
        strict = any(
            prefix.startswith(
                (
                    "legal--",
                    "hr-legal",
                    "forensic",
                    "financial",
                    "startup-business",
                    "ethics",
                    "vision",
                )
            )
            for prefix in affinity
        )
        if strict:
            ranked = [item for item in ranked if _in_affinity(item[1], affinity)]
        else:
            ranked = [
                item
                for item in ranked
                if _in_affinity(item[1], affinity)
                or (len(item[3]) >= 3 and not item[1].startswith(_LEGAL_PREFIXES))
            ]

    cards: list[SkillCard] = []
    used = 0
    seen_descriptions: set[str] = set()
    seen_slugs: set[str] = set()
    category_counts: dict[str, int] = {}
    for _rank, name, description, matched in ranked:
        if len(cards) >= limit:
            break
        if used + _CARD_TOKENS > max_tokens:
            break
        fingerprint = description.strip().lower()
        if fingerprint and fingerprint in seen_descriptions:
            continue
        slug = name.rsplit("--", 1)[-1].lower()
        if slug in seen_slugs:
            continue
        card_category = category(name)
        # Keep the list diverse: five code-review variants are one choice.
        if card_category != "general" and category_counts.get(card_category, 0) >= per_category:
            continue
        seen_descriptions.add(fingerprint)
        seen_slugs.add(slug)
        category_counts[card_category] = category_counts.get(card_category, 0) + 1
        token_cost = 0
        risk = "ok"
        if scan_risk:
            found = get_skill(name)
            if found is not None:
                token_cost = max(1, len(found.body) // 4)
                risk = scan(found.body).risk
        cards.append(
            SkillCard(
                name=name,
                description=_description_line(description),
                category=category(name),
                tokens=token_cost,
                risk=risk,
                matched=tuple(matched[:6]),
            )
        )
        used += _CARD_TOKENS
    note = (
        f"{len(cards)} card(s) within {max_tokens} tokens; "
        "load a body with get_skill, or several with load_skills."
    )
    if not cards:
        note = "No skill matched. Try different words, or call list_skills with a broader query."
    return cards, note
