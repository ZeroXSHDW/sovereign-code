---
name: report-writer
description: 通用报告输出。从 evidence-ledger 读取证据，生成结构化取证报告或竞赛 WriteUp。不绑定特定比赛或输出格式。
disable-model-invocation: false
---

# report-writer

## Purpose

report-writer 是通用报告输出 skill。从 evidence-ledger 读取证据记录，生成结构化的取证报告或竞赛 WriteUp。

本 skill 从 `iscc-wp-writer` 抽取通用报告规则，不保留 D 盘路径绑定、ISCC Word 模板等比赛专用逻辑。比赛专用版在 `skills/competition/iscc-wp-writer/`。

## Use When

- answer-gate 校验通过后，需要生成最终报告
- forensic-autopilot 的 Step 8（Report）
- 用户要求输出调查结果

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `evidence_ledger` | Yes | 完整的证据记录 |
| `findings` | Yes | 结论列表 |
| `timeline` | Recommended | 事件时间线 |
| `output_format` | No | 输出格式（markdown/html/docx），默认 markdown |

## Outputs

| Output | Description |
|--------|-------------|
| `report` | 结构化报告文件 |
| `report_path` | 报告文件路径 |

## Workflow

### Step 1: Gather Evidence

从 evidence-ledger 读取所有相关条目：
- 按 category 分组（acquisition, analysis, validation, negative）
- 按 confidence 排序（high → medium → low）
- 识别关键证据链

**Evidence**: 记录读取的 evidence entry 数量和分类

### Step 2: Structure Report

按 `templates/forensic-report.md` 结构组织：
1. Executive Summary
2. Scope（检查了什么、没检查什么）
3. Methodology
4. Findings（每个 finding 绑定证据）
5. Timeline
6. Negative Findings
7. Conclusions
8. Recommendations
9. Appendix: Evidence Ledger

**Evidence**: 记录报告结构

### Step 3: Write Findings

每个 finding 必须包含：
- 标题
- Confidence level
- Evidence 表格（Artifact, Source, Hash, Command）
- 详细描述
- Significance

**Evidence**: 记录每个 finding 的证据绑定

### Step 4: Generate Output

根据 output_format 生成最终文件：
- Markdown: 直接写入 .md 文件
- HTML: 转换为 HTML
- DOCX: 使用 python-docx 生成（如可用）

**Evidence**: 记录输出文件路径

### Step 5: Validate Report

检查报告完整性：
- [ ] 每个 cited finding 有对应 evidence entry
- [ ] 无幻觉路径或不存在的 artifact
- [ ] 时间线一致
- [ ] 无残留占位符或模板文本

## Evidence Requirements

| Field | When to Record |
|-------|---------------|
| `artifact` | 报告引用的每个检材 |
| `finding` | 报告中的每个结论 |
| `confidence` | 每个结论的置信度 |
| `command` | 生成报告的命令 |

## Handoff

**Passes to**: 用户（最终产物）
**Data available**: 完整的报告文件

## Stop Conditions

- evidence-ledger 为空（无证据可报告）
- 证据不足以支撑结论（返回补充分析）
- 输出格式不可用（如要求 DOCX 但 python-docx 未安装）

## Notes

- 报告必须引用 evidence-ledger 中的真实证据，不可编造
- 负面发现（"未找到 X"）也是重要报告内容
- 比赛专用报告模板在 `skills/competition/`
- 通用报告模板在 `templates/forensic-report.md`
- 竞赛 WriteUp 模板在 `templates/wp-template.md`
