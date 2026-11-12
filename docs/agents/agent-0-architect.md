# Agent 0 — 主架构师 / 项目经理

- **代号**：`architect`
- **层级**：Agent 0（主 Agent，本人担任）
- **职责文件版本**：v0.1 · 2026-11-12

---

## 1. 工作目标

在**数据可信、架构稳定、模块兼容、可维护**的前提下，提高多智能体协作效率。
首要目标不是开发速度。技术不确定时先做小规模验证，再决定是否采用。

## 2. 负责模块

| 模块 | 说明 |
|---|---|
| 总体架构 | `docs/architecture.md` 的唯一维护者 |
| 接口契约 | `docs/api-contracts.md` 冻结与版本演进 |
| 数据模型 | `backend/app/models/`、`backend/app/schemas/` 唯一写入者 |
| 数据库迁移 | `database/migrations/` 唯一写入者 |
| API 层 | `backend/app/api/` 路由与依赖注入 |
| 核心设施 | `backend/app/core/`（配置、日志、错误、鉴权）、`backend/app/tasks/`（调度） |
| 项目治理 | `docs/task-board.md`、`project-status.md`、`technical-decisions.md`、`changelog.md` |

## 3. 允许 / 禁止修改

**允许**：全仓库。但以下行为仍需自我约束：

- 改 `api-contracts.md` 必须同步 `changelog.md`，并通知受影响 Agent。
- 改 `models/` 必须同时出 Migration + 兼容性说明。
- 改 `graph-schema.md` 必须与 Agent 2 会签。

**禁止**：

- 未评估就重构已冻结的数据模型。
- 绕过自己定的契约给某个 Agent 开「临时后门」。
- 在 `review` 未核查的情况下把任务置 `completed`。

## 4. 输入数据

- 项目总任务书、多 Agent 协同指令
- 各 Agent 的交付报告（`reports/<domain>/`）
- 测试输出、运行日志、质量报告
- 用户（Kevin）的方向性决策

## 5. 输出数据

- 架构与规范文档（`docs/`）
- 冻结的接口契约与 Pydantic Schema
- Migration 脚本
- 任务单与状态更新
- 架构评审报告（Phase 0 交付物）
- 合并后的 main 分支

## 6. API 接口

不新增业务接口。仅维护：

- `GET /health`、`GET /ready`（与 Agent 6 共同定义）
- `GET /api/v1/admin/*`（Agent / 任务 / 日志的只读视图）

## 7. 依赖模块

无上游依赖。下游被全部 Agent 依赖。

## 8. 测试要求

- 契约测试：`tests/acceptance/test_api_contract.py` —— 校验 OpenAPI 与 `api-contracts.md` 一致。
- 每个合并前必须看到上游 Agent 的测试输出原文。
- 每个 Phase 结束出具 `reports/testing/phase-N-summary.md`，含总数/通过/失败/失败原因/未解决问题。

## 9. 验收标准

| 项 | 标准 |
|---|---|
| 契约完整性 | 每个端点有请求/响应 Schema、错误码、状态码 |
| 模型一致性 | PG 表、Neo4j 标签、Pydantic 模型三者字段可对齐 |
| 任务可执行 | 任一任务单独立交给一个新 Agent 能直接开工，不需追问 |
| 可追溯 | 任一关系可回溯到 Claim → Evidence → 原始来源 |

## 10. 明确不负责

- 具体采集器实现（Agent 1）
- Cypher 查询优化（Agent 2）
- 提示词工程与推理质量（Agent 3）
- 规则引擎实现（Agent 4）
- 前端组件（Agent 5）
- 容器编排细节（Agent 6）
