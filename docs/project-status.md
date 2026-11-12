# 项目状态

> 最后更新：2026-11-12 22:40 · 维护者：`architect`
> **状态语义严格区分**：未开始 / 已写代码 / 已运行 / 测试通过 / 已合并 / 已部署 / 已验证实际数据。
> 禁止把「写了代码」说成「做完了」。

---

## 一、当前阶段

**Phase 0 — 架构设计与可行性验证**（进行中，约 60%）

| 交付物 | 状态 | 备注 |
|---|---|---|
| architecture.md | ✅ 已写 | 含架构图、数据流、部署拓扑、ADR-0001~0005 |
| agent-responsibilities.md + 7 份职责文件 | ✅ 已写 | 含目录归属矩阵 |
| api-contracts.md | 🟡 draft | 端点/信封/错误码/枚举/状态机已定义，待冻结 |
| database-schema.md | 🟡 draft | 核心表 DDL 已写，5 个待评审项未决 |
| graph-schema.md | 🟡 draft | 标签/关系/投影规则已写，5 个待评审项未决 |
| task-dependencies.md | ✅ 已写 | 依赖图无环，10 个并行波次 |
| testing-strategy.md | 🟡 draft | 12 类测试已归类，固定数据集规格待定 |
| development-roadmap.md | ✅ 已写 | P0–P5 里程碑 |
| 架构评审报告 | ⚪ 未开始 | TASK-007，Phase 0 门禁 |
| 代码 | ⚪ 未开始 | **Phase 0 评审通过前不写业务代码** |

---

## 二、环境事实（2026-11-12 22:55 复测）

| 组件 | 状态 | 说明 |
|---|---|---|
| Python（项目环境） | ✅ **3.12.12** | `backend/.venv`，由 uv 创建，`.python-version` 锁定 |
| uv | ✅ 0.12.15 | 包管理，`uv sync` 可复现 |
| Python（宿主默认） | 3.13.14 / 3.14 | 项目不使用，仅宿主 PATH 默认值 |
| Node / npm | ✅ 22.22.2 / 10.9.7 | — |
| Docker CLI | ✅ 29.4.0 | — |
| Docker Compose | ✅ v5.1.1 | — |
| **Docker daemon** | ✅ **运行中**（29.4.0） | B-01 已解除 |
| PostgreSQL | ✅ **16-alpine，healthy** | 容器 `fig-postgres`，:5432，数据卷 `fig_fig_pgdata` |
| Neo4j | ✅ **5.26-community，healthy** | 容器 `fig-neo4j`，:7474 / :7687，已应用 4 约束 + 9 索引 |
| Git | ✅ 2.55.0 | 远端 `github.com/vvwn/Financial-Intelligence-Graph` |

**实际安装的关键版本**（与文档早期估计不同，以此为准）：

| 包 | 版本 |
|---|---|
| fastapi | 0.162.5 |
| pydantic | 2.14.3 |
| sqlalchemy | 2.1.8 |
| alembic | 1.20.1 |
| asyncpg | 0.32.0 |
| neo4j (driver) | 5.28.8 |
| apscheduler | 3.11.3 |
| httpx | 0.28.1 |
| uvicorn | 0.54.0 |

---

## 三、已完成

| 项 | 证据 |
|---|---|
| **后端 Python 环境** | `backend/.venv`（3.12.12），`uv sync` 装 42 个包，全部可 import |
| **后端骨架可运行** | `app/main.py` + `core/{config,logging,db,neo4j,errors,ids}.py` + `api/health.py`；`pytest tests/` **5 passed** |
| **PostgreSQL 容器** | `fig-postgres` healthy；`db.ping()` 返回 True |
| **Neo4j 容器 + 图 Schema** | `fig-neo4j` healthy；`scripts/apply_neo4j_schema.py` 应用 13 条语句 → 4 约束 / 15 索引 |
| **端到端就绪** | `curl /ready` → 200，`postgres.ok=true, neo4j.ok=true` |
| **数据持久化** | 写入临时表 → `compose restart` → 数据仍在（rows=1, note 保留）→ 已清理 |
| **前端工程** | Vite 6 构建通过（185 KB JS / 61 KB gzip）；`vitest` 2 passed；`tsc --noEmit` 零错误 |
| **Alembic 迁移链路** | `alembic current` 连库成功（尚无 revision，待 TASK-111） |
| **Docker Compose** | `deploy/docker-compose.yml`，PG + Neo4j 双服务 + 健康检查 + 具名卷 |
| **本地环境文档** | `docs/deployment.md`（5 步启动 + 6 类常见问题） |
| 项目目录骨架 | `backend/ frontend/ database/ integrations/ tests/ deploy/ reports/ docs/` 已建 |
| 协作章程 | `AGENTS.md` v0.1 |
| 7 个 Agent 职责文件 | `docs/agents/agent-0..6` |
| 架构设计 | `docs/architecture.md` v0.1（含 4 张 mermaid 图） |
| 接口规范 | `docs/api-contracts.md` v0.1 |
| 任务依赖图 | `docs/task-dependencies.md` v0.1（30 个任务、10 波次） |
| Git 仓库初始化 | 首次提交已推送 |

**注意：以上全部是文档，零业务代码。** 这是 Phase 0 的应有状态，不是进度落后。

---

## 四、正在进行

| 任务 | 负责人 | 当前动作 |
|---|---|---|
| TASK-003 PG Schema 冻结 | architect | 5 个待评审项待决策（见 database-schema.md 第五节） |

---

## 五、阻塞

| # | 阻塞 | 影响 | 解除条件 |
|---|---|---|---|
| B-01 | ~~Docker daemon 未运行~~ | ~~TASK-601/602~~ | ✅ **已解除**（daemon 29.4.0 运行中） |
| B-04 | 实体消歧标准未定 | TASK-101/302/401 | architect + qa-audit 会签规则 |
| B-06 | ~~Neo4j 镜像拉取慢~~ | ~~图库验证~~ | ✅ 已解除（镜像到位，容器 healthy） |

---

## 六、风险清单

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R-01 | ~~Docker daemon 不可用~~ | — | — | ✅ 已消除 |
| R-02 | Python 3.13 依赖轮子不全 | 中 | 中 | 锁 3.12，容器内验证 |
| R-03 | 实体消歧不准 → 关系挂错公司 | 高 | **严重** | 别名表 + 股票代码强约束 + qa-audit DUP 规则 + 人工复核队列 |
| R-04 | LLM 把推断写成事实 | 高 | **严重** | claim_type 硬约束 + state_guard + 反幻觉测试 |
| R-05 | 投影器与 PG 不一致 | 中 | 高 | 幂等测试 + 每周一致性校验 + 全量重建能力 |
| R-06 | Neo4j Community 内存限制，大图遍历超时 | 中 | 中 | 限深限点 + 首屏聚合 |
| R-07 | 数据源许可/频控不清，采集违规 | 中 | 中 | 只接官方/许可源，频控配置化 |
| R-08 | 证据质量判定阈值拍脑袋 | 高 | 中 | 用 TASK-101 种子数据校准，不预设数字 |
| R-09 | 任务粒度过大，Agent 交付不可验收 | 中 | 中 | 每任务必须有可执行验收命令 |
| R-10 | 多 Agent 同时改同一文件 | 中 | 中 | 目录归属矩阵 + 串行守门 |

---

## 七、技术债务（已知，先记账不还）

| # | 债务 | 何时还 |
|---|---|---|
| D-01 | 无鉴权（P0–P3 单用户） | P4 引入 Bearer token |
| D-02 | 无 CI（本地手动跑测试） | P2 前补 GitHub Actions |
| D-03 | 图谱时态查询 `as_of` 未实现 | P4 或按需 |
| D-04 | 质量指标用实时聚合而非物化视图 | 数据量 > 10 万关系时改 |
| D-05 | 无分布式锁，APScheduler 单进程假设 | 多实例部署前必须解决 |

---

## 八、下一步（按顺序）

1. ✅ 基础设施：Python 3.12 venv + 依赖、后端骨架、PG + Neo4j 容器、图约束/索引、Alembic 链路、前端工程
2. 决策 TASK-003 的 5 个待评审项 → Schema 冻结
3. TASK-004 图 Schema 冻结（会签 graph-eng）—— 当前约束/索引是**临时版**，冻结后可能调整
4. TASK-005 API 契约冻结 + OpenAPI 骨架
5. TASK-006 测试策略冻结
6. TASK-007 出架构评审报告 → **等用户评审通过**
7. 评审通过后才进入 Phase 1
