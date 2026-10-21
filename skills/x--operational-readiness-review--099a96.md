---
name: operational-readiness-review
description: Run or prepare for an operational readiness review (ORR) before a service or major feature launches — monitoring, dashboards, runbooks, on-call, capacity, failure modes, rollback, data durability, security, and load testing. Use when the user asks to review a launch's readiness, act as the gatekeeper/reviewer, or prepare their own service to pass a readiness review.
---

# Operational Readiness Review

A structured gate applied before a service or major feature goes live (or gets promoted to a higher criticality tier). Two modes:

- **Mode A — Reviewing (gatekeeper).** You assess someone's readiness, classify gaps by severity, and set sign-off criteria.
- **Mode B — Preparing (the team being reviewed).** You self-assess, gather evidence, and close gaps before the review.

## Mental Model

An ORR asks one question in many forms: **"When this breaks at 3am, will the on-call engineer be able to detect it, understand it, and fix it — before customers are seriously hurt?"** Every checklist item is a proxy for that. Review with the incident in mind, not the checklist for its own sake.

Readiness scales with **blast radius and criticality tier**. A internal tool with 5 users doesn't need what a customer-facing tier-1 service needs. Set the bar to the impact.

---

# Mode A: Conducting the Review

## Checklist Domains

For each domain, apply the checks in order. Findings get a severity (see below).

### 1. Architecture & Dependencies
| Check | Ask |
|-------|-----|
| Dependency map | Are ALL upstream and downstream dependencies listed, each with a failure mode? |
| Single points of failure | What happens when each dependency is unavailable? |
| Data flow | Is the full path documented — ingress → processing → storage → egress? |
| Blast radius | Worst case if this fails? Who and how many are affected? |
| Multi-AZ / multi-region | Deployed across zones? What's the zone-failure story? |

### 2. Monitoring & Alarming
| Check | Ask |
|-------|-----|
| SLI coverage | Are availability, latency, error rate, and saturation all measured? |
| Alarm quality | Are thresholds derived from real baselines, not arbitrary round numbers? |
| Missing data | Do critical alarms treat missing data as breaching (so silent failures still page)? |
| On-call routing | Do alarms page the right team? Is escalation clear? |

### 3. Dashboards
| Check | Ask |
|-------|-----|
| Single pane | Is there one operational dashboard with all key metrics? |
| Customer-impact-first | Does it lead with the metric that shows customer pain? |
| Accessible | Is the link current and reachable by whoever gets paged? |

### 4. Runbooks & On-Call
| Check | Ask |
|-------|-----|
| Runbook per alarm | Does every alarm link to a current runbook? |
| Coverage | Is there 24/7 on-call coverage if the tier requires it? |
| Trained | Are on-call engineers trained for this service's tier? |
| Escalation path | Is the path from on-call → lead → senior → exec documented? |
| Freshness | Do runbooks reference current tools, not deprecated ones? |

### 5. Capacity & Scaling
| Check | Ask |
|-------|-----|
| Load tested | Tested to ≥2x expected peak? (Not "we'll do it before peak.") |
| Autoscaling | Scaling policies configured? What triggers scale-out/in — and is it tested? |
| Headroom | >25% buffer above forecast peak? |
| Load shedding | Can it shed load / rate-limit gracefully under overload? |
| Dependency scaling | Will downstream dependencies survive *your* scaled traffic? |

### 6. Failure Modes & Recovery
| Check | Ask |
|-------|-----|
| Per-dependency timeout/fallback | Does one slow dependency block everything, or is it isolated? |
| Retry / circuit-breaker | Are there metrics on retries so amplification is visible before it cascades? |
| Emergency levers | Is there a fast way to shed load or route around a failure? |
| Healthy-service alarm | Is there one aggregate alarm that confirms the service actually works end-to-end? |

### 7. Rollback & Deployment
| Check | Ask |
|-------|-----|
| Rollback speed | Can the last deploy be rolled back in minutes? |
| Deployment safety | Bake times and canary/one-box stages configured? |
| Feature flags | Are risky new features behind flags? |
| Change control | Is the team aware of freeze/peak windows? |

### 8. Data Durability & Management
| Check | Ask |
|-------|-----|
| Backup | Automated backups configured — and tested by restoring? |
| Retention | Is there an enforced retention policy? |
| Recovery objectives | What are RTO/RPO? Has disaster recovery actually been drilled? |
| Compliance | Deletion / data-subject requirements met? |

### 9. Security
| Check | Ask |
|-------|-----|
| Threat model | Does one exist? Updated in the last ~12 months? |
| AuthN/AuthZ | How are callers authenticated and permissions enforced? |
| Data classification | What classification? Encrypted at rest and in transit? |
| Secrets | How are credentials stored and rotated? (Never in code.) |
| Network boundaries | Minimally scoped network/security-group rules? |

*(If the launch touches credentials, PII, network exposure, or IAM, pause and consult security standards before signing off — see the security-review-gate skill.)*

### 10. Cost
| Check | Ask |
|-------|-----|
| Right-sizing | Are instances/tasks sized to the workload? |
| Attribution | Are resources tagged for cost tracking? |
| Waste | Idle resources or oversized reservations? |

## Severity Classification

| Severity | Definition | Action |
|----------|-----------|--------|
| **Critical** | Direct customer impact if unresolved; could fail catastrophically. | Blocks sign-off. Resolve before launch. |
| **High** | Significant operational risk; recovery slow or manual. | Resolve before launch; exception needs senior sign-off. |
| **Medium** | Increases toil or slows incident response. | Track post-launch, ~90-day fix. |
| **Low** | Best practice not followed, minimal risk. | Next planning cycle. |

**Classification heuristics:**
- No alarms on a critical path → **Critical**
- No rollback plan → **Critical**
- No load test on a tier-1 service → **Critical** (internal service → **High**)
- Missing threat model → **High** (Critical if it handles PII)
- No runbook for an existing alarm → **High**
- Autoscaling exists but untested → **Medium**
- Dashboard missing one metric → **Medium**
- Naming/convention nit → **Low**

## Running the Review as Gatekeeper

1. **Before:** read the whole submission, note gaps, prepare questions. Confirm scope, tier, and launch date.
2. **Open (5 min):** confirm scope, criticality tier, timeline.
3. **Walk the domains (bulk of the time):** go section by section; let the team supply context before you classify.
4. **Classify together (~15 min):** agree severity per finding with the team in the room.
5. **Assign (~10 min):** each finding gets an owner and a target date.
6. **State sign-off criteria explicitly:** exactly what must be true for you to approve.

Be a guide, not a hammer. Lead with the operational reality ("when this pages someone…"), not authority. Acknowledge the pressure the team is under, then hold the bar.

## Most Common Real-World Gaps

1. Alarm thresholds disconnected from reality (600ms threshold when P90 is 24ms).
2. Missing data not treated as breaching — silent failures go undetected.
3. Submission outdated after a tier change (tier-1 service still has non-tier-1 answers).
4. Load test never actually run ("we'll do it before peak" — they won't).
5. Runbooks referencing deprecated tools.
6. No retry/circuit-breaker metrics — amplification invisible until it cascades.
7. Datastore capacity sized on average, not peak.
8. No emergency lever to shed load or route around failure.
9. On-call not trained for the tier they were promoted into.
10. Capacity numbers in the doc don't match what's actually deployed.

## Review Output

1. **Service context** — name, tier, new vs existing, launch date.
2. **Findings by domain** — grouped across the 10 domains.
3. **Severity per finding** — Critical/High/Medium/Low.
4. **Blocking items** — what must be resolved before sign-off.
5. **Recommendations** — prioritized actions with owners and dates.
6. **Sign-off criteria** — explicit approval conditions.

---

# Mode B: Preparing Your Service

## Quick Wins (do these before submitting)
- [ ] Every alarm links to a runbook.
- [ ] Dashboard link is current and accessible.
- [ ] On-call alias/escalation config is correct.
- [ ] Threat model exists and was reviewed in the last 12 months.
- [ ] Data classification is documented; encryption at rest + in transit confirmed.
- [ ] Dependencies are current (no stale/EOL versions).

## Evidence to Gather
| Domain | Evidence |
|--------|----------|
| Capacity | Load-test report, autoscaling config, capacity math |
| Monitoring | Dashboard URL, alarm list with thresholds + rationale |
| Deployment | Pipeline URL, bake-time config, written rollback procedure |
| Incident | Runbook links, on-call schedule, past postmortem list |
| Security | Threat model, data-classification doc, encryption proof |
| Durability | Backup-restore verification, last DR drill date |

## How to Fill the Submission
1. **No unjustified "N/A".** Explain *why* something doesn't apply.
2. **Link artifacts, not prose.** Dashboards, runbooks, and reports — not descriptions of them.
3. **Be honest about gaps.** Better to surface them than have the reviewer find them.
4. **Separate "done" from "planned".** Committed items (with tracking tickets) vs aspirational.
5. **Show the math.** Capacity calculations, not "we autoscale."

## Prep Output
1. **Current state** — green/yellow/red per domain.
2. **Gap list** — prioritized by severity.
3. **Action plan** — tasks with owners and dates.
4. **Evidence inventory** — what exists vs what to create.
5. **Timeline** — realistic path to review-ready.

## Tips
- **Review with the 3am incident in mind.** Every check is really "can on-call detect, understand, and fix this?"
- **Set the bar to blast radius and tier**, not to a fixed checklist.
- **"We'll load-test before peak" means it won't happen.** Treat an unrun load test on a critical service as blocking.
- **Missing-data-as-breaching is the cheapest high-value fix** — silent failures are the ones that hurt.
- **Link evidence, don't describe it.** A dashboard URL beats a paragraph about the dashboard.
- **This complements, not replaces, other pre-launch reviews** (design review, security review, peak/capacity planning).
