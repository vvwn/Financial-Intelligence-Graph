# Agent 职责总表与边界矩阵

> 版本 v0.1 · 2026-11-12 · 维护者：`architect`
> 单份职责文件见 [docs/agents/](agents/)。本文件只做**汇总与冲突裁决**，细节以单份文件为准。

---

## 一、一张表看清谁管什么

| 关注点 | 唯一负责人 | 参与方 | 冲突裁决 |
|---|---|---|---|
| 总体架构 / 契约冻结 | `architect` | 全体会签 | architect |
| PG 表结构 / Migration | `architect` | graph-eng、data-eng 提需求 | architect |
| 数据采集 / 去重 / 入库 | `data-eng` | qa-audit 验证 | architect |
| 图 Schema / 投影 / 遍历 | `graph-eng` | architect 会签 | architect |
| 新闻理解 / Claim 抽取 / 传导 | `industry-ai` | qa-audit 打假 | architect |
| 关系状态机 / 规则引擎 / 测试集 | `qa-audit` | architect 会签 | architect |
| 前端页面 / 可视化 | `frontend` | graph-eng 提供查询契约 | architect |
| 容器 / 部署 / 健康检查 | `devops` | architect 定义端点 | architect |
| 项目状态 / 任务看板 | `architect` | 全体更新自己那行 | architect |

**原则：每个关注点有且只有一个负责人。没有负责人的东西 = 不会有人做。**

---

## 二、数据流上的交接点（最容易扯皮的地方）

| 交接点 | 上游产出 | 下游消费 | 契约文件 | 验收方式 |
|---|---|---|---|---|
| ① 原始信息 → 标准化新闻 | `data-eng`：`news_event` | `industry-ai` | `database-schema.md` | 幂等 + 去重测试 |
| ② 新闻 → Claim | `industry-ai`：`ClaimCandidate` | `qa-audit` / `architect` | `agents/outputs.py` + `api-contracts.md` | Schema 校验 + 反幻觉测试 |
| ③ Claim + Evidence → 关系状态 | `qa-audit` 规则判定 | `architect` 审批 | 状态机定义 | 状态迁移测试 |
| ④ 已验证关系 → 图谱 | `graph-eng`：`GraphProjector` | 前端 / 传导算法 | `graph-schema.md` | 投影幂等 + 重建等价 |
| ⑤ 图谱 → 界面 | `graph-eng` / `architect` API | `frontend` | `api-contracts.md` | OpenAPI 生成类型通过 tsc |
| ⑥ 全链路 → 环境 | `devops` | 全体 | `deployment.md` | 冷启动 + `/ready` |

**规则：交接点必须有测试。没有测试的交接点 = 定时炸弹。**

---

## 三、禁止越权清单（高频事故）

| 行为 | 违规方 | 正确做法 |
|---|---|---|
| 在采集器里判断「这家公司属于哪个产业」 | data-eng | 交 industry-ai 出 Claim |
| 在 Cypher 里写 `WHERE confidence > 0.6` 来过滤 | graph-eng | 规则归 qa-audit，图只存事实与状态 |
| 让模型输出直接 UPDATE `relationship.status='verified'` | industry-ai | 只能写 Claim，状态迁移走 state_guard |
| 为了让测试通过改测试断言 | qa-audit | 报 bug + 复现案例给对应 Agent |
| 前端 `as any` 绕过类型不匹配 | frontend | 提契约变更请求 |
| 在 compose 里改后端依赖版本 | devops | 提依赖变更给 architect |
| 顺手给 `entity` 表加字段 | 任何人 | 提 Migration 请求给 architect |

---

## 四、Agent 启用计划（按阶段）

| 阶段 | 活跃 Agent | 说明 |
|---|---|---|
| Phase 0 | architect（+ qa-audit 参与评审） | 只出文档与契约，不写业务代码 |
| Phase 1 | architect, graph-eng, data-eng(种子数据), qa-audit, devops | 图谱底座 |
| Phase 2 | + industry-ai | 采集与 AI 扩展 |
| Phase 3 | qa-audit 主导 | 质量控制与纠错 |
| Phase 4 | frontend 主导 | Web 工作台 |
| Phase 5 | industry-ai + 新增「投资研究」能力 | 投资分析 |

**暂不启用**：Agent 5 在 Phase 4 前只做设计原型与 Mock 页面，不接真 API。

---

## 五、动态调整记录

| 日期 | 调整 | 原因 | 影响 |
|---|---|---|---|
| 2026-11-12 | 初版建立 7 个角色 | Phase 0 启动 | 无 |
