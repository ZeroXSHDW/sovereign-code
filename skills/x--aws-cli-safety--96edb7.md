---
name: aws-cli-safety
description: Use the AWS CLI safely and effectively — read-before-write, least-privilege profiles, extreme caution in production, and query/filter/paginate patterns. Use when running any `aws` command, inspecting cloud resources, debugging in an AWS account, or when the user asks to check/list/describe/modify/delete AWS infrastructure.
---

# AWS CLI Safety

A discipline for operating the AWS CLI without causing outages or data loss.
The core rule: **default to read, escalate to write only deliberately, and treat
every account as production until proven otherwise.**

## Mental Model: Read → Confirm → Write

Every AWS API call falls into one of three buckets. Know which one you're in
*before* you press enter.

| Bucket | Verbs | Blast radius | Default posture |
|--------|-------|--------------|-----------------|
| **Read** | `describe-*`, `list-*`, `get-*`, `head-*` | None (data exposure only) | Do freely with a read-only role |
| **Mutating** | `create-*`, `put-*`, `update-*`, `modify-*`, `attach-*`, `set-*` | Changes live state | Confirm intent, prefer non-prod, use `--dry-run` |
| **Destructive** | `delete-*`, `terminate-*`, `remove-*`, `revoke-*`, `disable-*`, `detach-*` | Data loss / outage | Explicit human confirmation, never guess |

## Rules That Prevent Incidents

1. **Read before you write.** Always `describe`/`get` the resource first to
   confirm you're targeting the right thing and to capture its current state
   (so you can undo).
2. **Least privilege.** Use a read-only / view-only role or profile for anything
   that doesn't require write access. Reserve admin credentials for the specific
   mutating call, then drop back down.
3. **Assume production when uncertain.** If you can't prove an account/resource
   is dev/test/staging, treat it as production and act with maximum caution.
4. **Confirm destructive actions with a human.** Never run `delete`/`terminate`/
   `modify` against production without explicit confirmation, and state the
   impact plainly first.
5. **Never disable safety protections** (termination protection, deletion
   protection, versioning, backup retention, MFA-delete) without explicit
   confirmation and a clear reason.
6. **Prefer `--dry-run`** on any call that supports it (most EC2 mutations do) to
   validate permissions and parameters without executing.

## Identifying What You're Pointed At

Before any mutating call, verify **who you are** and **where you are**:

```bash
aws sts get-caller-identity            # which account + role/principal
aws configure list                     # active profile, region, cred source
echo "$AWS_PROFILE  $AWS_REGION"        # env overrides
```

Production signals in resource names/tags/account aliases: `prod`, `production`,
`prd`, and the *absence* of `dev`/`test`/`beta`/`alpha`/`staging`/`sandbox`.
When in doubt, it's prod.

## Profiles and Credentials

Keep environments in named profiles so you never fat-finger prod:

```bash
aws s3 ls --profile myapp-readonly              # read with a scoped role
aws configure list-profiles                     # what profiles exist
```

- Give read-only work a **dedicated view-only profile** and use it by default.
- Scope roles to the minimum actions needed; broad `*:*` admin roles are a
  last resort for a single known call.
- If a command returns `AccessDenied`, read the denied action in the error and
  request exactly that permission — don't broaden to admin to "make it work".

## Querying, Filtering, and Paginating

Cut noise at the source. Two layers: server-side (`--filters`, cheaper) and
client-side (`--query` JMESPath, flexible). Pipe to `jq` for anything complex.

```bash
# Server-side filter (done in the API — preferred for large result sets)
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running" "Name=tag:env,Values=prod" \
  --query 'Reservations[].Instances[].{id:InstanceId,type:InstanceType,ip:PrivateIpAddress}' \
  --output table

# Client-side shaping with --query (JMESPath)
aws s3api list-buckets --query 'Buckets[?starts_with(Name, `logs-`)].Name' --output text

# Hand off to jq when JMESPath isn't enough
aws logs describe-log-groups --output json \
  | jq -r '.logGroups[] | select(.storedBytes > 1e9) | .logGroupName'
```

Pagination gotchas:

- The CLI **auto-paginates by default** and can hang on huge result sets. Cap it:
  `--max-items 50`, or `--no-paginate` for a single page, or `--page-size 100`
  to tune per-request size.
- Set `--output json|table|text` explicitly in scripts; don't rely on the
  configured default.

## Common Read Patterns

```bash
# CloudWatch Logs Insights across multiple log groups (BSD/macOS date shown)
aws logs start-query \
  --log-group-names "app-logs" "request-logs" \
  --start-time $(date -v-24H +%s) --end-time $(date +%s) \
  --query-string 'fields @timestamp, @log, @message | filter @message like /REQUEST_ID/ | sort @timestamp asc | limit 200'
# → returns a queryId; poll with:
aws logs get-query-results --query-id <ID>

# DynamoDB point read
aws dynamodb get-item --table-name my-table --key '{"pk":{"S":"value"}}'
```

> Date math differs by OS: `date -v-24H +%s` (BSD/macOS) vs
> `date -d '24 hours ago' +%s` (GNU/Linux).

## Before a Destructive Call — Checklist

1. `sts get-caller-identity` — right account, least-privilege role?
2. `describe`/`get` the target — is this exactly the resource you mean?
3. Captured current state for rollback?
4. Is a safety protection in the way? If so, that's a signal — don't disable it silently.
5. Prod? → get explicit human confirmation and state the impact.
6. Supports `--dry-run`? → run it first.

## Tips

- **`describe` first, always.** It's free, it confirms your target, and it gives you the state to roll back to.
- **Auto-pagination will bite you** on big accounts — cap with `--max-items` or `--no-paginate`.
- **`--query` runs client-side, `--filters` runs server-side.** For large result sets, filter server-side to save time and money.
- **A widening `AccessDenied` loop is a smell.** Read the exact denied action instead of reaching for admin.
- **Two-name safety:** keep prod behind a distinctly-named profile so `--profile` typos fail closed, not open.
- **Never disable a guardrail to unblock yourself** — termination/deletion protection and versioning exist precisely for the moment you're in.
