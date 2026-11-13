# 变更日志

格式参考 Keep a Changelog。版本号与项目阶段对应。

---

## [0.3.0] — 2026-11-13 · 执行架构评审裁决

### 裁决执行

- **DISPUTED 第 7 态批准**：语义限定为「已验证关系受到新证据挑战」；`pending_review → disputed` 改为**非法**；`relationship_evidence` 增加 `relation` 并进主键（双方证据并存）；`relationship_history` 增加 `trigger`，进入 disputed 必须有反向证据（DB CHECK）。
- **locale=C 保留**：新增 `entity.name_sort_key` + `name_sort_key_version` + `entity_sort_key_history`；`core/sortkey.py` 拼音排序键（多音字按词组上下文）；`scripts/backfill_sort_keys.py` 默认 dry-run。
- **阈值语义修正**：阈值只决定 `candidate → pending_review`；`pending_review → verified` 额外要求 `approved_by`，自动化 actor（`system:`/`auto:`/`pipeline:`）一律拒绝；阈值版本与变更记入 `app_setting_history`。
- **独立性修正**：`evidence.origin_key` 标识原始报道；阈值按 `COUNT(DISTINCT origin_key)` 计数，不同 `content_hash` 不再视为独立来源；`syndicated_from_id` 继承来源，`v_evidence_origin` 聚合视图。
- **I-5 落地**：`trg_evidence_immutable` 禁改正文列与 DELETE、仅允许改 `verification_status`；`trg_evidence_linkage` 校验 `supersedes_id` 同源且不倒序。

### 新增

- 迁移 `c7d1e4a92f10`（7 列 / 2 表 / 2 触发器 / 1 视图 / predicate CHECK）
- `app/graph/projector.py`：单关系投影 + 删边原语（幂等，`MERGE`）
- `app/core/sortkey.py`、`app/services/settings_service.py`
- 测试：`test_sortkey.py`(12)、`test_evidence_immutability.py`(9)、`test_projector.py`(8)、生命周期测试重写(14)
- `scripts/{backup,restore,verify_backup}.sh`、`scripts/backfill_sort_keys.py`
- `.github/workflows/ci.yml`
- `database/seeds/sources.yaml`、`tests/fixtures/` 六个目录 + 格式规格
- `predicate` CHECK（取值 = 关系类型枚举）
- Docker secrets 支持（`POSTGRES_PASSWORD_FILE` / `NEO4J_PASSWORD_FILE`）

### 破坏性变更（契约 v1.0 → v1.1）

- `pending_review → disputed` 不再合法
- `verify` 必须携带 `approved_by`
- 证据必须携带 `origin_key`（NOT NULL）
- `relationship_evidence` 主键改为三元组

### 验证状态（诚实标注）

| 项 | 结果 |
|---|---|
| 单元测试（无 DB） | ✅ 62 passed |
| ruff | ✅ All checks passed |
| 全量 pytest | ⚠️ 66 passed / **34 errors**（DB 未启动） |
| `alembic upgrade head` | ❌ **未执行**（Docker 不可用） |
| 备份恢复演练 | ❌ **未执行** |
| CI | ❌ **未在 GitHub 运行** |

### 阻塞

- B-09：Docker 守护进程不可用，`wsl.exe` 被本机安全策略拦截，无法启动 Docker Desktop。

---

## [0.2.0] — 2026-11-13 · 契约冻结与缺陷修复

### 架构决策（评审方 2026-11-13 下达）

- **决策 1**：`POTENTIAL_*` 不进正式图谱，采用「候选层 + 正式图谱」双层结构 → ADR-0007
- **决策 2**：PostgreSQL 为状态机唯一真源，Neo4j 为投影 → ADR-0008
- **偏差**：新增第 7 态 `DISPUTED`（决策清单外，理由见评审报告第二节，**待裁决**）

### 破坏性变更（契约 v0.1 → v1.0）

- 状态重命名：`pending_verification → pending_review`、`refuted → rejected`、`retracted → revoked`
- `EntityType` 移除 `customer` / `supplier` / `competitor`（它们是关系角色，不是实体种类）
- 图谱节点移除 `:Stock` 标签（股票是 `:ListedCompany` 的属性）
- `as_of` 参数从 v1 移除（P4 再评估）
- `derived_from_claim_ids uuid[]` → `claim_relationship` 关联表

### 新增

- 枚举：`NewsEventType`（16 值）、`ImpactPathStatus`；常量 `CANDIDATE_LAYER_RELATIONSHIP_TYPES`、`ACTIVE_TRIPLE_STATUSES`、`CONFIDENCE_CAPS`
- 数据模型：25 张表（新增 `source`、`collect_run_source`、`entity_mention`、`claim_relationship`、`idempotency_key`）
- 首个 Alembic 迁移 `bdaf9a0511cb`：含 `pg_trgm` 扩展、`v_evidence_distinct` 视图、`relationship_history` 只追加触发器、`app_setting` 7 项种子
- `validation/state_guard.py`：7 态迁移矩阵、证据达标判定、层级隔离、置信度上限
- `services/relationship_service.py`：状态迁移 + 强制 Claim 来源 + 历史追加
- `deploy/backend.Dockerfile` + compose `full` profile（已实测容器内 `/ready` 全绿）
- `core/context.py`：`request_id` ContextVar；日志每行带 `request_id`
- `StarletteHTTPException` 处理器：404/405 也返回统一信封

### 修复（36 条缺陷，31 已修 / 5 部分）

- `news_raw` 唯一键改 `(source_id, url)`，`raw_hash` 降为普通索引（转载可入库）
- `entity` 股票代码唯一键改 `(entity_type, stock_code)`
- `relationship` 唯一索引改为「仅活跃三态」，`confidence` 补 CHECK
- Neo4j `stock_code` 约束从 `:ListedCompany` 移到 `:Entity`，旧约束已 DROP
- 投影等价性断言显式排除 `projected_at` / `projection_run_id`
- 图谱字段映射重写：算不出的属性一律不进图
- `/ready` 增加 Alembic 版本比对 + 并发探测 + 5s TTL 缓存
- 测试根修正：`testpaths = ["backend/tests", "tests"]`（根 `tests/` 此前永不执行）
- 端口绑定改 `127.0.0.1`；生产环境弱密码启动即拒

### 验证结果

```
pytest backend/tests        → 51 passed
alembic upgrade head        → 成功（25 表 + 1 视图 + 1 触发器）
alembic check               → No new upgrade operations detected
ruff check                  → All checks passed
docker build                → fig-api:0.1.0 成功
curl /ready（容器内）        → postgres/neo4j/migration 三检 ok
```

### 新增文档

- `reports/development/phase0-architecture-review.md`（评审报告，36 条缺陷清单）
- `docs/deployment.md` 更新（容器化、已验证基线）
- `docs/technical-decisions.md` 新增 ADR-0007 / 0008 / 0009

### 已知未完成

- I-5（证据不可变）无列级触发器，仅代码约定
- `predicate` 无 DB CHECK
- `seeds/sources.yaml`、六个 fixture 目录仍空
- 备份恢复脚本、CI 未做
- 性能基线未测

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
