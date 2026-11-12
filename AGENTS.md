# AGENTS.md — FIG 多智能体协作章程

> **本文件地位**：项目内所有开发智能体（含主架构师）的最高协作约束。与 `docs/` 下规范文件冲突时，以本文件 + `docs/api-contracts.md` 为准。
> **版本**：v0.1 · 2026-11-12 · 状态：待评审

---

## 一、团队编制

| 编号 | 角色 | 代号 | 主责层 | 职责文件 |
|---|---|---|---|---|
| Agent 0 | 主架构师 / 项目经理 | `architect` | 架构、契约、审查、合并 | [agent-0-architect.md](docs/agents/agent-0-architect.md) |
| Agent 1 | 金融数据采集工程师 | `data-eng` | 采集、清洗、去重、入库 | [agent-1-data-engineer.md](docs/agents/agent-1-data-engineer.md) |
| Agent 2 | 知识图谱工程师 | `graph-eng` | Neo4j 模型、投影、遍历 | [agent-2-graph-engineer.md](docs/agents/agent-2-graph-engineer.md) |
| Agent 3 | AI 产业研究员 | `industry-ai` | 新闻理解、关系候选、传导 | [agent-3-industry-intelligence.md](docs/agents/agent-3-industry-intelligence.md) |
| Agent 4 | 质量控制与审计工程师 | `qa-audit` | 规则引擎、错误检测、测试 | [agent-4-qa-validation.md](docs/agents/agent-4-qa-validation.md) |
| Agent 5 | 前端开发工程师 | `frontend` | React 工作台、图谱可视化 | [agent-5-frontend.md](docs/agents/agent-5-frontend.md) |
| Agent 6 | 系统测试与运维工程师 | `devops` | Docker、部署、健康检查 | [agent-6-devops.md](docs/agents/agent-6-devops.md) |

职责总表与边界矩阵见 [docs/agent-responsibilities.md](docs/agent-responsibilities.md)。

---

## 二、当前环境的真实能力（实测结论，不许美化）

| 能力 | 实测结论 | 对协作方式的影响 |
|---|---|---|
| 并行子 Agent | **支持**。可同时派生多个独立上下文的子 Agent，结果回传主 Agent | 允许按「并行波次」派发只读调研 / 独立产出型任务 |
| 子 Agent 持久身份 | **不支持**。子 Agent 任务结束即销毁，无跨会话记忆 | 所有跨 Agent 信息必须落到文件（`docs/task-board.md`、`reports/`），不依赖 Agent 间对话 |
| Agent 间自由对话 | **不支持**。子 Agent 之间不能直接通信 | 一律走「主 Agent 中转 + 文件交接」，禁止假设对方记得上下文 |
| 文件系统 / 进程隔离 | **部分支持**。子 Agent 共享同一工作目录，无独立容器 | **同一文件同一时刻只允许一个 Agent 写入**，否则静默覆盖 |
| Git 分支 / Worktree 隔离 | **支持**。本地 git 可用，可开分支与 worktree | 每个 Agent 一个分支 `feat/<agent>-<task-id>`，由 architect 合并 |
| Docker 守护进程 | **当前不可用**（CLI 已装，daemon 未启动） | Agent 6 的部署类任务当前为 **blocked**，需人工启动 Docker Desktop |
| Python 运行时 | 3.13.14 可用；**建议锁定 3.12** | 3.13 部分 C 扩展轮子不全，见 ADR-0002 |

**结论 —— 本项目采用「串行守门 + 短任务并行」协作模式：**

```
主 Agent（唯一写入守门人）
  ├─ 冻结契约（docs/）
  ├─ 派发独立子任务 ──→ 子 Agent 在独立分支产出 → 回传「交付报告」
  ├─ 亲自核查代码与测试结果（不信口头完成）
  └─ 合并 → 更新 task-board / project-status
```

**明确不做的假装**：不存在「7 个常驻 Agent 在线协同」的运行时。本项目的「多 Agent」是**开发期分工 + 契约隔离**，不是运行时的多智能体自治系统。运行时只有一条确定性流水线（见 architecture.md）。

---

## 三、目录归属矩阵（谁能写）

`W` = 可写；`R` = 只读；`—` = 禁止触碰。主架构师对全仓库有 W，但同样受「接口先冻结」约束。

| 目录 / 文件 | 0 arch | 1 data | 2 graph | 3 ai | 4 qa | 5 fe | 6 ops |
|---|---|---|---|---|---|---|---|
| `docs/api-contracts.md` | **W** | R | R | R | R | R | R |
| `docs/database-schema.md` | **W** | R | R | R | R | — | R |
| `docs/graph-schema.md` | **W** | — | R | R | R | — | R |
| `docs/agent-*.md` / `AGENTS.md` | **W** | R | R | R | R | R | R |
| `docs/task-board.md` | **W** | R | R | R | R | R | R |
| `backend/app/collectors/` | R | **W** | — | — | R | — | — |
| `backend/app/services/ingest*` | R | **W** | — | R | R | — | — |
| `backend/app/graph/` | R | — | **W** | — | R | — | — |
| `backend/app/services/graph*` | R | — | **W** | — | R | — | — |
| `backend/app/agents/` | R | — | — | **W** | R | — | — |
| `integrations/llm/` | R | — | — | **W** | R | — | — |
| `backend/app/validation/` | R | — | — | R | **W** | — | — |
| `tests/fixtures/`、`tests/acceptance/` | R | R | R | R | **W** | — | R |
| `frontend/` | R | — | — | — | R | **W** | — |
| `deploy/`、`scripts/` | R | — | — | — | — | — | **W** |
| `database/migrations/` | **W（唯一）** | — | — | — | R | — | R |
| `database/neo4j/` | R | — | **W** | — | R | — | R |
| `backend/app/models/`、`schemas/` | **W** | R | R | R | R | R | — |
| `backend/app/api/` | **W** | — | R | — | R | R | — |
| `backend/app/core/`、`tasks/` | **W** | R | R | R | R | — | R |
| `backend/tests/` | R | **W** | **W** | **W** | R | — | R |
| `reports/<domain>/` | R | W | W | W | W | W | W |

**四条硬规则：**

1. `database/migrations/` **只有主架构师可写**。任何 Agent 需要改表 → 提交 `docs/adr/` 提案 + Migration 请求，由主架构师统一生成。
2. `backend/app/models/`、`schemas/` 是跨模块公共资产，只有主架构师可改；其他 Agent 通过 PR 提议字段。
3. 前端不得定义与 `api-contracts.md` 不一致的 TypeScript 类型；类型必须由 OpenAPI 生成或手写对齐并附生成脚本。
4. 需要同时改两个 Agent 的目录时，**拆成两个任务**，禁止一个任务跨权。

---

## 四、协作硬规则（不可协商）

1. **先读规范，再领任务。** 未读 `api-contracts.md` + 本文件的任务交付一律退回。
2. **先冻结接口，再并行开发。** 契约未冻结（状态非 `frozen`）的模块不得开工。
3. **一个核心文件同一时刻只有一个写入者。** 冲突由主架构师串行裁决。
4. **所有 DB 变更必须有 Migration。** 禁止手写 SQL 改线上表结构。
5. **所有功能必须附测试。** 无测试的交付视为未完成。
6. **接口变更必须先改文档再改代码**，且需 `changelog.md` 记录。
7. **AI 推测永不直接进入已验证关系。** 唯一入口是 Claim → 证据 → 状态迁移。
8. **禁止物理删除已验证关系。** 只能迁移到 `retracted` / `disputed` 状态。
9. **禁止多个 Agent 同时写正式图谱。** 写图只能经 `GraphProjector` 单一管道。
10. **禁止未经测试的大规模重构。** 重构须单独立项，附前后测试对比。

---

## 五、任务协议

### 5.1 任务单结构（`docs/task-board.md` 中每行对应一个 YAML 块）

```yaml
task_id: TASK-101
title: 新闻与公告采集器 MVP
agent: data-eng
phase: P1
objective: 拉取 3 个官方信源，标准化为 NewsEvent 并去重入库
inputs:
  - docs/api-contracts.md (v0.1, frozen)
  - docs/database-schema.md (news_raw / news_event 表)
outputs:
  - backend/app/collectors/*.py
  - backend/app/services/ingest_service.py
  - backend/tests/test_collectors.py
dependencies: [TASK-003, TASK-004]
files_scope:
  write: [backend/app/collectors/, backend/app/services/ingest_service.py, backend/tests/]
  read:  [backend/app/models/, backend/app/schemas/]
acceptance_criteria:
  - 同一新闻重复采集不产生第二条 news_event（去重键命中）
  - 每条记录保留 source_url / published_at / collected_at / raw_hash
  - 采集失败写入 dead_letter 表并含错误类型，不静默丢弃
test_requirements:
  - 单元测试覆盖去重、时间解析、失败重试
  - 用 tests/fixtures/news/*.json 离线运行，不依赖网络
status: pending
```

### 5.2 任务状态机

```
pending → assigned → in_progress → review → completed
                          ↓           ↓
                       blocked      failed → (重新派发)
```

- `blocked` 必须写清五要素：阻塞位置 / 错误信息 / 已尝试方案 / 需要谁协助 / 推荐解法。
- `completed` 只能由主架构师在**核查代码与测试输出后**置位。Agent 自报完成 = `review`。

### 5.3 状态语义（禁止混用）

| 状态 | 含义 |
|---|---|
| 未开始 | 无代码 |
| 已写代码 | 有文件，未运行 |
| 已运行 | 能启动，行为未验证 |
| 测试通过 | 自动化测试实际通过，附输出 |
| 已合并 | 进入 main 分支 |
| 已部署 | 在目标环境跑起来 |
| 已验证实际数据 | 用真实数据跑通并人工核对过 |

---

## 六、交付协议

每个 Agent 交付时必须提交 `reports/<domain>/TASK-xxx-delivery.md`，包含：

1. 完成内容（对应验收标准逐条勾选）
2. 修改文件列表 / 新增文件列表
3. 接口变化（无变化也要写「无」）
4. 运行方式（可复制粘贴的命令）
5. **测试结果原文**（不是「测试通过」四个字）
6. 已知问题
7. **未完成内容**（必须显式列出，不许省略）
8. 对其他模块的依赖与假设
9. 需要主架构师决策的事项

> 主架构师核查纪律：交付报告与实际代码不一致时，以代码为准，任务打回 `review`。

---

## 七、冲突与阻塞处理

```
发现问题
 → 定位所属层（数据源/格式/实体/关系模型/推理/DB/API/前端/协作/部署）
 → 交给对应 Agent
 → 在隔离分支验证
 → 测试通过后合并
 → 更新 docs/project-status.md
```

多个 Agent 无法解决时，必须输出：完整错误日志 + 最小复现案例 + 至少两种方案 + 成本/风险/维护难度对比，交主架构师裁决。**禁止在没有理解问题的情况下反复改代码。**

---

## 八、团队动态调整

允许主架构师：新建专业 Agent、合并重复职责、暂停闲置 Agent、转交任务、要求专项审查、安排两个 Agent 对同一方案独立评估。

**每次调整必须记录在 `docs/technical-decisions.md`，写明原因与影响。**

---

## 九、变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-12 | v0.1 | 初版：团队编制、环境实测、目录归属矩阵、任务与交付协议 |
