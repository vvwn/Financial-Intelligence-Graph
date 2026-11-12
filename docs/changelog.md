# 变更日志

格式参考 Keep a Changelog。版本号与项目阶段对应。

---

## [0.1.1] — 2026-11-12 · 基础设施落地（TASK-008）

### 新增

- **后端环境**：`backend/pyproject.toml` + `uv.lock` + `.python-version`，uv 管理，锁定 **Python 3.12.12**
- **后端骨架**（可运行，非占位）：
  - `core/config.py` 基于 pydantic-settings，从仓库根 `.env` 读取
  - `core/logging.py` JSON 单行日志
  - `core/db.py` async engine + session 依赖 + `ping()`
  - `core/neo4j.py` async driver + `ping()`
  - `core/errors.py` 与契约一致的 14 个错误码 + `AppError`
  - `core/ids.py` UUIDv7（时间有序，应用侧生成）
  - `schemas/enums.py` 契约枚举 + `PROJECTABLE_STATUSES` / `PROMOTABLE_CLAIM_TYPES` 常量
  - `schemas/envelope.py` 统一响应信封
  - `api/health.py` `/health` `/ready`；`main.py` request_id 中间件 + 三个异常处理器
- **数据库**：`deploy/docker-compose.yml`（PG 16-alpine + Neo4j 5.26-community，健康检查 + 具名卷）
- **迁移链路**：`backend/alembic.ini` + `database/migrations/{env.py,script.py.mako}`（async，DSN 运行时注入）
- **图 Schema（临时版）**：`database/neo4j/{constraints,indexes}.cypher` + `scripts/apply_neo4j_schema.py`
- **前端工程**：Vite 6 + React 18 + TS 5.7 + react-router 7 + cytoscape，`src/services/api.ts` 信封客户端，暗色终端底样式，7 个路由占位，vitest 用例
- **文档**：`docs/deployment.md`（5 步启动 + 已验证基线 + 排错表）

### 验证结果

- `pytest` 5 passed；`ruff check` 全通过
- `/ready` 返回 200，PG 与 Neo4j 双绿
- 容器重启后数据仍在
- `vite build` 成功；`tsc --noEmit` 零错误；`vitest` 2 passed

### 解除

- B-01 Docker daemon 未运行（已启动，29.4.0）
- B-06 Neo4j 镜像拉取慢（已到位）

### 注意

- Neo4j 约束/索引是**临时版**，`docs/graph-schema.md` 冻结（TASK-004）后可能调整
- 版本实测与早期文档估计不同：FastAPI 0.162.5、SQLAlchemy 2.1.8、Alembic 1.20.1、neo4j driver 5.28.8

---

## [0.1.0] — 2026-11-12 · Phase 0 启动

### 新增

- 项目骨架：`backend/ frontend/ database/ integrations/ tests/ deploy/ reports/ docs/`
- `README.md`：项目定位、三条红线、文档导航
- `AGENTS.md` v0.1：团队编制、**环境能力实测结论**、目录归属矩阵、10 条协作硬规则、任务协议、交付协议
- `docs/agents/`：7 份 Agent 职责文件（Agent 0–6），含允许/禁止修改目录、输入输出、API、依赖、测试、验收
- `docs/agent-responsibilities.md`：职责总表、6 个交接点、禁止越权清单、分阶段启用计划
- `docs/architecture.md` v0.1：总体架构图、新闻端到端数据流、事件传导边界、部署拓扑、模块依赖方向、技术风险表
- `docs/api-contracts.md` v0.1：统一响应信封、14 个错误码、封闭枚举集合、关系状态机 + 合法迁移表、约 40 个端点、幂等与重试、契约变更流程
- `docs/database-schema.md` v0.1：18 张表 DDL、7 条不变量、索引性能预算
- `docs/graph-schema.md` v0.1：16 类节点标签、16 种关系类型、约束与索引、投影规则、字段映射表
- `docs/task-dependencies.md` v0.1：任务依赖图（30 任务、无环）、10 个并行波次、关键路径、阻塞清单
- `docs/task-board.md`：10 个任务的完整 YAML 任务单
- `docs/project-status.md`：阶段进度、环境实测、风险 R-01~R-10、技术债 D-01~D-05
- `docs/agent-status.md`：角色状态与派发记录
- `docs/technical-decisions.md`：ADR-0001~0006、5 个待决问题
- `docs/testing-strategy.md` v0.1：12 类测试归属、6 个固定数据集、25 例错误注入清单、性能基线
- `docs/development-roadmap.md` v0.1：P0–P5 里程碑与验收标准

### 决策

- ADR-0001 PostgreSQL 为唯一事实源，Neo4j 为派生投影
- ADR-0002 Python 锁定 3.12
- ADR-0003 Claim / Evidence / VerifiedRelationship 三层分离
- ADR-0004 LLM 只能经 `LLMClient` 协议访问
- ADR-0005 初期用 APScheduler，不引 Prefect
- ADR-0006 模块化单体，不做微服务

### 已知阻塞

- B-01 Docker daemon 未运行 → TASK-601 / TASK-602 blocked

### 说明

本版本**无业务代码**。Phase 0 评审通过前不写业务代码，这是设计约束，不是进度问题。

---

## 版本号规则

| 版本 | 含义 |
|---|---|
| 0.x.0 | Phase 0 期间迭代 |
| 1.0.0 | Phase 1 验收通过（图谱底座可用） |
| 2.0.0 | Phase 2 验收通过（自动扩展可用） |
| 3.0.0 | Phase 3 验收通过（质量闭环） |
| 4.0.0 | Phase 4 验收通过（Web 可用） |
| 5.0.0 | Phase 5 验收通过（投资研究可用） |
