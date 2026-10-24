"""Task packs: a category's skills, model sources, guardrails and playbook.

A domain (``domains.py``) decides which specialist answers a prompt. A pack is
the larger unit an autonomous agent needs to work a whole project in one
category: what skills to load, where to find models for it, the rules it must
not break, and the steps it follows. ``sovereign pack brief`` writes a pack into
a project's ``AGENTS.md`` so OpenCode or ChatGPT picks it up on open.

Model searches are only search queries. Nothing here claims a model works for
a category until it has been run on the Mac (see ``sovereign model-info`` and
``sovereign verify``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domains import DOMAINS
from .router import Task


@dataclass(frozen=True)
class Pack:
    key: str
    label: str
    summary: str
    domain: str  # routing domain in domains.DOMAINS
    task: Task  # which installed model the router picks for this pack
    skill_queries: tuple[str, ...]
    model_queries: tuple[str, ...]
    guardrails: tuple[str, ...]
    steps: tuple[str, ...]
    deliverables: tuple[str, ...]
    related: tuple[str, ...] = ()  # other pack keys worth referencing next

    def aliases(self) -> tuple[str, ...]:
        """Every extra name that resolves to this pack."""
        return tuple(alias for alias, target in PACK_ALIASES.items() if target == self.key)


# Short or common names a caller may use instead of the canonical key.
# Keys are normalised (lowercase, alphanumerics only) before lookup.
PACK_ALIASES: dict[str, str] = {
    "adversary": "redteam",
    "adversaryemulation": "redteam",
    "red": "redteam",
    "blue": "blueteam",
    "detection": "blueteam",
    "detectionengineering": "blueteam",
    "hunting": "soc",
    "threathunting": "soc",
    "triage": "soc",
    "cti": "threatintel",
    "ioc": "threatintel",
    "iocs": "threatintel",
    "threatintelligence": "threatintel",
    "dfir": "forensics",
    "incident": "forensics",
    "incidentresponse": "forensics",
    "ir": "forensics",
    "riskassessment": "risk",
    "grc": "compliance",
    "vuln": "vulnerability",
    "vulnmgmt": "vulnerability",
    "vulnerabilitymanagement": "vulnerability",
    "contract": "legal",
    "contracts": "legal",
    "threatmodel": "threatmodel",
    "threatmodelling": "threatmodel",
    "stride": "threatmodel",
    "linddun": "threatmodel",
    "purple": "purpleteam",
    "malwareanalysis": "malware",
    "cloud": "cloudsec",
    "cloudsecurity": "cloudsec",
    "appsec": "appsec",
    "securecode": "appsec",
    "securecoding": "appsec",
}


def normalize_key(value: str | None) -> str:
    """Canonical pack key for a user-supplied name: red-team, RED_TEAM, dfir -> key."""
    cleaned = re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())
    if not cleaned:
        return ""
    return PACK_ALIASES.get(cleaned, cleaned)


_AUTHORISED = (
    "Test only systems the user owns or has written authorisation to test. Before any "
    "active step, read SCOPE.md at the project root and stop if it is missing or does "
    "not list the target."
)

PACKS: dict[str, Pack] = {
    "pentest": Pack(
        key="pentest",
        label="Penetration testing",
        summary="Authorised, scoped security testing of web apps, APIs and hosts.",
        domain="security",
        task=Task.CODE,
        skill_queries=("penetration", "owasp", "attack"),
        model_queries=("security instruct gguf", "cybersecurity gguf"),
        guardrails=(
            _AUTHORISED,
            "No denial-of-service, data destruction, persistence on production hosts, or "
            "credential spraying.",
            "Record every request and command with a timestamp in EVIDENCE.md.",
            "Stop and report, do not pivot, when a finding touches out-of-scope data.",
        ),
        steps=(
            "Read SCOPE.md and confirm targets, dates and allowed techniques.",
            "Map the attack surface from the project's routes, configs and dependencies.",
            "Test each entry point against OWASP categories, one at a time.",
            "Confirm each finding with a minimal, reversible reproduction.",
            "Write findings with severity, affected path, reproduction and fix.",
        ),
        deliverables=("FINDINGS.md", "EVIDENCE.md"),
        related=("redteam", "vulnerability", "blueteam"),
    ),
    "vulnerability": Pack(
        key="vulnerability",
        label="Vulnerability analysis",
        summary="Static and dependency analysis of code, configs and supply chain.",
        domain="security",
        task=Task.CODE,
        skill_queries=("vulnerability", "security", "dependency"),
        model_queries=("code security gguf", "vulnerability detection gguf"),
        guardrails=(
            "Analyse without executing untrusted code or exploits.",
            "Tie every finding to a CWE and, where one exists, a CVE, and say which one "
            "is unverified.",
            "Report the lowest-cost fix first.",
        ),
        steps=(
            "Inventory dependencies and lockfiles; check each against advisories.",
            "Scan source for injection, auth, secrets and unsafe deserialisation.",
            "Review configuration for exposed binds, debug flags and weak defaults.",
            "Rank findings by exploitability and exposure, then write VULNERABILITIES.md.",
        ),
        deliverables=("VULNERABILITIES.md",),
        related=("appsec", "pentest", "risk"),
    ),
    "risk": Pack(
        key="risk",
        label="Risk analysis",
        summary="Risk register with likelihood, impact, treatment and owners for a project.",
        domain="security",
        task=Task.REASON,
        skill_queries=("risk analysis", "threat model", "risk register"),
        model_queries=("instruct reasoning gguf", "risk analysis gguf"),
        guardrails=(
            "State every assumption and the source of each likelihood and impact score.",
            "Show the scoring scale used, and keep it the same across the register.",
        ),
        steps=(
            "Define the system, its assets and its boundary.",
            "Enumerate risks by asset and threat; one row per risk.",
            "Score likelihood and impact on the stated scale; compute the rating.",
            "Propose a treatment (avoid, reduce, transfer, accept) and an owner for each.",
        ),
        deliverables=("RISK_REGISTER.md",),
        related=("threatmodel", "blueteam", "compliance"),
    ),
    "vendor": Pack(
        key="vendor",
        label="Vendor due diligence",
        summary="Third-party assessment: security posture, data handling, certifications.",
        domain="research",
        task=Task.REASON,
        skill_queries=("vendor due diligence", "supplier", "third-party"),
        model_queries=("instruct gguf", "reasoning instruct gguf"),
        guardrails=(
            "Mark every claim as evidenced (with source) or unverified.",
            "Never mark a certification as held without a certificate or report reference.",
        ),
        steps=(
            "List the vendor's data flows, sub-processors and data locations.",
            "Check certifications (SOC 2, ISO 27001) and their scope and dates.",
            "Score answers against the questionnaire; list every gap.",
            "Write VENDOR_ASSESSMENT.md with a go, conditional, or no-go recommendation.",
        ),
        deliverables=("VENDOR_ASSESSMENT.md",),
        related=("compliance", "risk"),
    ),
    "legal": Pack(
        key="legal",
        label="Legal analysis",
        summary="Contract, policy and regulatory review with cited clauses.",
        domain="legal",
        task=Task.REASON,
        skill_queries=("legal", "contract", "regulation"),
        model_queries=("legal instruct gguf", "law gguf"),
        guardrails=(
            "This is analysis, not legal advice. Name the jurisdiction and say when a "
            "lawyer must check the result.",
            "Quote the clause you rely on, with its location.",
        ),
        steps=(
            "Identify the governing law, parties and effective dates.",
            "Extract obligations, liabilities, termination and data terms.",
            "Flag clauses that are unusual, one-sided or missing.",
            "Write LEGAL_REVIEW.md with each issue, the clause and a suggested change.",
        ),
        deliverables=("LEGAL_REVIEW.md",),
        related=("compliance", "risk", "vendor"),
    ),
    "compliance": Pack(
        key="compliance",
        label="Compliance",
        summary="Control mapping and evidence gaps against a named framework.",
        domain="legal",
        task=Task.REASON,
        skill_queries=("compliance", "audit", "gdpr"),
        model_queries=("legal compliance gguf", "instruct gguf"),
        guardrails=(
            "Name the framework and version for every control mapped.",
            "A control with no evidence is a gap, never a pass.",
        ),
        steps=(
            "Select the framework and list its controls in scope.",
            "Map each control to the project's evidence (code, config, docs).",
            "Record gaps and the owner of each.",
            "Write COMPLIANCE_GAPS.md ordered by audit risk.",
        ),
        deliverables=("COMPLIANCE_GAPS.md",),
        related=("legal", "risk", "vendor"),
    ),
    "forensics": Pack(
        key="forensics",
        label="Digital forensics",
        summary="Evidence-preserving analysis of logs, disks and incident artefacts.",
        domain="forensics",
        task=Task.REASON,
        skill_queries=("forensic", "incident", "evidence"),
        model_queries=("forensic gguf", "incident response gguf"),
        guardrails=(
            "Hash every evidence file before reading it and never modify the originals.",
            "Work on copies; log each tool run and its output hash.",
        ),
        steps=(
            "Record evidence inventory with hashes and acquisition times.",
            "Build a timeline from logs and file metadata.",
            "Separate observed facts from inferences in every conclusion.",
            "Write FORENSIC_REPORT.md with the timeline and open questions.",
        ),
        deliverables=("FORENSIC_REPORT.md", "TIMELINE.csv"),
        related=("soc", "legal", "malware"),
    ),
    "redteam": Pack(
        key="redteam",
        label="Red team / adversary emulation",
        summary="Authorised adversary emulation mapped to MITRE ATT&CK, with detections "
        "handed to the blue team.",
        domain="security",
        task=Task.CODE,
        skill_queries=("adversary emulation", "attack patterns", "purple team"),
        model_queries=("cybersecurity gguf", "red team gguf"),
        guardrails=(
            _AUTHORISED,
            "Map every action to a MITRE ATT&CK technique and record the technique ID.",
            "No destructive payloads, persistence on production hosts, or "
            "exfiltration beyond the agreed scope.",
            "Hand every successful technique to the blue team as a detection test case.",
        ),
        steps=(
            "Read SCOPE.md and confirm targets, dates, allowed techniques and stop conditions.",
            "Define the objectives and the threat actor being emulated.",
            "Map the planned TTPs to MITRE ATT&CK technique IDs.",
            "Execute each technique minimally and reversibly, recording evidence.",
            "Write REDTEAM_REPORT.md, ATTACK_MATRIX.csv and DETECTIONS.md.",
        ),
        deliverables=("REDTEAM_REPORT.md", "ATTACK_MATRIX.csv", "DETECTIONS.md"),
        related=("blueteam", "threatintel", "purpleteam"),
    ),
    "blueteam": Pack(
        key="blueteam",
        label="Blue team / detection engineering",
        summary="Telemetry, detection rules, triage and hardening for SOC defence.",
        domain="security",
        task=Task.REASON,
        skill_queries=("blue team", "detection engineering", "incident runbook"),
        model_queries=("cybersecurity gguf", "incident response gguf"),
        guardrails=(
            "Cite the log source and field behind every detection.",
            "Ship each detection with a test case and its known false-positive profile.",
            "Do not block, isolate or delete in production without explicit approval.",
        ),
        steps=(
            "Inventory the telemetry sources and the fields they actually provide.",
            "Map ATT&CK coverage and name the blind spots.",
            "Write detections with severity, logic, test case and false-positive notes.",
            "Define triage and escalation for each detection.",
            "Write DETECTIONS.md and BLUE_TEAM_PLAYBOOK.md.",
        ),
        deliverables=("DETECTIONS.md", "BLUE_TEAM_PLAYBOOK.md"),
        related=("soc", "redteam", "purpleteam"),
    ),
    "soc": Pack(
        key="soc",
        label="SOC triage and threat hunting",
        summary="Alert triage, IOC enrichment, hunting hypotheses and escalation.",
        domain="forensics",
        task=Task.REASON,
        skill_queries=("soc analyst", "ioc", "threat hunting"),
        model_queries=("incident response gguf", "cybersecurity gguf"),
        guardrails=(
            "Every IOC carries its source, first-seen date, confidence and TLP.",
            "Never invent a timestamp: write `unknown` when the prompt supplies none.",
            "Separate observed telemetry from inference; say what is still unverified.",
            "Never block or isolate without approval; propose the action and its blast radius.",
        ),
        steps=(
            "Parse the alerts and list the observable facts.",
            "Enrich each indicator and discard expired or unsourced ones.",
            "Test hunting hypotheses against the available telemetry.",
            "Rank alerts as true positive, benign or needs-more-data.",
            "Write SOC_TRIAGE.md, IOCS.csv and HUNT_QUERIES.md.",
        ),
        deliverables=("SOC_TRIAGE.md", "IOCS.csv", "HUNT_QUERIES.md"),
        related=("forensics", "threatintel", "blueteam"),
    ),
    "threatintel": Pack(
        key="threatintel",
        label="Threat intelligence",
        summary="IOC collection, enrichment, ATT&CK mapping and sharing-ready output.",
        domain="security",
        task=Task.REASON,
        skill_queries=("threat intelligence", "attack patterns", "malware analysis"),
        model_queries=("cybersecurity gguf", "threat intelligence gguf"),
        guardrails=(
            "Date every IOC and state its source and confidence; expired indicators are not intel.",
            "Never invent a timestamp: write `unknown` when the source supplies none.",
            "Map activity to ATT&CK techniques and name an adversary only when evidenced.",
            "Sanitise and mark sharing limits (TLP) before distribution.",
        ),
        steps=(
            "Collect indicators from named sources and record the collection date.",
            "Normalise, deduplicate and enrich each indicator.",
            "Map the activity to ATT&CK techniques and campaigns.",
            "Write THREAT_INTEL.md and IOCS.csv with confidence and TLP.",
        ),
        deliverables=("THREAT_INTEL.md", "IOCS.csv"),
        related=("soc", "forensics", "malware"),
    ),
    "threatmodel": Pack(
        key="threatmodel",
        label="Threat modeling",
        summary="STRIDE or LINDDUN model over explicit data flows, trust boundaries and "
        "mitigations.",
        domain="security",
        task=Task.REASON,
        skill_queries=("threat modeling", "stride", "linddun"),
        model_queries=("instruct reasoning gguf", "risk analysis gguf"),
        guardrails=(
            "Name the framework (STRIDE or LINDDUN) and use it consistently.",
            "Every threat names its asset, actor, vector, trust boundary, mitigation and owner.",
            "No threat without a testable mitigation or an explicit accepted risk.",
        ),
        steps=(
            "Define the system, its assets, actors and trust boundaries.",
            "Draw the data flows and mark where data crosses a boundary.",
            "Enumerate threats per element with the chosen framework.",
            "Score likelihood and impact, then assign a mitigation and owner.",
            "Write THREAT_MODEL.md and DATA_FLOWS.md.",
        ),
        deliverables=("THREAT_MODEL.md", "DATA_FLOWS.md"),
        related=("appsec", "risk", "blueteam"),
    ),
    "purpleteam": Pack(
        key="purpleteam",
        label="Purple team",
        summary="Pair red-team actions with blue-team telemetry and turn misses into detections.",
        domain="security",
        task=Task.REASON,
        skill_queries=("purple team", "adversary emulation", "detection engineering"),
        model_queries=("cybersecurity gguf", "incident response gguf"),
        guardrails=(
            _AUTHORISED,
            "Every red action has a detection candidate and a named owner.",
            "Measure detection coverage, not just the number of findings.",
            "Do not tune production detections without approval.",
        ),
        steps=(
            "Agree the ATT&CK techniques and success criteria with both teams.",
            "Pair each technique with the telemetry that should detect it.",
            "Emulate the technique and record detected, missed or noisy.",
            "File each miss as a detection backlog item with a test case.",
            "Write PURPLE_TEAM_REPORT.md and DETECTION_BACKLOG.md.",
        ),
        deliverables=("PURPLE_TEAM_REPORT.md", "DETECTION_BACKLOG.md"),
        related=("redteam", "blueteam", "threatintel"),
    ),
    "malware": Pack(
        key="malware",
        label="Malware analysis",
        summary="Static and dynamic triage: hashes, behaviour, config, C2 and indicators.",
        domain="forensics",
        task=Task.REASON,
        skill_queries=("malware analysis", "reverse engineering", "ioc"),
        model_queries=("malware analysis gguf", "cybersecurity gguf"),
        guardrails=(
            "Hash every sample before touching it and analyse copies only.",
            "Never execute a sample outside an isolated VM with no network path to production.",
            "Record the tool and version behind each observation.",
            "No attribution without evidence; mark inferences as inferences.",
        ),
        steps=(
            "Inventory the sample: names, hashes, size, first seen.",
            "Static triage: strings, imports, sections, packer and signature checks.",
            "Dynamic triage in an isolated VM; capture process, file and network behaviour.",
            "Extract config, C2 and IOCs with source and confidence.",
            "Write MALWARE_REPORT.md and IOCS.csv.",
        ),
        deliverables=("MALWARE_REPORT.md", "IOCS.csv"),
        related=("forensics", "soc", "threatintel"),
    ),
    "cloudsec": Pack(
        key="cloudsec",
        label="Cloud and container security",
        summary="Identity, network, storage, logging and workload posture against provider "
        "baselines.",
        domain="security",
        task=Task.REASON,
        skill_queries=("cloud security", "kubernetes security", "iam"),
        model_queries=("instruct reasoning gguf", "cybersecurity gguf"),
        guardrails=(
            "Least privilege is the default recommendation; name the exact role or policy.",
            "Never export credentials, keys or customer data into the report.",
            "Cite the provider control or CIS benchmark behind each finding.",
            "Separate a config fact from an inference; state what was not inspected.",
        ),
        steps=(
            "Inventory accounts, clusters, identities and exposed entry points.",
            "Review IAM, network exposure, storage, logging, secrets and workload limits.",
            "Map findings to CIS or provider benchmarks and rank by exposure.",
            "Propose the lowest-cost fix and its blast radius.",
            "Write CLOUD_SECURITY_REVIEW.md and IAM_FINDINGS.csv.",
        ),
        deliverables=("CLOUD_SECURITY_REVIEW.md", "IAM_FINDINGS.csv"),
        related=("appsec", "vulnerability", "risk"),
    ),
    "appsec": Pack(
        key="appsec",
        label="Application security review",
        summary="Secure-code and attack-surface review with CWE-backed findings and fixes.",
        domain="security",
        task=Task.CODE,
        skill_queries=("secure coding", "application security", "owasp"),
        model_queries=("code security gguf", "vulnerability detection gguf"),
        guardrails=(
            "Give a CWE ID for every finding and say when it is unverified.",
            "Reproduce without touching real user data or production credentials.",
            "Report the lowest-cost fix first and never copy secrets into the report.",
        ),
        steps=(
            "Map the attack surface from routes, configs and dependencies.",
            "Review authentication, authorization, input handling, secrets, "
            "deserialisation and SSRF.",
            "Confirm each finding with a minimal, reversible reproduction.",
            "Rank by exploitability and exposure, then write SECURITY_REVIEW.md and FIXES.md.",
        ),
        deliverables=("SECURITY_REVIEW.md", "FIXES.md"),
        related=("vulnerability", "threatmodel", "cloudsec"),
    ),
    "finance": Pack(
        key="finance",
        label="Financial analysis",
        summary="Models, budgets and valuations with every assumption shown.",
        domain="finance",
        task=Task.REASON,
        skill_queries=("financial", "valuation", "budget"),
        model_queries=("finance instruct gguf", "financial reasoning gguf"),
        guardrails=(
            "Show every formula and input; no figure appears without its source or assumption.",
            "Include a sensitivity check on the two largest assumptions.",
            "This is analysis, not investment advice.",
        ),
        steps=(
            "Collect inputs and record their sources.",
            "Build the model in a script or spreadsheet so each number recomputes.",
            "Run the sensitivity check and report the range.",
            "Write FINANCIAL_ANALYSIS.md with the conclusion and its limits.",
        ),
        deliverables=("FINANCIAL_ANALYSIS.md", "model.py"),
        related=("risk",),
    ),
}


def get_pack(key: str | None) -> Pack | None:
    if not key:
        return None
    return PACKS.get(normalize_key(key))


def pack_skills(pack: Pack, limit: int = 12) -> list[tuple[str, str]]:
    """Library skills matching the pack, best matches first, without repeats.

    Uses ``skillrouter.route`` so ranking already weighs the pack's task text,
    then drops legal skills for a non-legal pack: a shared word such as
    "disclosure" must not drag a legal skill into a pentest pack. Route order is
    preserved so the most specific match stays first.
    """
    from .skillrouter import route

    legal_domain = pack.domain in {"legal", "compliance"}
    seen: dict[str, str] = {}
    for query in (*pack.skill_queries, pack.label):
        cards, _note = route(query, limit=limit, scan_risk=False)
        for card in cards:
            if not legal_domain and card.name.startswith(("legal--", "hr-legal-compliance--")):
                continue
            seen.setdefault(card.name, card.description)
        if len(seen) >= limit:
            break
    if seen:
        # The first query is the pack's most specific one, so its order wins;
        # later queries only fill the remaining slots.
        return list(seen.items())[:limit]
    # No coherent match: fall back so a pack still suggests something.
    from .skills import search_skills

    fallback: dict[str, str] = {}
    for query in pack.skill_queries:
        for name, description in search_skills(query, limit=limit):
            fallback.setdefault(name, description)
        if len(fallback) >= limit:
            break
    return list(fallback.items())[:limit]


def hf_candidates(
    pack: Pack,
    limit: int = 5,
    *,
    token: str | None = None,
    transport: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """GGUF search hits per query. Results are candidates, not verified models."""
    from .hf import HFError, search_models

    found: dict[str, list[dict[str, Any]]] = {}
    for query in pack.model_queries:
        try:
            hits = search_models(
                query,
                limit=limit,
                gguf_only=True,
                token=token,
                transport=transport,
            )
        except HFError as exc:
            found[query] = [{"error": str(exc)}]
            continue
        found[query] = [
            {
                "id": hit.id,
                "downloads": hit.downloads,
                "license": hit.license,
                "gated": hit.gated,
                "private": hit.private,
            }
            for hit in hits
        ]
    return found


def installed_for(pack: Pack, views: dict[str, Any], free_gb: float | None) -> str | None:
    """The installed model the router would pick for this pack, or None."""
    from .router import choose

    selection = choose(pack.task, views, free_gb)
    return selection.tag


def _marker(key: str, edge: str) -> str:
    return f"<!-- sovereign-pack:{key}:{edge} -->"


def brief_block(pack: Pack, skills: Iterable[tuple[str, str]]) -> str:
    lines = [
        _marker(pack.key, "start"),
        f"## Pack: {pack.label}",
        "",
        pack.summary,
        "",
        "### Guardrails",
        *[f"- {rule}" for rule in pack.guardrails],
        "",
        "### Steps",
        *[f"{index}. {step}" for index, step in enumerate(pack.steps, start=1)],
        "",
        "### Deliverables",
        *[f"- {name}" for name in pack.deliverables],
        "",
    ]
    if pack.related:
        lines += [
            "### Related packs",
            *[f"- `{key}`" for key in pack.related],
            "",
        ]
    lines += [
        "### Skills to load",
        *[f"- **{name}** — {_first(description)}" for name, description in skills],
        "",
        "Load a skill with the sovereign MCP tool `get_skill`, or list matches with `list_skills`.",
        _marker(pack.key, "end"),
    ]
    return "\n".join(lines)


def _first(text: str) -> str:
    head = re.split(r"(?<=\.)\s", text.strip(), maxsplit=1)[0]
    return head if len(head) <= 160 else head[:159].rstrip() + "…"


def write_brief(path: Path, pack: Pack, skills: Iterable[tuple[str, str]]) -> Path:
    """Insert or replace this pack's managed block in ``path``."""
    block = brief_block(pack, skills)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    start, end = _marker(pack.key, "start"), _marker(pack.key, "end")
    if start in text and end in text:
        head = text[: text.index(start)]
        tail = text[text.index(end) + len(end) :]
        updated = head + block + tail
    else:
        updated = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.write_text(updated, encoding="utf-8")
    return path


def pack_domains_known() -> bool:
    return all(pack.domain in DOMAINS for pack in PACKS.values())


SCOPE_TEMPLATE = """# Engagement scope

Fill this in before any active test. The agent stops if a target is not listed.

- Owner and authorisation (name, date, written reference):
- Targets (hostnames or IP ranges, one per line):
- Out of scope:
- Allowed techniques (for example: authenticated scan, API fuzzing at low rate):
- Test window (start and end, with timezone):
- Contact for emergencies:
"""


def scope_file(project: Path) -> Path | None:
    """Create a SCOPE.md template when a pentest brief is written; None if it exists."""
    target = project / "SCOPE.md"
    if target.exists():
        return None
    target.write_text(SCOPE_TEMPLATE, encoding="utf-8")
    return target


# One fixed question per pack. A model passes when its reply names one of the
# keywords and ends with the VERDICT line. This is a smoke test that the model
# follows the pack's protocol, not a benchmark of its expertise.
PROBES: dict[str, tuple[str, tuple[str, ...]]] = {
    "pentest": (
        "Before any active test, which file must you read first, and what must it list?",
        ("scope",),
    ),
    "vulnerability": ("Which weakness class is CWE-89?", ("sql",)),
    "risk": (
        "Likelihood is 4 and impact is 5, both on 1-5 scales, and rating equals "
        "likelihood times impact. What is the rating?",
        ("20",),
    ),
    "vendor": (
        "A vendor says it holds SOC 2 but gives no report. Is the claim evidenced? "
        "Answer yes or no.",
        ("no", "not"),
    ),
    "legal": (
        "A clause waives all liability. Name one reason it may not be enforceable.",
        ("jurisdiction", "unenforce", "law", "limit", "consumer"),
    ),
    "compliance": (
        "A control has no evidence attached. Is it a pass or a gap?",
        ("gap",),
    ),
    "forensics": (
        "Before reading an evidence disk image, what must you do to it first?",
        ("hash",),
    ),
    "finance": (
        "What is the present value of 110 received in one year at a 10% discount "
        "rate, to two decimal places?",
        ("100.00", "100"),
    ),
}


@dataclass(frozen=True)
class ProbeResult:
    pack: str
    model: str
    passed: bool
    reply: str


def probe_reply_passes(pack_key: str, reply: str) -> bool:
    from .domains import verdict

    _, keywords = PROBES[pack_key]
    lowered = reply.lower()
    return verdict(reply) is not None and any(word in lowered for word in keywords)


async def run_probe(pack: Pack, model: str, client: Any) -> ProbeResult:
    from .domains import DOMAINS, system_prompt

    question, _ = PROBES[pack.key]
    messages = [
        {"role": "system", "content": system_prompt(DOMAINS[pack.domain])},
        {"role": "user", "content": question},
    ]
    parts: list[str] = []
    async for chunk in client.chat_stream(model, messages, context=4096, temperature=0.0):
        parts.append(chunk.content)
    reply = "".join(parts)
    return ProbeResult(pack.key, model, probe_reply_passes(pack.key, reply), reply)


def verification_file(root: Path) -> Path:
    return root / "data" / "packs" / "verified.json"


def load_verified(path: Path) -> dict[str, dict[str, str]]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_probe(path: Path, result: ProbeResult, when: str) -> None:
    """Store a passing result; a failing run clears the model's mark for the pack."""
    import json

    from .safefile import write_private

    data = load_verified(path)
    models = data.setdefault(result.pack, {})
    if result.passed:
        models[result.model] = when
    else:
        models.pop(result.model, None)
    write_private(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def verified_for(path: Path, pack_key: str) -> list[str]:
    return sorted(load_verified(path).get(pack_key, {}))
