---
name: handoff
description: 会话交接。将当前调查的上下文、证据、进度压缩为交接文档，供另一个 agent 或未来的自己继续。
disable-model-invocation: true
---

# handoff

## Purpose

handoff 将当前取证调查的上下文压缩为结构化交接文档，使调查可以跨会话、跨 agent 持续。

## Use When

- 调查会话即将结束，但工作未完成
- 需要将任务交给另一个 agent
- 需要从 AFK 状态恢复调查

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `evidence_ledger` | Yes | 当前证据记录 |
| `investigation_log` | Yes | 调查日志 |
| `current_state` | Yes | 当前进度和下一步计划 |

## Outputs

| Output | Description |
|--------|-------------|
| `handoff_document` | 压缩的交接文档 |

## Workflow

### Step 1: Summarize Current State

- 调查目标
- 已完成的步骤
- 当前正在做什么
- 遇到的问题

### Step 2: Extract Key Evidence

从 evidence-ledger 提取：
- 所有 high confidence findings
- 关键 artifact 列表
- 未完成的线索

### Step 3: Document Next Steps

- 明确的下一步行动
- 需要的工具或环境
- 已知的阻塞项

### Step 4: Write Handoff Document

按以下结构写入：

```
# Handoff: <investigation name>

## Summary
<2-3 sentence summary>

## Current State
<what's done, what's in progress>

## Key Findings
<numbered list with evidence refs>

## Next Steps
<actionable next steps>

## Blockers
<known blockers>

## Evidence Ledger Reference
<path to evidence-ledger.md>
```

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `finding` | 交接文档中的每个关键发现 |
| `artifact` | 引用的每个检材 |

## Handoff

**Passes to**: 下一个 agent 或未来的自己
**Data available**: 交接文档 + evidence-ledger 文件路径

## Stop Conditions

- evidence-ledger 为空（无内容可交接）

## Notes

- handoff 文档应简洁，不复制整个 evidence-ledger
- 保存到调查工作目录，文件名 `handoff-<timestamp>.md`
- 交接文档是给人和 agent 阅读的，不是机器解析的
