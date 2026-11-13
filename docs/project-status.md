# 项目状态

> 最后更新：2026-11-13 23:20 · 维护者：`architect`
> **状态语义严格区分**：未开始 / 已写代码 / 已运行 / 测试通过 / 已合并 / 已部署 / 已验证实际数据。

---

## 一、当前阶段

**Phase 0 — 已完成** ｜ **Phase 1 — 进行中**

- Phase 0 关闭依据：评审方 2026-11-13 19:19 指令「推进 Phase 1」（原文），视为授权进入下一阶段。
  **未收到 APPROVED / WITH CONDITIONS 字样，记录中不代拟评审结论。**
- 已知限制（随 Phase 1 携带）：未在独立物理机/VM 验证 OS 层部署。

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
| **`reports/development/phase0-architecture-review.md`** | ✅ **v3 已提交，待签署** | 三类清单（已完成/已验证/暂缓）+ 19 项不变量核验 + CI 记录 |
| 代码 | ✅ 骨架 + **3 个迁移** + 状态守卫 + 投影原语 | **全量 100 passed / 不变量核验 19 passed** |

**Phase 1 目标**：AI 算力产业链图谱底座 —— 能查公司、查上下游、看证据、可重建、可追溯。

### Phase 1 进度（2026-11-13 19:30）

| 项 | 状态 | 证据 |
|---|---|---|
| 完整投影器（full/incremental/剪枝/reconcile） | ✅ | `test_projector_rebuild.py` 6 例 |
| 遍历（neighbors/path/subgraph + 深度与节点上限） | ✅ | `test_traversal.py` 8 例 |
| 读 API（25 个端点） | ✅ | `test_api_graph.py` 9 例；`/openapi.json` 可生成 |
| 产业分类 16 个 | ✅ | `database/seeds/industries.yaml` |
| 真实公司数据（Baostock） | ✅ **51 家** | `database/seeds/ai_compute_universe.yaml` + `import_baostock_universe.py` |
| 供应链关系（supplies_to） | 🟡 **已打通路径，覆盖率有限** | 巨潮关联交易公告；样例 3 条 A 级边已入图 |
| 巨潮数据源调查 | ✅ 完成 | `reports/development/datasource-cninfo-investigation.md` |
| 年报子公司表抽取 | ✅ 已接入（中际旭创 26 家，全 A 级） | `scripts/import_subsidiaries.py` |
| gsxt 可用性评估 | ✅ 完成（结论：不接入） | `reports/development/datasource-gsxt-assessment.md` |
| Tushare 接入 | ✅ 51 家：申万三级 + 主营构成 | `scripts/enrich_classification_tushare.py` |
| Tushare 评估 | ✅ 完成（无供应链数据） | `reports/development/datasource-tushare-assessment.md` |
| 东方财富接入 | ✅ 51 家：实控人 + 核心题材 | `scripts/enrich_eastmoney.py` |
| 东财评估 + 五源总账 | ✅ 完成 | `reports/development/datasource-eastmoney-assessment.md` |
| 演示数据 | 已移除 | 按评审方指示删除 |
| 全量测试 | ✅ **127 passed** | `reports/testing/2026-11-13-full.log` |
| 子公司批量抽取 | ✅ **470 家子公司 / 479 条股权边（47/51 家）** | `reports/development/phase1-path1-subsidiaries.md` |
| 图一致性 | ✅ **537 节点 / 531 边** / `reconcile consistent=True` | 同上 |

交付报告：`reports/development/phase1-delivery.md`

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
| 契约层冻结 | 三份文档 `status: frozen` **v1.1** + 测试策略 v1.1 |
| 裁决执行 | disputed 语义、阈值只入核验、排序键、I-5 触发器、predicate CHECK |
| 迁移 2 | `c7d1e4a92f10` **已在真实库执行**：28 表 / 2 视图 / 3 触发器；`alembic check` 无差异 |
| 全量测试 | **100 passed / 0 failed**（PG + Neo4j 实连） |
| 备份恢复演练 | `verify_backup.sh` PASSED（含真实数据比对） |
| 排序键 | `core/sortkey.py`（拼音 + 多音字 + 数字补零），12 个单测通过 |
| 投影原语 | `graph/projector.py`（单关系投影 + 删边），7 个测试待 DB |
| 运维脚本 | `backup.sh` / `restore.sh` / `verify_backup.sh`（未演练） |
| CI | `.github/workflows/ci.yml`（未在 GitHub 运行） |
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
| B-08 | 证据阈值未校准（Q-03b） | TASK-411 | 需 TASK-101 真实数据 |
| B-09 | ~~Docker 守护进程不可用~~ | — | ✅ 已解除（评审方手动启动，29.9.3） |
| B-10 | ~~`fig-api:0.1.1` 重建被 Hub 502 阻断~~ | — | ✅ 已解除（重试成功，已部署验证） |
| B-11 | 无独立物理机/VM 做从零部署 | 「换台机器一定能跑」缺直接证据 | 外部环境项，不计代码缺陷；CI 全新 runner 为等价证据 |

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
| D-06 | ~~证据不可变只有约定~~ | ✅ 已由触发器强制（ADR-0011） |
| D-07 | ~~`predicate` 无 DB CHECK~~ | ✅ 已加 CHECK，取值 = 关系类型枚举 |
| D-08 | 排序键算法升级需全量回填，期间键与原文可能不一致 | 每次升 `SORT_KEY_VERSION` 时跑 backfill |
| D-09 | ~~迁移未在真实库验证~~ | ✅ 已执行并通过 `alembic check` |

---

## 八、下一步

1. **恢复 Docker**（人工启动 Docker Desktop），然后依次执行：
   `alembic upgrade head` → `alembic check` → `pytest`（含 db/neo4j）→ `scripts/verify_backup.sh`
2. 把上述原始输出补进评审报告第六节，替换当前「未验证」标注
3. **评审方**签署 APPROVED / WITH CONDITIONS / REJECTED
4. 签署通过后 Phase 0 才置 `completed`，进入 Phase 1
5. 未获批准前**不启动 Phase 1 业务开发**
