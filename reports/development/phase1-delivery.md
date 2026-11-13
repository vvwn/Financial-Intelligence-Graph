# Phase 1 交付报告（TASK-202 / 203 / 211 / 102 / 101-部分）

> 提交时间：2026-11-13 19:30 · 交付方：`architect`
> 范围：图谱底座 —— 投影、遍历、读 API、产业分类、演示数据装载
> **未做**：真实 A 股公司数据（见第五节）、采集器（属 P2）、规则引擎（属 P3）

---

## 一、完成内容（对照 Phase 1 验收标准）

| 验收标准 | 状态 | 证据 |
|---|---|---|
| 能按股票代码/名称查公司 | ✅ | `GET /companies/{stock_code}`、`GET /entities?q=` |
| 能查某公司的上下游（含类型与方向） | ✅ | `GET /graph/neighbors?direction=up\|down\|both` |
| 每条关系能展开看证据 | ✅ | `GET /relationships/{id}/evidence`（含等级、来源、摘录、正反） |
| 已验证/待核验关系可区分 | ✅ | 图谱端点默认只返回 verified；`status` 字段随边返回 |
| 重启服务后数据仍在 | ✅ | PostgreSQL 持久化；容器重启演练已做 |
| 清空 Neo4j 可从 PG 完整重建，差异为 0 | ✅ | `test_full_rebuild_is_equivalent`、`admin/graph/reconcile` |
| 能做基础历史追踪 | 🟡 | `GET /history/relationships/{id}` 已通；演示数据直接置 verified，历史为空属预期 |

---

## 二、代码交付

| 文件 | 内容 |
|---|---|
| `app/graph/projector.py` | 单关系投影 + **full/incremental 扫描** + 剪枝 + `reconcile` + `graph_stats`；每次扫描写 `graph_projection_run` |
| `app/graph/traversal.py` | `neighbors` / `find_paths` / `subgraph`；深度 ≤5、节点 ≤2000、默认排除 disputed |
| `app/api/entities.py` | `/industries`、`/entities`、`/entities/{id}`、`/entities/{id}/relations`、`/companies`、`/companies/{code}` |
| `app/api/graph.py` | `/graph/subgraph`、`/graph/neighbors`、`/graph/path` |
| `app/api/relationships.py` | 列表/详情/证据/历史 + submit-review / verify / dispute / reject / revoke |
| `app/api/evidence.py` | `POST /evidence`（服务端算 content_hash）、`GET /evidence/{id}` |
| `app/api/admin.py` | `/admin/graph/project`、`/reconcile`、`/stats` |
| `app/schemas/api.py` | 响应模型（`Envelope[T]`），使 `/openapi.json` 可用于前端生成类型 |
| `database/seeds/industries.yaml` | AI 算力产业链 16 个分类（1 个一级 + 15 个二级） |
| `database/seeds/demo_companies.yaml` | **合成**演示数据：12 家公司 / 11 条关系 |
| `scripts/load_seed_data.py` | 种子装载；`--demo` 必须显式确认，生产环境拒绝运行 |

---

## 三、测试

```
$ backend/.venv/Scripts/python.exe -m pytest
123 passed in 128.38s
```

新增 23 个用例：

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_projector_rebuild.py` | 6 | 重建等价、幂等、增量剪枝、漂移检测、候选层拒绝、投影记录 |
| `test_traversal.py` | 8 | 深度 1 vs 2、深度越界 400、节点截断、方向过滤、路径、disputed 默认隐藏、产业过滤、未知节点 404 |
| `test_api_graph.py` | 9 | 信封、公司查询、404、产业树、子图、深度 400、关系+证据、无批准 422、空正文 400 |

**重建等价的做法**：投影 → 抓取每条边的属性快照（排除 `projected_at` / `projection_run_id`）→ 再全量投影 → 再抓快照 → 断言两次完全相等。

---

## 四、实测（真实输出）

```
full projection: nodes=12 edges=11 removed=0
reconcile: {'expected_edges': 11, 'actual_edges': 11, 'consistent': True}

/graph/neighbors depth=1 → nodes 7 edges 6
/graph/neighbors depth=2 → nodes 12 edges 11
/graph/neighbors depth=6 → 400 DEPTH_LIMIT_EXCEEDED

/graph/path 光器件 → 数据中心
  depth=3 min_confidence=0.82 | 光器件戊 → 光模块丁 → AI服务器己 → 数据中心子

/relationships?status=verified → 11 条
/relationships/{id}/evidence → grade A, relation supporting
/admin/graph/reconcile → consistent: True
```

日志：`reports/testing/2026-11-13-phase1-api-smoke.log`

---

## 五、未完成（明确列出）

| 项 | 原因 | 归属 |
|---|---|---|
| **供应链关系（supplies_to / upstream_of）** | Baostock **不提供**任何客户/供应商数据。没有真实公告或研报就无法生成，不编造 | 等 P2 采集器 + 人工核验 |
| 采集器与 `/news` 等端点 | 属 Phase 2 | TASK-121/122/311 |
| 规则引擎 13 条 | 属 Phase 3 | TASK-411 |
| 关系历史（真实迁移轨迹） | 演示数据直接置 verified，无迁移记录 | 随真实数据产生 |
| 性能基线 | 当前仅 12 节点 / 11 边，压测无意义 | 数据量上来后补 |

**演示数据已移除**（2026-11-13 19:55）。Baostock 走通后按评审方指示删除：`database/seeds/demo_companies.yaml` 已删，`load_seed_data.py` 只保留产业分类装载。当前库里是 51 家真实 A 股公司。

## 五之二、Baostock 接入结果

| 项 | 结果 |
|---|---|
| 连通性 | ✅ 登录成功，51 个代码全部解析 |
| 提供的数据 | 代码 / 名称 / 上市日期 / 上市状态 / 证监会行业分类 |
| **不提供的数据** | **任何供应链关系**（无客户、供应商、上下游） |
| 导入结果 | 51 家公司 + 16 个产业节点 + 51 条 `belongs_to_industry` 边 |
| 图规模 | 66 节点 / 51 边，`reconcile consistent=True` |

**公司名称由 Baostock 返回，不是我手写的**——这一步自动纠正了我记错的两处：
`300223` 现名「君正股份」（非北京君正）、`688347` 是「华虹宏力」（非华虹公司）。

**`belongs_to_industry` 的性质要说清**：证监会分类只到 `C39 计算机、通信和其他电子设备制造业` 这一级，
「中际旭创属于光模块」是本项目的产业划分判断，不是公告事实。因此该关系的 `attributes` 明确写了：

```json
{"classification_source": "project_taxonomy",
 "review_status": "pending_human_review",
 "csrc_industry": "C39计算机、通信和其他电子设备制造业"}
```

证据 `evidence_grade=B`，摘录原文同时包含证监会分类与本项目划分理由，可复核、可推翻。

---

## 六、需要评审方决策

1. **真实数据怎么进**：等 P2 采集器跑通后由 AI 抽 Claim + 人工核验，还是先人工录入 20–30 家作为 P1 收尾？
2. **演示数据是否保留在开发库**：保留便于演示，但会让 `GET /entities` 出现「合成样例·」前缀的公司。建议保留并在前端加 `synthetic` 标记。
