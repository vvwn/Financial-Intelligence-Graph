# Phase 0 架构评审报告（TASK-007）

> 提交时间：2026-11-13 · 提交方：`architect`
> 评审状态：**待评审（NOT YET REVIEWED）** — 本文不构成自我通过
> 评审依据：项目总任务书第十三节 + 2026-11-13 两项架构决策

---

## 一、结论摘要

Phase 0 的**契约层已冻结**，代码层已从「只有文档」变成「有约束、有测试、有迁移」。

| 项 | 结果 |
|---|---|
| 三份契约（DB / Graph / API） | ✅ 已冻结 v1.0 |
| 数据模型 | ✅ 25 张表 + 1 视图 + 1 触发器，已迁移到真实 PG |
| 模型与库一致性 | ✅ `alembic check` → No new upgrade operations detected |
| 不变量强制 | ✅ 10 条中 9 条有代码或 DB 落点（I-5 仅约定） |
| 后端测试 | ✅ **51 passed** |
| 静态检查 | ✅ ruff 全通过 |
| 容器化 | ✅ 镜像构建成功，容器内 `/ready` 三检全绿 |
| 缺陷修复 | 36 条中 **31 已修复 / 5 部分修复** |
| 未完成 | P1 业务端点、采集器、投影器、规则引擎（属 Phase 1–3） |

**本报告不声称 Phase 0 已通过。** 通过与否由评审方决定。

---

## 二、两项架构决策的落地

### 决策 1：`POTENTIAL_*` 不进正式图谱 → 已落地为双层结构

| 落地位置 | 实现 |
|---|---|
| 枚举 | `CANDIDATE_LAYER_RELATIONSHIP_TYPES` 固定 4 类：`potential_beneficiary` / `potential_loser` / `potential_supplier` / `potential_customer` |
| 代码门禁 | `validation/state_guard.py::assert_projectable` —— 遇到这 4 类直接抛 `STATE_TRANSITION_INVALID` |
| 投影准入 | 投影 SQL 三重过滤：状态 + 类型 + 增量水位（`graph-schema.md` 5.1） |
| 契约 | 候选层通过 `/claims`、`/relationships?status=candidate` 暴露；`/graph/*` 永不返回 |
| 测试 | `test_candidate_layer_types_never_project`（4 个参数化用例） |

「未通过核验的候选关系保留为已否定或待核验记录，不静默删除」→ 已由 `rejected` / `pending_review` 状态 + 无 DELETE 端点 + 触发器保证。

### 决策 2：PG 为状态机唯一真源 → 已落地

| 落地位置 | 实现 |
|---|---|
| 权威数据 | `relationship.status` 是唯一真源；Neo4j 只读投影 |
| 状态变更顺序 | 先写 PG（含 `relationship_history`），再由投影器同步 Neo4j |
| 不一致处理 | 以 PG 为准重建；每周一致性校验（`graph-schema.md` 5.3） |
| 审计四要素 | `relationship_history`：`actor` / `reason` / `evidence_ids[]` / `created_at` + `snapshot` 全行快照 |
| 禁止双写权 | 唯一写图通道 `GraphProjector`；无 `POST /relationships`、无 `DELETE` |
| 测试 | `test_revoke_keeps_the_row_and_appends_history`、`test_history_is_append_only` |

### ⚠️ 一处偏差，需评审方裁决

**我新增了第 7 个状态 `DISPUTED`**，你的清单只有 `CANDIDATE / PENDING_REVIEW / VERIFIED / REJECTED / EXPIRED / REVOKED`。

- 理由：总任务书第八节要求「存在冲突时必须保留双方证据，不允许 AI 自行选一个版本并隐藏另一个」。没有这个状态，冲突证据只能塞进 `verified`（污染事实）或 `rejected`（丢掉支持方证据）。
- 代价：状态机多一态，`verified ↔ disputed` 双向可达。
- 若你否决，我需要把冲突证据改放到 `claim_evidence.relation='contradicting'` 并让关系停在 `pending_review`——可行，但审计时看不出「曾已验证后被质疑」。

**这一条请明确 APPROVE 或 REJECT。**

---

## 三、36 条缺陷修复清单

来源：6 个角色 Agent 独立审查（2026-11-12 23:40）。

### 采集侧（`data-eng`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-01 | high | `raw_hash` 唯一索引使转载无法入库，与验收标准矛盾 | 唯一键改 `(source_id, url)`，`raw_hash` 降为普通索引 | ✅ |
| D-02 | high | `dedup_key` 算法未定；无事件类型枚举 | 定义指纹算法；新增 `NewsEventType`（16 值） | ✅ |
| D-03 | high | `/ingest/run` 同步/异步未定、响应体缺失、幂等键无落库 | 定为 **202 异步** + 返回 `run_id`；新增 `idempotency_key` 表 | ✅ |
| D-04 | high | 无信源水位表；`migrations/versions` 空 | 新增 `source` 表（含 `last_fetched_at`）；首个迁移已执行 | 🟡 seeds 仍空 |
| D-05 | medium | `dead_letter` 无法定位重放；`collect_run` 多源合一行 | 补 `url/http_status/next_retry_at/resolved_at`；新增 `collect_run_source` | ✅ |

### 图谱侧（`graph-eng`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-06 | high | 投影元数据导致「重建后逐属性相等」永远失败 | 等价性断言显式排除 `projected_at` / `projection_run_id` | ✅ |
| D-07 | high | 图上有 PG 算不出的属性（`policy_level`、`institution`、`grade` 等） | 重写映射表；算不出的属性一律不进图 | ✅ |
| D-08 | high | `stock_code` 全局唯一，`:Stock` 与 `:ListedCompany` 抢代码 | 改 `(entity_type, stock_code)` 复合唯一；删除 `:Stock` 标签 | ✅ |
| D-09 | medium | `stock_code` 约束挂 `:ListedCompany` 但 MERGE 只建 `:Entity`，约束空转 | 约束移到 `:Entity`；投影显式写 `stock_code`；旧约束已 DROP | ✅ |
| D-10 | medium | 准入含 `retracted` 但唯一索引排除它，同一三元组可并存多条 | 统一为 `revoked`；唯一索引只覆盖 `pending_review/verified/disputed` | ✅ |
| D-11 | medium | `v_evidence_distinct` 只被提及未定义；`evidence_missing` 无规则；`POTENTIAL_*` 自相矛盾 | 视图 DDL 已写入迁移；`evidence_count=0 → missing`；按决策 1 处理 | ✅ |

### 推理侧（`industry-ai`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-12 | high | 缺 `object` 字面量列；`EntityMention` 无表 | 新增 `claim.object_text` + `entity_mention` 表 | ✅ |
| D-13 | high | 无证据写入端点，`original_excerpt NOT NULL` 导致 Agent 无法落证据 | 契约新增 `POST /evidence` | ✅ 契约 |
| D-14 | high | `predicate` 与 `relationship_type` 无映射 | 冻结为**共用一套枚举** | 🟡 DB 未加 CHECK |
| D-15 | high | `state_guard.py` 不存在，`PROMOTABLE` 常量零引用，`claim_type` 全凭模型自报 | 实现 `state_guard` + `relationship_service` 强制调用 + 9 个测试 | ✅ |
| D-16 | medium | `derived_from_claim_ids uuid[]` 无外键、无法反向查 | 新增 `claim_relationship` 关联表（双向索引） | ✅ |
| D-17 | medium | `unknowns` 粒度不清（Claim 级 vs 全局级） | 定义：全局放 `analysis_run.output_snapshot`，Claim 级放 `claim.unknowns` | ✅ |

### 质量侧（`qa-audit`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-18 | high | `testpaths` 只收 `backend/tests`，根 `tests/` 永不执行 | 配置移到仓库根，`testpaths=["backend/tests","tests"]` | 🟡 fixtures 仍空 |
| D-19 | high | 404 测试是假绿灯（`{"detail"}` 非信封） | 新增 `StarletteHTTPException` 处理器；断言改为校验 `error.code` | ✅ |
| D-20 | high | `relationship.confidence` 无 CHECK | 补 `ck_relationship_confidence_range` | ✅ |
| D-21 | high | I-1..I-7 全部只是文档 | 9/10 条落到代码或 DB；I-5 见「未完成」 | 🟡 |
| D-22 | medium | 状态机表与 mermaid 有 4 处冲突 | 删除 mermaid，**以 7×7 表为唯一真源** | ✅ |
| D-23 | medium | 6 例注入判据缺失（#14/#16/#17/#21/#22/#23） | 逐条定义阈值，新增 `app_setting` 7 项种子 | ✅ |

### 前端侧（`frontend`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-24 | high | `/graph/subgraph` 无响应 schema、无 `node_limit`、`status` 语义不明 | 补齐完整响应示例；明确 `status` 只作用于边 | ✅ |
| D-25 | high | 「candidate 永不进图」与「前端要画 candidate 点线」冲突 | 双层结构：前端从候选层端点取，不进图 | ✅ |
| D-26 | high | 图谱端点是否分页未裁决，`truncated` 后无续页 | 明确**不分页**，`truncated` 即终态 | ✅ |
| D-27 | high | `as_of` 既在参数表又列待评审 | v1 移除该参数，P4 再评估 | ✅ |
| D-28 | medium | `/relationships/{id}/evidence` 字段未定 | 定义 `Evidence` 对象（14 字段） | ✅ |
| D-29 | medium | 左栏筛选无数据源 | 新增 `GET /industries`（含层级与计数） | ✅ |

### 运维侧（`devops`）

| # | 严重度 | 缺陷 | 修复 | 状态 |
|---|---|---|---|---|
| D-30 | high | 无首个 revision；`/ready` 不查迁移版本却返 200 | 首个迁移已执行；`/ready` 增加 `migration` 检查 | ✅ |
| D-31 | high | 无 Dockerfile，换机要手装三套运行时 | `deploy/backend.Dockerfile` + compose `full` profile；**已实测容器内 `/ready` 全绿** | ✅ |
| D-32 | high | 用 `gin_trgm_ops` 但全仓无 `CREATE EXTENSION` | 迁移首行 `CREATE EXTENSION IF NOT EXISTS pg_trgm` | ✅ |
| D-33 | medium | `locale=C` 导致中文按字节序、非 ASCII 大小写失效 | 记录为**有意识取舍**（C 索引更快；中文排序显式 `COLLATE`；trgm 不受影响） | 🟡 文档化 |
| D-34 | medium | `/ready` 串行真连打爆 pool；`request_id` 不进日志 | 并发探测 + 5s TTL 缓存；`ContextVar` + `RequestIdFilter` | ✅ |
| D-35 | medium | `.env` 明文、端口绑 0.0.0.0 | 端口改绑 `127.0.0.1`；生产环境弱密码启动即拒 | 🟡 未上 secrets |
| D-36 | low | `/health` 同时挂在根与 `/api/v1` | 探针只在根；业务只在 `/api/v1`；新增断言测试 | ✅ |

**统计：36 条 → 31 已修复 / 5 部分修复 / 0 未修复。**

---

## 四、总任务书要求的 10 个评审问题

| # | 问题 | 回答 |
|---|---|---|
| 1 | 当前架构是否合理？ | 合理。模块化单体 + 单一投影管道 + PG 唯一真源，在「AI 产出必须可证伪」这个约束下是最省心的组合。代价是投影器成为单点，已列为最高风险节点。 |
| 2 | 哪些技术有兼容性/实现风险？ | ① Neo4j Community 无集群、内存受限；② Cytoscape 万级节点性能未压测；③ APScheduler 多实例会重复执行（当前锁单 worker）；④ Python 3.13 轮子不全，已锁 3.12。 |
| 3 | 哪些功能可以并行开发？ | 采集适配器、前端骨架、图谱遍历、LLM 适配层、测试数据构造 —— 五路并行（见 `task-dependencies.md` W4 波次）。 |
| 4 | 哪些必须串行？ | Schema 冻结 → 迁移 → 投影器 → 遍历 → 读 API → 前端接真接口。这条链是唯一关键路径。 |
| 5 | 哪些部分最容易卡壳？ | ① 实体消歧（同名/曾用名/母子公司）；② 「证据达标」阈值校准（需真实数据）；③ 投影与 PG 的一致性校验；④ 中文排序与匹配（collation 取舍）。 |
| 6 | 如何降低 Agent 协作冲突？ | 目录归属矩阵 + 契约先冻结 + 单一写图管道 + 同一文件单写入者 + 子 Agent 默认只读。已实测 6 Agent 并行零冲突。 |
| 7 | 如何验证 AI 生成的产业关系？ | Claim/Evidence/Relationship 三层物理分离；提升需 ① 关联 Claim ② `fact_reported` ③ A/B 或 ≥2 独立 C ④ 无冲突证据。全部有代码与测试。 |
| 8 | 如何避免错误向下游扩散？ | 状态守卫拦非法迁移；撤销不删行只改状态；`impact_path.status` 支持 `invalidated`；撤销触发重算（TASK-415，未实现）。 |
| 9 | 如何保证数据可追溯？ | 证据不可变（`supersedes_id` 修正）+ `relationship_history` 全行快照 + `claim_relationship` 双向关联 + `analysis_run` 记录模型与 token。 |
| 10 | 如何控制初期成本？ | 不拆微服务、不引 Prefect、先做 AI 算力单产业 50–100 家、图谱不分页只限深限点。 |

---

## 五、测试证据（原文，未删改）

### 5.1 后端测试

```
$ backend/.venv/Scripts/python.exe -m pytest backend/tests -q
...................................................                      [100%]
51 passed
```

分类：单元（状态机/守卫）21 个、DB 集成 18 个、API 冒烟 7 个、日志 1 个、其余 4 个。

### 5.2 迁移与模型一致性

```
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> bdaf9a0511cb, init schema

$ alembic check
No new upgrade operations detected.
```

### 5.3 容器内运行（镜像实测）

```
$ curl http://127.0.0.1:8000/ready
{"data":{"status":"ready","version":"0.1.0","checks":{
  "postgres":{"ok":true,"error":null},
  "neo4j":{"ok":true,"error":null},
  "migration":{"ok":true,"current":"bdaf9a0511cb","expected":"bdaf9a0511cb","error":null}}}}

$ curl http://127.0.0.1:8000/api/v1/nope
{"error":{"code":"NOT_FOUND","message":"Not Found","details":{"path":"/api/v1/nope"},
  "request_id":"01a1d09a-6a54-7000-bf09-9a1aeed8c8f6"}}
```

### 5.4 静态检查

```
$ ruff check backend/app backend/tests scripts
All checks passed!
```

### 5.5 Neo4j 约束（已应用）

```
CONSTRAINT entity_stock_code ['Entity'] ['stock_code']
CONSTRAINT entity_uid        ['Entity'] ['uid']
CONSTRAINT industry_code     ['Industry'] ['industry_code']
CONSTRAINT news_event_uid    ['NewsEvent'] ['uid']
```

---

## 六、风险清单（更新）

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R-03 | 实体消歧不准 → 关系挂错公司 | 高 | **严重** | 代码强约束 + 别名表 + DUP 规则（P3）+ 人工复核队列 |
| R-04 | LLM 把推断写成事实 | 中（已降） | **严重** | 三层分离 + 状态守卫 + DB CHECK + 6 个反幻觉测试 |
| R-05 | 投影器与 PG 不一致 | 中 | 高 | 幂等/重建测试 + 每周一致性校验 |
| R-11 | 投影器成为单点故障 | 中 | 高 | 增量 + 全量重建能力；投影失败可重放 |
| R-12 | 中文排序/匹配不合预期 | 高 | 中 | `normalized_name` 应用层归一化；显式 `COLLATE` |
| R-13 | 证据达标阈值拍脑袋（当前 1×A/B 或 2×C） | 高 | 中 | 需 TASK-101 真实数据校准；参数在 `app_setting` 可调 |
| R-14 | 状态机 7 态含未经批准的 `DISPUTED` | 中 | 中 | 已列入待裁决项 |

---

## 七、未完成事项（明确列出，不隐瞒）

| 项 | 原因 | 归属 |
|---|---|---|
| 采集器、`/news` 等 P2 端点 | 属 Phase 2 | TASK-121/122 |
| 投影器 `GraphProjector` | 属 Phase 1，等 TASK-004 会签后开工 | TASK-202 |
| 规则引擎 13 条规则 | 属 Phase 3 | TASK-411 |
| `POST /evidence`、`/industries` 等端点实现 | 契约已冻结，代码未写 | TASK-211/311 |
| `seeds/sources.yaml`、六个 fixture 目录 | 数据构造未开始 | TASK-101/413 |
| **I-5 证据不可变** 只有约定，无 DB 触发器 | 担心堵死 `supersedes_id` 合法修正路径 | 待设计「禁改正文、允许改状态」的列级规则 |
| `predicate` 无 DB CHECK | 允许事件型谓词，尚未穷举 | TASK-003 收尾 |
| 备份/恢复脚本、CI | 未开始 | TASK-602 |
| 性能基线 | 数据量不足 | P2 后 |

---

## 八、请评审方裁决的三件事

1. **`DISPUTED` 第 7 态** 是否批准（见第二节）。
2. **`locale=C` 的取舍** 是否接受（中文排序在应用层解决，换取索引速度与初始化确定性）。
3. **`evidence.min_grade_for_verified = C` + 「1×A/B 或 2×独立 C」** 的阈值是否合理（当前为拍定值，需真实数据校准）。

---

## 九、附件

- `docs/database-schema.md`（frozen v1.0）
- `docs/graph-schema.md`（frozen v1.0）
- `docs/api-contracts.md`（frozen v1.0）
- `docs/testing-strategy.md`（frozen v1.0）
- `database/migrations/versions/bdaf9a0511cb_init_schema.py`（可执行 DDL）
- `backend/app/validation/state_guard.py`（状态机与提升规则）
- `backend/tests/`（51 个用例）
- `deploy/backend.Dockerfile`
