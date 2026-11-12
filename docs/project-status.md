# 项目状态

> 最后更新：2026-11-13 00:50 · 维护者：`architect`
> **状态语义严格区分**：未开始 / 已写代码 / 已运行 / 测试通过 / 已合并 / 已部署 / 已验证实际数据。

---

## 一、当前阶段

**Phase 0 — 架构设计与可行性验证**（契约已冻结，**等待独立评审**）

| 交付物 | 状态 | 证据 |
|---|---|---|
| `architecture.md` | ✅ v1.0 | 架构图、数据流、部署拓扑、ADR-0001~0009 |
| `agent-responsibilities.md` + 7 份职责文件 | ✅ v0.1 | 含目录归属矩阵 |
| `api-contracts.md` | ✅ **frozen v1.0** | 双层结构、7 态状态机、40+ 端点 |
| `database-schema.md` | ✅ **frozen v1.0** | 25 表、10 条不变量落点 |
| `graph-schema.md` | ✅ **frozen v1.0** | 15 标签、15 关系、投影准入三重过滤 |
| `testing-strategy.md` | ✅ **frozen v1.0** | 25 例判据全部定义 |
| `task-dependencies.md` | ✅ v0.1 | 30 任务、10 波次、无环 |
| `development-roadmap.md` | ✅ v0.1 | P0–P5 |
| **`reports/development/phase0-architecture-review.md`** | ✅ **已提交，待评审** | 36 条缺陷修复清单 + 测试原文 |
| 代码 | ✅ 骨架 + 迁移 + 状态守卫 | 51 tests passed |

**Phase 0 未完成的部分**：评审方签字。在此之前状态保持 `awaiting_review`，不置 `completed`。

---

## 二、环境事实（2026-11-13 00:40 复测）

| 组件 | 状态 | 说明 |
|---|---|---|
| Python（项目） | ✅ **3.12.12** | `backend/.venv`，uv 管理，`.python-version` 锁定 |
| uv | ✅ 0.12.15 | `uv sync` 可复现（`uv.lock` 已提交） |
| Node / npm | ✅ 22.22.2 / 10.9.7 | — |
| Docker daemon | ✅ 29.4.0 | 运行中 |
| PostgreSQL | ✅ **16-alpine healthy** | `fig-postgres`，25 表已迁移 |
| Neo4j | ✅ **5.26-community healthy** | `fig-neo4j`，4 约束 / 15 索引 |
| **api 容器** | ✅ **fig-api:0.1.0 运行中** | 容器内 `/ready` 三检全绿 |
| Git | ✅ 2.55.0 | `github.com/vvwn/Financial-Intelligence-Graph` |

**实际版本**：fastapi 0.162.5 / pydantic 2.14.3 / sqlalchemy 2.1.8 / alembic 1.20.1 / asyncpg 0.32.0 / neo4j 5.28.8 / uvicorn 0.54.0。

---

## 三、已完成

| 项 | 证据 |
|---|---|
| 契约层冻结 | 三份文档 `status: frozen` v1.0 + 一项测试策略 |
| 数据模型 | 25 表 + `v_evidence_distinct` 视图 + `trg_relationship_history_immutable` 触发器 |
| 迁移链路 | `alembic upgrade head` 成功；`alembic check` 无差异 |
| 状态机与提升规则 | `validation/state_guard.py`（7 态矩阵 + 证据达标 + 层级隔离） |
| 关系生命周期服务 | `services/relationship_service.py`（强制 Claim 来源 + 历史追加） |
| 后端测试 | **51 passed**（21 单元 + 18 DB 集成 + 7 API + 5 其他） |
| 静态检查 | ruff 全通过 |
| 容器化 | `deploy/backend.Dockerfile` 构建成功，容器内 `/ready` 全绿 |
| 404 信封修复 | 新增 `StarletteHTTPException` 处理器，测试断言 `error.code` |
| 日志可追溯 | `ContextVar` + `RequestIdFilter`，每行日志带 `request_id` |
| `/ready` 加固 | 并发探测 + 5s TTL 缓存 + 迁移版本比对 |
| Neo4j 约束修正 | `stock_code` 约束移到 `:Entity`，旧约束已 DROP |

---

## 四、正在进行

| 任务 | 负责人 | 当前动作 |
|---|---|---|
| Phase 0 独立评审 | **评审方** | 待阅读评审报告并给出 APPROVED / WITH CONDITIONS / REJECTED |

---

## 五、阻塞

| # | 阻塞 | 影响 | 解除条件 |
|---|---|---|---|
| B-04 | 实体消歧标准未定（Q-01） | TASK-101/302/401 | architect + qa-audit 会签规则 |
| B-07 | `DISPUTED` 第 7 态未获批（Q-06） | 全部状态逻辑 | 评审方裁决 |
| B-08 | 证据阈值未校准（Q-08） | TASK-411/412 | 需 TASK-101 真实数据 |

---

## 六、风险清单

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R-03 | 实体消歧不准 → 关系挂错公司 | 高 | 严重 | 代码强约束 + 别名表 + DUP 规则 + 人工复核 |
| R-04 | LLM 把推断写成事实 | 中（已降） | 严重 | 三层分离 + 状态守卫 + DB CHECK + 6 个反幻觉测试 |
| R-05 | 投影器与 PG 不一致 | 中 | 高 | 幂等/重建测试 + 每周一致性校验 |
| R-11 | 投影器成为单点故障 | 中 | 高 | 增量 + 全量重建能力 |
| R-12 | 中文排序/匹配不合预期 | 高 | 中 | `normalized_name` + 显式 `COLLATE` |
| R-13 | 证据阈值拍脑袋 | 高 | 中 | 参数在 `app_setting`，待真实数据校准 |
| R-14 | `DISPUTED` 未获批 | 中 | 中 | 已列待裁决 |

---

## 七、技术债务

| # | 债务 | 何时还 |
|---|---|---|
| D-01 | 无鉴权（P1–P3 单用户） | P4 引入 Bearer |
| D-02 | 无 CI（本地手动跑测试） | P2 前补 GitHub Actions |
| D-03 | 图谱时态查询 `as_of` 未实现 | P4 评估 |
| D-04 | 质量指标实时聚合，未物化 | >10 万关系时改 |
| D-05 | APScheduler 单进程假设，无分布式锁 | 多实例部署前必须解决 |
| D-06 | 证据「不可变」只有约定，无列级触发器（I-5） | 待设计「禁改正文/允许改状态」 |
| D-07 | `predicate` 无 DB CHECK（事件型谓词未穷举） | TASK-003 收尾 |

---

## 八、下一步

1. **评审方**阅读 `reports/development/phase0-architecture-review.md`，就三个待裁决项给出结论
2. 按评审意见修订（若 REJECTED / WITH CONDITIONS）
3. 评审通过后：Phase 0 置 `completed`，进入 Phase 1（TASK-201 图约束会签 → TASK-202 投影器）
4. 未获批准前**不启动 Phase 1 业务开发**
