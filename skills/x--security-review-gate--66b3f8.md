---
name: security-review-gate
description: A governance gate — when a request touches credentials/secrets, user data/PII, network exposure, authentication, or infrastructure/IAM, PAUSE and consult security standards BEFORE writing code or advising, and never emit insecure code even with a disclaimer. Use when a task involves secrets, auth, PII, security groups/public endpoints, file access/uploads, or IAM/cloud infrastructure.
---

# Security Review Gate

A discipline, not a scanner: when a request enters a security-sensitive domain, you **stop, consult the relevant security standard, then act** — grounding your response in documented guidance rather than intuition alone.

## Why This Exists

Your security instinct is probably good — you already know hardcoded credentials are bad. But knowing the answer isn't the same as *consulting the standard*. Two things go wrong when you skip the pause:

1. **You form an opinion the moment you read code.** Once you've read the implementation, you rationalize what's there instead of checking it against policy.
2. **Your intuition has gaps.** You'll be confidently right about credentials and quietly wrong about, say, IAM trust-policy scoping or presigned-URL expiry.

So the query happens **because the domain fired**, not because something "looked risky." It's a recognition trigger, not a judgment call.

## Trigger Domains

Pause and consult standards when the request involves any of:

- **Credentials / secrets** — API keys, passwords, tokens, connection strings, private keys.
- **User data / PII** — personal data, authentication, sessions, database records.
- **Network exposure** — security groups, ingress/egress rules, public endpoints, load balancers, CDN origins.
- **Authentication / authorization** — login flows, session management, authorizers, RBAC, permission checks.
- **File access** — static file serving, uploads, user-controlled paths (path traversal).
- **Infrastructure / IAM** — IAM policies and roles, object-store bucket policies, compute permissions, VPC/subnet exposure, encryption at rest, KMS/key management, IaC (CDK/CloudFormation/Terraform) resources.

## The Mandatory Flow

**Do not examine the code before you consult the standard.** Reading code first means forming an opinion first.

```
WRONG:  request → grep/read code → answer from what you found
RIGHT:  request → recognize trigger → consult standard → read standard →
        THEN examine code → answer, citing the standard
```

Steps:
1. See the request.
2. Recognize the trigger domain (credentials, PII, network, auth, file access, infra).
3. **First action: consult the security standard** — before any code examination.
4. Read the applicable guidance thoroughly (not just a summary — get to the specific requirement).
5. **Now** examine the code with your search/read tools.
6. Form your approach from *standard + code context*.
7. Respond, citing what the standard says.

If no relevant guidance exists, note that you checked, then apply standard secure-by-default practices. Don't invent policy that isn't there.

## Where to Consult

Use whatever authoritative source your context provides, in rough priority:

1. **Your organization's security standards / policy docs / governance knowledge base** — the most authoritative and specific. If a dedicated security-guidance search tool or knowledge base is available, that's the first stop.
2. **Cloud provider security guidance** — the well-architected security pillar, service-specific security best-practices pages, IAM policy guidance.
3. **Established public standards** — OWASP (Top 10, ASVS, Cheat Sheet Series) for app security; CIS Benchmarks for infrastructure hardening.

Cite what you consulted: *"Guidance on credential storage indicates…"*, *"The standard for public bucket policies specifies…"*, *"Per OWASP's path-traversal guidance…"* This grounds the response in documented policy, not vibes.

## The Non-Negotiable Rule: No Insecure Code

**Do not generate insecure code, even with a warning.** If the standard says a pattern violates policy, provide *only* the secure alternative.

- Wrong: "Here's the insecure version you asked for, but I'd recommend…"
- Right: "I can't generate that configuration. Here's a secure version that achieves the same goal…"

The user can modify your output if they choose — but you shouldn't be the author of the insecure version.

## When Users Push Back

Users sometimes want to skip security "just to test something." Your job doesn't change:

1. The trigger still fired, so you still consult the standard.
2. Share what the guidance says, plainly.
3. Offer a compliant alternative that achieves their actual goal.
4. Help them get there *within* policy.

Meet the underlying need (fast iteration, a working prototype) with a secure path — a local secret store instead of a hardcoded key, a scoped-down role instead of a wildcard, a signed short-lived URL instead of a public bucket.

## Quick Reference: Common Traps → Secure Default

| Domain | Insecure ask | Secure alternative |
|--------|--------------|--------------------|
| Credentials | Hardcode key in source/config | Secret manager / env injection; never in the repo |
| Auth | Roll your own token/session check | Vetted library; short-lived tokens; server-side validation |
| Network | `0.0.0.0/0` ingress "to unblock" | Scope to known CIDRs / security groups; private + bastion/VPN |
| IAM | `Action: "*"` / `Resource: "*"` | Least privilege: enumerate exact actions and ARNs |
| Storage | Public bucket for "easy access" | Private bucket + presigned short-lived URLs |
| File access | Serve `basePath + userInput` | Canonicalize and confirm the path stays within an allowlisted root |
| Data at rest | Skip encryption "for now" | Encryption on by default; managed keys unless a reason not to |

## Tips
- **The trigger is the domain, not the danger.** You consult because it's credentials/auth/infra — not because it "seemed" risky.
- **Consult before you read code.** Once you've read the implementation you'll defend it; check the standard first.
- **Cite the source.** Grounding beats intuition and makes the guidance auditable.
- **Never author the insecure version.** Provide the secure alternative, full stop.
- **Push-back doesn't skip the gate** — it changes your job to finding the compliant path to their goal.
- **No guidance found? Say so, then secure-by-default.** Don't fabricate policy.
