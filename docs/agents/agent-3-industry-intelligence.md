# Agent 3 — AI 产业研究员（Industry Intelligence Agent）

- **代号**：`industry-ai`
- **层级**：Agent 3
- **职责文件版本**：v0.1 · 2026-11-12

---

## 1. 工作目标

把一条新闻，变成**结构化的、带证据引用的、可被质疑的**产业分析结果：
事件 → 实体 → 关系候选（Claim）→ 传导路径假设。

**核心纪律：你输出的是 Claim，不是事实。** 你的产出必须能被 Agent 4 逐条打假。

## 2. 负责模块

| 模块 | 路径 |
|---|---|
| 新闻理解流水线 | `backend/app/agents/pipeline.py` |
| 事件分类 | `backend/app/agents/event_classifier.py` |
| 实体识别与链接 | `backend/app/agents/entity_linker.py` |
| 关系候选抽取 | `backend/app/agents/relation_extractor.py` |
| 传导路径生成 | `backend/app/agents/propagation.py` |
| 提示词库 | `backend/app/agents/prompts/` |
| 模型适配层 | `integrations/llm/`（provider 无关接口 + 各厂商 adapter） |
| 结构化输出 Schema | `backend/app/agents/outputs.py`（Pydantic，与 Agent 0 会签） |

## 3. 允许 / 禁止修改

**允许写入**：
```
backend/app/agents/
integrations/llm/
backend/tests/test_agents*.py
backend/tests/fixtures/llm_responses/
reports/development/
```

**只读**：`backend/app/models/`、`schemas/`、`docs/api-contracts.md`、`backend/app/graph/`

**禁止**：
- 直接写 `relationship` 表为 `verified` 状态（只能写 `candidate` Claim）
- 直接写 Neo4j（任何情况下）
- 在业务代码里 `import openai` / `import anthropic` —— 必须经 `integrations/llm/base.py` 的 `LLMClient` 协议
- 把模型返回的自由文本直接入库（必须过 Pydantic 校验，失败则记 `parse_error` 并降级）

## 4. 输入数据

| 输入 | 形式 |
|---|---|
| `news_event` 记录 | PG，含正文与来源 |
| 已有实体库 | `entity` 表（含 aliases、stock_code） |
| 已有图谱邻域 | Agent 2 的 `neighbors(depth=1)`，作为消歧与扩展的锚点 |
| 产业分类体系 | `database/seeds/industries.yaml` |

## 5. 输出数据

统一 Pydantic 模型（`outputs.py`），每条结果必须能区分四类成分：

```python
class ExtractionResult(BaseModel):
    event: EventCandidate            # 事件类型、涉及主体、时间
    entities: list[EntityMention]    # mention + 链接到已有 entity_id 或 linked=None
    claims: list[ClaimCandidate]     # subject/predicate/object + claim_type + confidence
    unknowns: list[str]              # 明确无法确定的信息
    needs_human_review: list[str]    # 需要人工核验的点
    evidence_refs: list[EvidenceRef] # 每条 claim 必须至少引用 1 条（可为 D 级）
```

`claim_type` 枚举（不可扩展，需变更走 ADR）：
`fact_reported`（媒体陈述的事实）｜`inferred`（AI 推断）｜`hypothesis`（假设，待验证）｜`disputed`（存在冲突）

**硬规则**：
- `claim_type=inferred/hypothesis` 的 Claim，`confidence` 上限 0.6，且不得进入 `verified`。
- 每条 Claim 必须有 `evidence_refs`；无证据的 Claim 只能标 `hypothesis` 且 `confidence ≤ 0.3`。
- 输出中必须显式列出 `unknowns`——**空列表等于声称「我什么都确定了」，需要理由**。

## 6. API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/analyze/news/{id}` | 触发单条新闻分析（幂等，重复调用返回同一 analysis_id） |
| GET | `/api/v1/analyze/{analysis_id}` | 分析结果（含 claims、unknowns、token 成本） |
| POST | `/api/v1/events/{id}/propagate` | 生成传导路径（受深度/节点上限约束） |
| GET | `/api/v1/events/{id}/impact-paths` | 路径列表 + 每条路径的证据数与质量分布 |

## 7. 依赖模块

| 依赖 | 提供方 | 状态 |
|---|---|---|
| `news_event` 数据 | Agent 1 | TASK-101 |
| 实体库与别名表 | Agent 0（Schema）+ Agent 1（数据） | TASK-003 |
| 图谱邻域查询 | Agent 2 | TASK-202 |
| Claim Schema 冻结 | Agent 0 | TASK-004 |
| 错误注入用例（用于自测过度扩散） | Agent 4 | TASK-402 |

## 8. 测试要求

- **Schema 合规**：所有输出过 Pydantic；构造畸形模型输出（缺字段/多字段/中文枚举）必须被拦截。
- **禁止幻觉升级**：断言 `inferred` 的 Claim 无法通过任何代码路径变成 `verified`。
- **可复现**：固定 `temperature=0` + 录制回放 fixture，同一输入两次运行输出一致。
- **过度扩散检测**：给一条弱相关新闻，断言扩展节点数 ≤ 上限且 `truncated` 正确。
- **成本可观测**：每次分析记录 token 数与耗时，写入 `analysis_run`。
- **离线可跑**：CI 使用录制的模型响应，不打真实 API。

## 9. 验收标准

- [ ] 输入一条真实新闻，输出：事件、实体、Claim、证据引用、未知项、待人工核验项
- [ ] 每条 Claim 能追溯到具体证据或明确标为假设
- [ ] 无证据的推断不会出现在 `verified` 关系中
- [ ] 模型可切换（至少 2 个 provider 跑通同一接口）
- [ ] 输出 100% 通过 Schema 校验

## 10. 明确不负责

新闻真实性最终裁定（Agent 4）、关系状态迁移审批（Agent 4 + 人工）、投资建议（Phase 5 独立模块）、图谱写入（Agent 2）。
