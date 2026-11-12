# 测试策略

> 版本 v0.1 · 2026-11-12 · 状态：**draft，待 TASK-006 冻结**
> 维护者：`qa-audit` ｜ 会签：`architect`

---

## 一、总原则

1. **测试是验收的唯一证据。** 没有测试输出的「完成」不算完成。
2. **固定数据集 + 可重跑。** 改模型、改提示词、改算法、改表结构后，同一批数据能重跑并对比。
3. **离线优先。** CI 不联网：采集用录制响应，模型用录制回放。
4. **错误必须被植入，而不是等它自己出现。** 没有错误注入的测试体系，只能证明「顺利时能跑」。

---

## 二、12 类测试的归属与判据

| # | 类型 | 负责 | 工具 | 通过判据 |
|---|---|---|---|---|
| 1 | 单元测试 | 各模块 Agent | pytest | 覆盖率 ≥ 80%（核心模块 ≥ 90%） |
| 2 | API 测试 | architect + qa-audit | pytest + httpx | 每端点至少 1 正常 + 1 异常用例；错误码与契约一致 |
| 3 | 数据库测试 | architect | pytest + 临时 PG | 约束可被触发；迁移 upgrade/downgrade 通过 |
| 4 | 图谱查询测试 | graph-eng | pytest + 测试 Neo4j | 遍历限深/限点生效；无环爆炸；状态过滤正确 |
| 5 | Agent 输出 Schema 测试 | industry-ai | pytest + Pydantic | 畸形输出 100% 被拦截 |
| 6 | 关系扩展测试 | graph-eng + industry-ai | pytest | 深度超限报错；节点上限 `truncated` 正确 |
| 7 | 数据一致性测试 | qa-audit | pytest | PG 应入图数 == 图中数；重建前后逐属性相等 |
| 8 | 错误检测测试 | qa-audit | pytest + 注入集 | 20–30 例注入，检出率 ≥ 80%，误报 ≤ 20% |
| 9 | 前端交互测试 | frontend | Vitest + Testing Library | 关键路径可点通；`tsc --noEmit` 零错误 |
| 10 | Docker 部署测试 | devops | shell + compose | 冷启动 ≤ 90s；`/ready` 200；重启数据不丢 |
| 11 | 备份恢复测试 | devops | shell | 备份→删库→恢复→条数一致 |
| 12 | 端到端集成测试 | qa-audit + devops | pytest | 一条新闻 → 图谱可查 → 证据可见，全链路通过 |

---

## 三、固定测试数据集规格

| 数据集 | 位置 | 内容 | 用途 |
|---|---|---|---|
| `DS-01 companies` | `tests/fixtures/companies/` | 30 家 A 股公司（含 3 组易混：同名不同公司、母子公司、曾用名） | 实体消歧 |
| `DS-02 news` | `tests/fixtures/news/` | 50 条新闻，含 10 组同文转载、5 条弱相关、3 条纯传闻 | 去重、理解、防过度扩散 |
| `DS-03 evidence` | `tests/fixtures/evidence/` | A/B/C/D 四级各 10 条，含 5 组冲突证据 | 证据达标判定 |
| `DS-04 graph` | `tests/fixtures/graph/` | 200 节点 / 500 关系，含 1 条 5 跳链、1 个环、1 条断链 | 遍历与路径 |
| `DS-05 injected_errors` | `tests/fixtures/injected_errors/` | 25 个人为错误（见下表） | 错误检测 |
| `DS-06 llm_replay` | `tests/fixtures/llm_responses/` | 录制好的模型响应（含 5 条畸形输出） | 离线测 Agent |

**版本化**：数据集改动必须提 commit message 说明原因，并重跑基线。

---

## 四、错误注入清单（DS-05，25 例）

| # | 注入错误 | 期望命中规则 | 严重度 |
|---|---|---|---|
| 1 | A 公司供应商写成 B（实际 B 供 A） | REL-001 | high |
| 2 | 客户关系无任何公告支撑 | REL-003 / EVD-001 | medium |
| 3 | 同一公司建两条实体（代码相同） | DUP-001 | high |
| 4 | 同一公司建两条实体（简称相同、代码不同） | DUP-002 | high |
| 5 | 已终止的合作关系仍标 verified | TMP-002 | low |
| 6 | 子公司归属写反（父挂子） | REL-002 | critical |
| 7 | 控股关系成环 A→B→C→A | REL-002 | critical |
| 8 | 关系无 evidence 记录 | EVD-001 | critical |
| 9 | 5 家媒体转载算 5 条独立证据 | EVD-002 | high |
| 10 | D 级证据（论坛帖）支撑 verified | EVD-003 | critical |
| 11 | `valid_to` 早于 `valid_from` | TMP-001 | medium |
| 12 | verified 直接改回 candidate | STA-001 | critical |
| 13 | 传导深度 6 跳未报错 | PRP-001 | medium |
| 14 | 路径含 0.2 置信边却标"高置信" | PRP-002 | high |
| 15 | `inferred` Claim 被提升为 verified | STA-001 / CLAIM_TYPE_NOT_PROMOTABLE | critical |
| 16 | 一条新闻扩出 200 个节点无截断 | PRP-001 | medium |
| 17 | 事件影响方向写反（利好标受损） | 人工复核项 | high |
| 18 | 同一关系重复插入（三元组冲突） | ux_rel_triple | medium |
| 19 | 实体自环（A 供应 A） | ck_rel_no_self | medium |
| 20 | 股票代码格式非法（6 位以外） | VALIDATION_ERROR | low |
| 21 | 新闻发布时间为未来 3 天 | 时间校验 | low |
| 22 | 关系 confidence=1.5 | CHECK 约束 | medium |
| 23 | 撤销关系后下游 impact_path 未重算 | 重算缺失检测 | critical |
| 24 | 图中出现 candidate 状态关系 | I-1 违反 | critical |
| 25 | 模型输出缺 `claims` 字段 | Schema 校验 | high |

**特别测试（Phase 3 硬门禁）**：撤销 #6 或 #10 的关系后，系统必须：
1. 识别受影响的 `impact_path` 列表；
2. 重算这些路径；
3. 输出前后 diff；
4. 若某路径不再成立，标记 `invalidated`。

---

## 五、反幻觉测试（专项）

| 测试 | 断言 |
|---|---|
| 弱相关新闻输入 | 扩展节点数 ≤ 上限，`truncated` 正确 |
| 无证据场景 | 所有 Claim `claim_type=hypothesis`，`confidence ≤ 0.3` |
| 强行提升 | `POST /claims/{id}/promote` 对 `inferred` 返回 422 |
| 冲突证据 | 关系进 `disputed` 而非 `verified`，双方证据都保留 |
| 空 unknowns | 若 `unknowns=[]` 但 Claim 有 `inferred`，判为异常并记录 |

---

## 六、性能基线

| 场景 | 规模 | 目标 |
|---|---|---|
| 图遍历 `neighbors(depth=2)` | 10 万关系 | P95 < 300ms |
| 图遍历 `neighbors(depth=3)` | 10 万关系 | P95 < 1s |
| 公司关系列表 | 单公司 200 关系 | P95 < 50ms |
| 全量投影 | 10 万关系 | < 5 分钟 |
| 质量全量扫描 | 10 万关系 | < 3 分钟 |
| 单条新闻分析（LLM） | — | < 20s，token 成本记录 |

---

## 七、测试报告模板

```markdown
# 测试报告 TASK-xxx / phase-N

- 执行时间：2026-11-12 14:00 ~ 14:06
- 环境：Python 3.12.x / PG 16 / Neo4j 5.x / commit abc1234
- 数据集版本：DS-01@v1, DS-02@v1, DS-05@v1

## 汇总
| 项 | 数 |
|---|---|
| 测试总数 | 128 |
| 通过 | 121 |
| 失败 | 6 |
| 跳过 | 1 |

## 失败明细
| # | 用例 | 期望 | 实际 | 原因 | 归属 |
|---|---|---|---|---|---|

## 未解决问题
（必须写，没有就写"无"）

## 与上次基线对比
| 指标 | 上次 | 本次 | 变化 |
```

**禁止**只写「全部通过」而不贴实际输出。

---

## 八、待评审项（TASK-006）

1. 覆盖率 80% 是否合理？（对 AI pipeline 部分，覆盖率意义有限，可能改用「用例覆盖矩阵」）
2. 固定数据集放 `tests/fixtures/` 还是独立 `fixtures/` 仓库？（体量增长后 git 会大）
3. LLM 录制回放的格式：JSON 序列 vs VCR 风格？（需与 `LLMClient` 设计对齐）
4. 性能基线在开发机测得，是否需要容器内基准？
