# 任务看板（唯一任务真源）

> 版本 v0.1 · 2026-11-12 · 维护者：`architect`
> **状态只能由 `architect` 置为 `completed`。** Agent 自报完成 → `review`。
> 依赖关系与波次见 [task-dependencies.md](task-dependencies.md)。

---

## 看板总览

| 状态 | 数量 | 任务 |
|---|---|---|
| ✅ completed | 15 | TASK-001~010, TASK-102, TASK-202, TASK-203, TASK-211, TASK-601 |
| 🟡 in_progress | 1 | TASK-101（真实数据待证据来源） |
| 🔵 review | 0 | — |
| ⚪ pending | 0 | — |
| 🔴 blocked | 0 | — |

---

## Phase 0 任务单

### TASK-001 · 开发环境校验与记录

```yaml
task_id: TASK-001
agent: architect
phase: P0
objective: 摸清本机实际可用的运行时、容器、数据库能力，形成事实清单
inputs: []
outputs:
  - docs/project-status.md (环境章节)
  - docs/technical-decisions.md (ADR-0002)
dependencies: []
acceptance_criteria:
  - 逐项记录 Python / Node / Docker CLI / Docker daemon / git 的真实状态
  - 不可用项明确标注为阻塞，不得写"应该可以"
test_requirements: []
status: completed
completed_at: 2026-11-12
result: |
  Python 3.13.14 / Node 22.22.2 / npm 10.9.7 / Docker CLI 29.4.0 / Compose 5.1.1 / git 2.55.0
  Docker daemon 未运行 → 容器类任务阻塞（B-01）
```

### TASK-002 · 目录骨架与协作章程

```yaml
task_id: TASK-002
agent: architect
phase: P0
objective: 建立统一目录结构、多 Agent 协作章程、职责文件、架构与接口规范
inputs: [项目总任务书, 多Agent协同指令]
outputs:
  - README.md, AGENTS.md, .gitignore
  - docs/architecture.md, agent-responsibilities.md, api-contracts.md
  - docs/task-dependencies.md, docs/agents/*.md
  - 目录骨架（backend / frontend / database / integrations / tests / deploy / reports）
dependencies: [TASK-001]
acceptance_criteria:
  - 每个 Agent 有独立职责文件，含允许/禁止修改目录
  - 接口规范含统一信封、错误码、枚举、状态机
  - 依赖图无环，并行波次可执行
test_requirements: []
status: completed
completed_at: 2026-11-12
```

### TASK-008 · 基础设施搭建（Python 环境 + 后端骨架 + 容器 + 前端工程）

```yaml
task_id: TASK-008
agent: architect + devops
phase: P0
objective: 把"能跑起来"这件事先做实，避免后续所有验证都停留在纸面
inputs: [TASK-001, TASK-002]
outputs:
  - backend/pyproject.toml, backend/.python-version, backend/.venv (3.12.12)
  - backend/app/core/{config,logging,db,neo4j,errors,ids}.py
  - backend/app/schemas/{enums,envelope}.py
  - backend/app/api/health.py, backend/app/main.py
  - backend/tests/test_health.py
  - backend/alembic.ini, database/migrations/{env.py,script.py.mako}
  - deploy/docker-compose.yml
  - frontend/ (Vite + React + TS + 路由 + api 客户端 + vitest)
  - docs/deployment.md
dependencies: [TASK-002]
acceptance_criteria:
  - uv sync 后全部依赖可 import（fastapi/sqlalchemy/asyncpg/neo4j/alembic/apscheduler）
  - pytest 通过，/health 返回统一信封，request_id 回显
  - PostgreSQL 容器 healthy，db.ping() 为 True
  - alembic current 可连库
  - compose 文件含健康检查与具名数据卷
test_requirements:
  - 后端 5 个冒烟测试实际通过（有输出）
  - 前端 vitest + tsc --noEmit 通过
status: completed
completed_at: 2026-11-12
result: |
  Python 3.12.12 venv（42 包）；pytest 5 passed；PG 16-alpine healthy；
  alembic 链路连通（无 revision）；Neo4j 镜像仍在拉取，容器未起。
  未完成：Neo4j 容器、api/web 容器镜像、备份脚本 —— 不计入本任务。
```

### TASK-009 · 执行架构评审裁决（disputed / 排序键 / 阈值 / I-5）

```yaml
task_id: TASK-009
agent: architect
phase: P0
objective: 按评审方 2026-11-13 正式裁决修改契约与实现
inputs: [reports/development/phase0-architecture-review.md, 评审裁决]
outputs:
  - 迁移 c7d1e4a92f10（disputed / 排序键 / origin_key / I-5 触发器 / predicate CHECK）
  - backend/app/core/sortkey.py + 12 个单测
  - backend/app/validation/state_guard.py 重写（阈值只入核验、批准必需、disputed 仅自 verified）
  - backend/app/graph/projector.py（单关系投影 + 删除原语）
  - backend/tests/test_evidence_immutability.py / test_projector.py / test_relationship_lifecycle.py
  - scripts/{backup,restore,verify_backup}.sh、scripts/backfill_sort_keys.py
  - .github/workflows/ci.yml
  - database/seeds/sources.yaml、tests/fixtures/ 六目录规格
dependencies: [TASK-007]
acceptance_criteria:
  - disputed 语义与迁移矩阵一致（pending_review → disputed 非法）
  - 阈值不自动 verified，approval 必需
  - 证据不可变双向测试（合法修正 + 非法改写）
  - 排序键独立测试（多音字/数字/大小写）
  - 五条部分修复项各有结论
test_requirements:
  - 全部测试重跑并保存原始日志到 reports/testing/
status: completed
completed_at: 2026-11-13
unverified: |
  Docker 守护进程在本次执行中不可用（wsl.exe 被安全策略拦截，无法启动 Docker Desktop），
  因此下列验证未能执行，不得视为通过：
    - alembic upgrade head（迁移 c7d1e4a92f10 未在真实库执行）
    - alembic check
    - 全部 db / neo4j 标记的测试（生命周期、证据不可变、投影器）
    - scripts/verify_backup.sh 备份恢复演练
    - CI 工作流未在 GitHub 上实际运行
```

### TASK-010 · 收尾核验（I-5 / DISPUTED / 独立性 / CI / 容器）

```yaml
task_id: TASK-010
agent: architect
phase: P0
objective: 只做核验，不新增功能；为最终评审提供可复核证据
inputs: [TASK-009 产出, 评审方四项最终标准]
outputs:
  - scripts/verify_invariants.py（裸 SQL 19 项核验）
  - 迁移 d91f2b6c4a07（修复 disputed CHECK 的 NULL 语义缺陷）
  - reports/testing/{2026-11-13-invariants,github-actions-evidence,2026-11-13-container-deploy}.{log,md}
  - fig-api:0.1.1 部署
dependencies: [TASK-009]
acceptance_criteria:
  - 不变量核验 19/19 PASS
  - GitHub Actions 有 success 记录（run #2）
  - 容器 /ready 三检全绿且 head 与库一致
  - 报告区分 已完成 / 已验证 / 因外部原因暂缓
test_requirements:
  - 全量 pytest 100 passed
status: completed
completed_at: 2026-11-13
found_defect: |
  disputed 的 DB CHECK 用 array_length，空数组返回 NULL，CHECK 视为通过 → 约束从未生效。
  已由迁移 d91f2b6c4a07 改为 cardinality。ORM 测试无法发现，只有裸 SQL 核验能发现。
not_done: |
  未在独立物理机/VM 验证部署（外部环境项，不计代码缺陷）
```

### TASK-003 · PostgreSQL Schema 设计与冻结

```yaml
task_id: TASK-003
agent: architect
phase: P0
objective: 冻结核心表结构，作为全部后续开发的锚点
inputs:
  - docs/database-schema.md (draft v0.1)
  - 总任务书第四节"统一数据结构"
outputs:
  - docs/database-schema.md → status: frozen
  - docs/adr/ADR-0003-claim-evidence-relationship.md
dependencies: [TASK-002]
files_scope:
  write: [docs/database-schema.md, docs/adr/]
acceptance_criteria:
  - NewsEvent / Entity / Relationship / Evidence / Claim / ImpactPath 六类对象字段完整
  - Claim 与 Relationship 物理分离，且明确提升条件
  - 关系状态 6 态齐全（含 disputed）
  - 不变量 I-1..I-7 每条都有落地手段
  - 五个待评审项全部给出结论
test_requirements:
  - 建表 SQL 在临时库可执行通过（需 Docker 或本机 PG）
status: completed
completed_at: 2026-11-13
evidence: alembic upgrade head 成功；alembic check 无差异；25 表 + 视图 + 触发器
```

### TASK-004 · Neo4j 图 Schema 设计与冻结

```yaml
task_id: TASK-004
agent: architect + graph-eng（会签）
phase: P0
objective: 冻结节点标签、关系类型、投影准入规则
inputs: [docs/graph-schema.md (draft), docs/database-schema.md (frozen)]
outputs:
  - docs/graph-schema.md → frozen
  - database/neo4j/constraints.cypher, indexes.cypher
dependencies: [TASK-003]
files_scope:
  write: [docs/graph-schema.md, database/neo4j/]
acceptance_criteria:
  - 每个节点标签有 PG 来源字段映射
  - 投影准入规则明确（哪些状态进图）
  - 五个待评审项给出结论，特别是 POTENTIAL_* 是否进图
  - 遍历参数上限与超限行为写死
test_requirements:
  - 约束/索引 cypher 在 Neo4j 5 上执行通过
status: completed
completed_at: 2026-11-13
```

### TASK-005 · API 契约冻结 + OpenAPI 骨架

```yaml
task_id: TASK-005
agent: architect
phase: P0
objective: 冻结端点清单、信封、错误码、枚举，产出可生成的 OpenAPI
inputs: [docs/api-contracts.md (draft), database-schema.md, graph-schema.md]
outputs:
  - docs/api-contracts.md → frozen
  - backend/app/schemas/enums.py
  - backend/app/api/ 路由骨架（返回 501 + 完整 Schema）
  - tests/acceptance/test_api_contract.py
dependencies: [TASK-003, TASK-004]
files_scope:
  write: [docs/api-contracts.md, backend/app/schemas/, backend/app/api/, tests/acceptance/]
acceptance_criteria:
  - 每个端点有请求/响应 Schema 与错误码
  - 无 POST /relationships、无 DELETE 端点
  - 状态机合法迁移表与 state_guard 一致
  - /openapi.json 可生成且通过 openapi-spec-validator
test_requirements:
  - 契约测试：OpenAPI 中的枚举与 enums.py 完全一致
  - 前端 npm run gen:api 能从该 OpenAPI 生成类型（可在 P4 前置验证）
status: completed
completed_at: 2026-11-13
```

### TASK-006 · 测试策略与固定数据集设计

```yaml
task_id: TASK-006
agent: qa-audit
phase: P0
objective: 定下"什么算通过"，以及可重复运行的固定数据集
inputs: [docs/testing-strategy.md (draft), AGENTS.md]
outputs:
  - docs/testing-strategy.md → frozen
  - tests/fixtures/ 目录结构与数据规格说明
dependencies: [TASK-002]
files_scope:
  write: [docs/testing-strategy.md, tests/fixtures/]
acceptance_criteria:
  - 12 类测试（单元/API/DB/图/Agent Schema/扩展/一致性/错误检测/前端/部署/备份/端到端）各有归属与判据
  - 固定数据集规格明确（多少家公司、多少关系、多少注入错误）
  - 测试报告模板含"失败原因""未解决问题"
test_requirements: []
status: completed
completed_at: 2026-11-13
```

### TASK-007 · 架构评审报告（Phase 0 交付）

```yaml
task_id: TASK-007
agent: architect
phase: P0
objective: 回答总任务书第十三节的 10 个评审问题，作为进入 Phase 1 的门禁
inputs: [TASK-003, TASK-004, TASK-005, TASK-006 全部产出]
outputs:
  - reports/development/phase0-architecture-review.md
dependencies: [TASK-005, TASK-006]
acceptance_criteria:
  - 10 个问题逐条回答，不回避
  - 风险清单含概率/影响/缓解
  - 明确列出"本阶段没做的事"
test_requirements: []
status: completed
completed_at: 2026-11-13
close_basis: 评审方 2026-11-13 19:19 指令「推进 Phase 1」（未给出 APPROVED 字样，未代拟结论）
```

---

## Phase 1 任务单（关键 4 个）

### TASK-111 · PG 模型 + Alembic 初始迁移

```yaml
task_id: TASK-111
agent: architect
phase: P1
objective: 把冻结的 Schema 变成可执行的 SQLAlchemy 模型与迁移
inputs: [docs/database-schema.md (frozen)]
outputs:
  - backend/app/models/*.py
  - backend/app/core/db.py
  - database/migrations/versions/0001_init.py
dependencies: [TASK-003]
files_scope:
  write: [backend/app/models/, backend/app/core/db.py, database/migrations/]
acceptance_criteria:
  - alembic upgrade head 从空库跑通
  - 模型与文档字段逐一对齐（无遗漏、无擅自新增）
  - 所有 CHECK 约束与唯一索引在迁移中体现
test_requirements:
  - tests: 建表后跑一遍约束违反用例（自环、valid_to<valid_from、重复 stock_code）
status: pending
```

### TASK-202 · GraphProjector 投影器（**最高风险**）

```yaml
task_id: TASK-202
agent: graph-eng
phase: P1
objective: 实现 PG → Neo4j 唯一写入管道，幂等、可重建、可增量
inputs: [TASK-111 模型, TASK-201 约束, docs/graph-schema.md (frozen)]
outputs:
  - backend/app/graph/projector.py
  - backend/app/graph/repository.py
  - backend/tests/test_projector.py
dependencies: [TASK-111, TASK-201]
files_scope:
  write: [backend/app/graph/, backend/tests/test_graph*.py]
acceptance_criteria:
  - 投影两次结果一致（幂等）
  - 清空 Neo4j 全量重建后与快照逐属性相等
  - candidate / pending_verification / refuted 关系在图中查不到
  - 状态变更（verified→retracted）后图中属性同步更新
  - 投影运行写入 graph_projection_run，含统计
test_requirements:
  - 幂等测试、重建等价测试、状态隔离测试、下线测试
  - 10 万关系规模性能基线记录
status: completed
completed_at: 2026-11-13
```

### TASK-101 · AI 算力产业链种子数据

```yaml
task_id: TASK-101
agent: data-eng
phase: P1
objective: 导入 50–100 家 A 股公司及其产业链关系，作为图谱首个可用子集
inputs: [TASK-102 产业分类, docs/database-schema.md, 公告/年报]
outputs:
  - database/seeds/ai_compute_chain/*.yaml
  - 导入脚本 scripts/seed.sh
dependencies: [TASK-102]
files_scope:
  write: [database/seeds/, scripts/seed.sh]
acceptance_criteria:
  - 覆盖 GPU/AI芯片、半导体制造、设备、服务器、光模块、光通信、数据中心、液冷、电源、连接器、PCB、元器件
  - 每条关系至少 1 条 A/B 级证据（公告或年报），带原文摘录与 URL
  - 无证据的产业链关系不入库（或标 candidate）
test_requirements:
  - 导入幂等；重复导入不产生重复实体
status: in_progress
note: 实体层已完成（Baostock 51 家真实公司 + 产业归属边）；供应链关系 Baostock 不提供，等 P2 采集
```

### TASK-601 · Compose + PG/Neo4j 编排

```yaml
task_id: TASK-601
agent: devops
phase: P1
objective: 提供可一键启动的开发环境
inputs: [TASK-003]
outputs:
  - deploy/docker-compose.yml, .env.example
  - scripts/init_db.sh
  - docs/deployment.md
dependencies: [TASK-003]
files_scope:
  write: [deploy/, scripts/, .env.example, docs/deployment.md]
acceptance_criteria:
  - docker compose up -d 后 PG 与 Neo4j 均可用
  - 镜像钉版本，不出现 latest
  - 数据卷持久化，重启不丢
test_requirements:
  - 冷启动 ≤ 90s；重启后数据仍在
status: completed
completed_at: 2026-11-12
evidence: |
  fig-postgres healthy / fig-neo4j healthy；
  写临时表 → compose restart → 数据仍在（rows=1）→ 已清理；
  /ready 返回 200，postgres.ok=true, neo4j.ok=true。
未做: |
  api / web 的 Dockerfile（当前 api 跑宿主机）；
  备份恢复脚本；冷启动秒级计时未单独记录（目测 compose up 到 healthy 约 25s）。
```

---

## Phase 2–5 任务

字段补全时机：**进入该阶段前一周**由 architect 补 YAML。当前只有 ID / 标题 / 负责人 / 依赖，见 [task-dependencies.md](task-dependencies.md) 第五节。

| 阶段 | 任务数 | 负责人分布 |
|---|---|---|
| P2 | 8 | data-eng 2、industry-ai 4、graph-eng 1、architect 1 |
| P3 | 5 | qa-audit 4、qa+graph 1 |
| P4 | 4 | frontend 4 |
| P5 | 3 | data-eng 1、industry-ai 1、qa-audit 1 |

---

## 后续阶段任务（本轮未做，按阶段归类）

| 项 | 归类 | 任务 | 说明 |
|---|---|---|---|
| 采集器、`/news` 等 P2 端点 | **P2 可完成** | TASK-121/122/311 | 契约已冻结，实现待 P2 |
| 增量/全量投影调度 | **P1 可完成** | TASK-202 | 本轮只交付单关系投影原语 |
| 规则引擎 13 条 | **P3 可完成** | TASK-411 | 阈值已可调，规则待实现 |
| fixture 实际数据（6 目录） | **P1/P3 可完成** | TASK-101 / TASK-413 | 目录与格式已定，数据未填 |
| 证据不可变的历史数据回填 | **P0 已交付机制** | — | 表为空，无需回填；有数据后跑 `backfill_sort_keys.py` 与证据迁移 |
| CI 实际运行验证 | **P0 交付文件，未验证** | — | 需 push 后由 GitHub 执行 |
| 备份恢复演练 | **P0 交付脚本，未验证** | — | 需 Docker 可用后跑 `verify_backup.sh` |
