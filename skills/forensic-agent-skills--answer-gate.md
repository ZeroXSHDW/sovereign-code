---
name: answer-gate
description: 通用答案校验门。在提交任何结论前执行五步校验：Question Semantics、Answer Format、Evidence Binding、Cross-Validation、Final Evidence Re-read。
disable-model-invocation: false
---

# answer-gate

## Purpose

answer-gate 是提交前的最后一道校验。它从 evidence-ledger 读取所有证据，对即将提交的答案执行五步校验，确保结论有据可依、格式正确、无自相矛盾。

本 skill 从 `server-answer-gate` 泛化而来，五步校验逻辑适用于所有取证场景，不仅限于服务器。

## Use When

- 准备提交答案、flag、结论前（必经步骤）
- forensic-autopilot 的 Step 7（Validate）
- 任何 skill 准备输出最终结论前

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `question` | Yes | 原始问题或目标 |
| `proposed_answer` | Yes | 拟提交的答案 |
| `evidence_ledger` | Yes | 完整的证据记录（优先读取 `evidence-ledger.jsonl`；JSONL 不存在时回退到 `evidence-ledger.md`） |
| `target_type` | Yes | 答案主体类型字符串；至少支持 `cluster`、`pve-node`、`guest-vm`、`web-application`、`database`，其他领域使用证据化的明确类型 |
| `target_ref` | Yes | 题目所指对象的稳定引用；必须能回指 Route、Artifact 或已登记的调查对象 |
| `expected_evidence_type` | Yes | 该题允许支持答案的证据类型 |

## Outputs

| Output | Description |
|--------|-------------|
| `verdict` | `pass` / `needs_fix` / `not_locally_reproduced` |
| `check_results` | 每步校验的结果 |
| `issues` | 发现的问题列表（如有） |

`target_type`、`target_ref`、`expected_evidence_type` 及其比较结果只放入现有 Response Envelope 的 `payload.check_results`；不得把这些字段塞入 Route Step、Finding Record 或另建答案记录。发现冲突时在 `payload.issues` 中输出 `issue_type: evidence_conflict`，同时令 `verdict: needs_fix`，不扩展既有 verdict 枚举。

```yaml
payload:
  verdict: pass|needs_fix|not_locally_reproduced
  check_results:
    target_type: string
    target_ref: string
    expected_evidence_type: string
    observed_evidence_types: []
    target_match: pass|fail
    evidence_type_match: pass|fail
  issues: []
```

| target_type | 直接证据示例 |
|-------------|-------------|
| `cluster` | Corosync/Ceph/Pool/RBD 的直接状态输出 |
| `pve-node` | 对应宿主的运行态、证书、网络或配置 Artifact |
| `guest-vm` | Guest 运行态、控制台、网络、服务或文件系统 Artifact |
| `web-application` | 目标应用的源码、配置、访问/应用日志或运行态输出 |
| `database` | 确定性 SQL 结果或离线 dump 解析 Artifact |

表中是必须支持的服务器类型，不是封闭枚举，也不替代题目指定的 `expected_evidence_type`；其他取证领域同样必须逐题绑定明确主体和证据类型。

## Workflow

### Check 1: Question Semantics

- [ ] 我理解问题在问什么
- [ ] 我的答案直接回答了问题（不是相关但不同的问题）
- [ ] 我没有假设问题或证据中不存在的信息
- [ ] 答案格式匹配要求（IP、域名、时间戳、flag 等）
- [ ] `target_type` 和 `target_ref` 与题面主体一致，且 `expected_evidence_type` 能支持该类答案
- [ ] cluster-level 与 guest-level 对象没有被描述为同一台服务器

**宿主与 Guest 强制边界**：

- `target_type: pve-node` 的问题只能引用对应 PVE 宿主证据；Guest 的内核、IP、服务或配置不能支持宿主答案。
- `target_type: guest-vm` 的问题不能用 PVE 宿主的内核、IP 或配置替代 Guest 证据；必须引用目标 Guest 或其已验证文件系统/服务。
- `cluster`、`web-application` 和 `database` 同样必须由 `target_ref` 锁定主体，跨主体证据只能用于交叉验证，不能替代直接证据。

**Evidence**: 记录语义校验结果

### Check 2: Answer Format

- [ ] 答案匹配预期格式（IPv4、email、ISO 时间戳、flag{...} 等）
- [ ] 无多余空格、换行或格式残留
- [ ] 大小写正确（flag、密码、hash）
- [ ] 数值在正确单位/范围内
- [ ] “前 N 位”或“后 N 位”已按题面字符口径执行精确计数，并保留原始值 Artifact/Ledger 引用和计数结果

**Evidence**: 记录格式校验结果

### Check 3: Evidence Binding

- [ ] 答案的每个组成部分至少有一条 evidence entry
- [ ] evidence entry 引用真实存在的 artifact（非幻觉路径）
- [ ] 能指向支持每个答案组件的具体命令输出或文件内容
- [ ] hash 值在声称完整性的地方匹配
- [ ] evidence 的主体与 `target_type`、`target_ref` 一致，且类型匹配 `expected_evidence_type`

以下答案类型必须满足额外绑定要求：

- **PVE 加入集群证书指纹**：必须先识别并验证实际集群加入流程使用的证书或指纹来源，再由该证书计算 SHA-256。证据必须保存证书角色、实际路径或来源引用、证书 Artifact 和 SHA-256 计算输出；不得把某个固定路径假定为所有 PVE 环境的唯一来源。SSH `known_hosts`、SSH 公钥指纹或其他无关摘要不能替代。
- **时间戳**：必须引用时区依据（原始日志时区、系统时区配置、应用配置或等价 Artifact）。缺少时区依据时不得输出高置信的标准化时间；应降级结论并返回补证。
- **字符串截取**：记录未截取原始值的引用、N 的精确值、字符计数口径和截取结果，不能只保存最终片段。
- **数据库答案**：必须绑定确定性 SQL 或离线 dump 的可复现解析结果，并保存完整查询、目标表、结果 Artifact、`row_count` 和结果 Hash。滚动到“最后一行”、截图观察或视觉估算不能作为数量答案。

**Evidence**: 记录每个答案组件对应的 evidence entry

### Check 4: Cross-Validation

- [ ] 没有与本次调查中其他 finding 矛盾
- [ ] 时间线事件一致（没有把未来事件当过去引用）
- [ ] 多个证据源在重叠处一致
- [ ] 负面发现不与正面发现矛盾
- [ ] 查询结果、题面约束和候选答案彼此一致

任一来源与候选答案不一致时，保留全部原始引用并输出：

```yaml
issue_type: evidence_conflict
target_type: string
target_ref: string
evidence_refs: []
description: string
```

存在 `evidence_conflict` 时不得自行选择其中一个答案并标记 `pass`。

**Evidence**: 记录交叉验证结果

### Check 5: Final Evidence Re-read

- [ ] 重新阅读了支持答案的原始 artifact
- [ ] 证据内容与我的理解一致（无误读）
- [ ] 没有选择性忽略矛盾证据
- [ ] confidence level 有依据

**Evidence**: 记录最终复核结果

### Final Verdict

- **PASS**: 五步全部通过，可提交
- **NEEDS FIX**: 一步或多步失败，返回补充证据
- **NOT LOCALLY REPRODUCED**: 无法在本地验证，需人工审查

主体错配、证书指纹来源不符、时间缺少时区依据、截取无法复算、数据库结果不确定或存在 `evidence_conflict` 时，至少为 **NEEDS FIX**，不得 PASS。

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `artifact` | 被校验的答案和相关证据 |
| `finding` | 每步校验结果 |
| `confidence` | 校验结论置信度 |

校验 Finding 必须引用实际 Ledger Event，且只能使用 `templates/finding-record.schema.json` 已允许的字段：`schema_version`、`finding_id`、`description`、`confidence`、`evidence_refs`，以及可选的 `artifact_refs`、`category`、`related_skill`、`created_at`。`target_type`、`target_ref`、`expected_evidence_type` 与期望/实际证据类型的比较结果只能写入 Response `payload.check_results`；Finding 可在 `description` 中概述校验结论，但不得增加同名或其他 Schema 未定义字段。数据库数量答案的 Finding 必须通过 `evidence_refs`/`artifact_refs` 回指完整查询、结果 Artifact、`row_count` 和结果 Hash。

## Handoff

**Passes to**: `report-writer`（校验通过后）或返回 domain skill（校验失败后补充证据）
**Data available**: 校验结果和发现的问题

## Stop Conditions

- 校验失败且无法自动修复（返回 forensic-autopilot 补充分析）
- 答案无法在本地复现（标记为 not_locally_reproduced）
- 发现证据矛盾（需要人工审查）
- 答案证据属于错误主体，或无法证明 `target_ref`

## Notes

- answer-gate 是强制步骤，不可跳过
- 五步校验逻辑适用于所有场景（服务器、CTF、固件、恶意样本等）
- `evidence_conflict` 是 `issues` 中的失败类型，不是新的 Route、Finding 或 verdict 结构
- Answer Gate 不扩展 Finding Record；主体和证据类型比较只存在于 Response `payload.check_results`
- 详见 `templates/answer-gate-checklist.md`
