---
name: call-chain-tracing
description: Trace a request or data value hop-by-hop across services, packages, and logs to find where it's transformed, filtered, or dropped. Use when asked "how does X call Y", "where does this value get lost/filtered", "trace this request/customer/order ID", "which service is dropping the field", or when debugging a failure that could live at any hop in a multi-service flow.
---

# Call-Chain Tracing

Follow one thing — a request, a field, an ID — across boundaries until you find
where reality diverges from expectation. Works two ways, usually together:

- **Static trace** (code): read the source hop-by-hop to map the intended flow.
- **Dynamic trace** (logs): follow a correlation ID across services to see what
  *actually* happened at runtime.

The discipline is the same: **pick one thread, follow it across every boundary,
verify each hop instead of assuming.**

## Step 0: Frame the Question

Write down what you're tracing and what would count as an answer *before* you
start. Vague goals produce vague traces.

| Question shape | What you're hunting for |
|----------------|-------------------------|
| "How does A reach B?" | The full path and every intermediary |
| "Where does field X get dropped?" | The hop where X is present on input but absent on output |
| "Why is request R failing?" | The first hop where R errors or gets unexpected data |
| "Does A go through B or straight to C?" | The actual next-hop, not the assumed one |

## Static Trace: Following Code Across Boundaries

### Step 1: Find the entry point

Start at the known caller. Read it to find:
- Imports — which client/wrapper/SDK it uses.
- The outbound call — method name, request builder, what data goes in.
- Config/dependency declarations — what it's wired to talk to.

### Step 2: Follow the client to the next hop

For each hop, locate the client class and read *what it actually calls
downstream* — don't stop at the wrapper.

```bash
# ripgrep is your primary tool. Find the class/handler, then read it.
rg -n "class PaymentClient" --type java
rg -n "callOperation|\.query\(|\.invoke\(|httpClient" src/payment/
```

Capture at each hop: **what's sent, what's transformed, what's filtered, error
handling, and timeout/retry config.**

### Step 3: Jump to the receiving service

Confirm the dependency (build/config file), then find the handler that receives
the call:

```bash
rg -n "PaymentRequest|/v1/charge|handleCharge" src/ --type-add 'src:*.{java,ts,py,go}' -tsrc
```

### Step 4: Repeat until a leaf

Keep hopping until you reach one of:
- An external boundary (a datastore, a third-party API, a queue).
- The answer (the hop where the value is transformed/dropped/the bug lives).
- A dead end (no further downstream call).

### Step 5: Draw the chain with data annotations

Make the transformation at each hop explicit:

```
ServiceA        sends  {userId, filters:["active"]}
 → ClientWrapper adds   timeout=5s, auth header
   → ServiceB   receives filter, queries store
     → DataStore returns full row set
   ← ServiceB   maps rows → DTO, DROPS "active" filter  ← bug is here
 ← ClientWrapper returns JSON
← ServiceA      maps to domain model
```

### What to look for at each hop

| Looking for | Where it lives |
|-------------|----------------|
| What data is sent | Method params, request builder, serialization |
| What gets filtered | Builder conditionals, `if (x != null)`, default constants |
| What's transformed | Mapper classes, `.map()`, response parsing |
| Error handling | try/catch, fallbacks, swallowed exceptions |
| Config | Timeouts, retries, feature flags |

## Dynamic Trace: Following an ID Through Logs

When you have a runtime symptom, trace a **correlation ID** across service logs.

### Step 1: Pick the correlation ID

Best IDs are the ones that survive across service boundaries:
- **Request/trace ID** — propagated in headers (`X-Request-Id`, `traceId`,
  W3C `traceparent`). Best for a single request's journey.
- **Entity ID** — a customer/order/account ID. Best for "what happened to this
  thing over time" across many requests.
- **Session/job ID** — for async or batch flows.

If services don't propagate a shared ID, that gap is itself a finding — you may
have to bridge on timestamps + entity ID.

### Step 2: Query every log source in the path at once

Search all relevant log groups/streams together and sort by time so you see the
interleaved cross-service story:

```bash
# CloudWatch Logs Insights across multiple groups (see aws-cli-safety skill)
aws logs start-query \
  --log-group-names "svc-a-app" "svc-b-app" "svc-b-requests" \
  --start-time $(date -v-24H +%s) --end-time $(date +%s) \
  --query-string 'fields @timestamp, @log, @message | filter @message like /REQUEST_ID/ | sort @timestamp asc | limit 200'
# → poll: aws logs get-query-results --query-id <ID>

# Or local/aggregated logs
rg -n "req-8f2a1c" /var/log/*/app.log | sort -t' ' -k1
```

The `@log`/source field tells you which service each line came from — that's
your hop boundary in the timeline.

### Step 3: Read the timeline for the divergence

Walk the interleaved log lines and find the first place expected != actual:

| Symptom in the timeline | Likely meaning |
|-------------------------|----------------|
| ID appears in A, never in B | A never called B (wrong branch, feature flag off, dropped message) |
| ID in A and B, error in B | B received it but failed — read B's error/stack |
| ID reaches B, response empty | Upstream dependency of B failed, or filter removed the data |
| ID present, wrong value | A transformation between the two log points mangled it |
| Big time gap between hops | Timeout/retry/queue backlog between services |

### Step 4: Confirm state at the boundary

Logs tell you flow; a point read confirms end state. Check the datastore
directly (read-only) to distinguish "never written" from "written then lost":

```bash
aws dynamodb get-item --table-name profiles --key '{"id":{"S":"REQUEST_ID"}}'
```

## When to Parallelize

- **Single chain (3–5 hops):** do it yourself, sequentially — each hop depends
  on the last.
- **Multiple independent chains:** fan out one worker per chain, then merge.
- **Comparing two paths:** trace both, then diff the hop lists.

## Tips

- **Trace one thread, not the whole system.** One ID, one field, one request — breadth comes from following it fully, not from reading everything.
- **Verify every hop; never assume the obvious path.** Services take surprising routes (through a gateway, a queue, a cache) — confirm the actual next-hop in code or logs.
- **Static + dynamic together.** Code shows the *intended* flow; logs show the *actual* flow. The bug is usually where they disagree.
- **Don't stop at the wrapper.** A client wrapper hides the real downstream call — read what it actually invokes.
- **A missing correlation ID is a finding.** If you can't follow one ID across a boundary, the tracing gap is worth fixing (and forces you onto timestamps).
- **Read the divergence, not the whole log.** Find the first hop where expected != actual; everything after is usually downstream fallout.
- **Point-read the datastore to disambiguate** "never written" vs "written then overwritten/deleted".
