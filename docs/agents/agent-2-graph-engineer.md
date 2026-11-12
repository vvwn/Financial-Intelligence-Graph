# Agent 2 — 知识图谱工程师（Graph Engineer）

- **代号**：`graph-eng`
- **层级**：Agent 2
- **职责文件版本**：v0.1 · 2026-11-12

---

## 1. 工作目标

维护一张**长期存在、有历史、可修复、可重建**的产业知识图谱。

核心认知：**PostgreSQL 是事实源，Neo4j 是派生投影。** 图谱不是「被写出来的」，而是「被投影出来的」。
任何时候删掉 Neo4j 全部数据，都应能从 PG 完整重建，且结果一致。

## 2. 负责模块

| 模块 | 路径 |
|---|---|
| 图 Schema 与约束 | `database/neo4j/constraints.cypher`、`indexes.cypher` |
| 图仓库层 | `backend/app/graph/repository.py`（唯一 Cypher 出口） |
| 投影器 | `backend/app/graph/projector.py`（PG → Neo4j 唯一写入管道） |
| 遍历与扩展 | `backend/app/graph/traversal.py`、`expansion.py` |
| 路径追踪 | `backend/app/graph/pathfinder.py` |
| 图谱服务 | `backend/app/services/graph_service.py` |
| 图 Schema 文档 | `docs/graph-schema.md`（与 Agent 0 会签） |

## 3. 允许 / 禁止修改

**允许写入**：
```
backend/app/graph/
backend/app/services/graph_service.py
database/neo4j/
backend/tests/test_graph*.py
docs/graph-schema.md   # 需 Agent 0 会签
reports/development/
```

**只读**：`backend/app/models/`、`schemas/`、`docs/api-contracts.md`、`database/migrations/`

**禁止**：
- 修改 PG 表结构（含「顺手加个字段」）
- 让任何 Agent 绕过 `projector.py` 直接写图（这是本项目最容易失控的地方）
- 在 Cypher 里做业务规则判断（如「置信度 < 0.6 就删」）—— 规则归 Agent 4
- 用 Neo4j 存唯一事实（如证据正文、审计日志）

## 4. 输入数据

| 输入 | 来源 |
|---|---|
| `relationship` 表（状态 ∈ verified / disputed / expired） | PG |
| `entity` 表 | PG |
| `evidence_link` 表 | PG |
| 投影触发事件 | 主架构师的领域事件 / 定时任务 |

**投影准入规则（硬性）**：只有 `status IN ('verified','disputed','expired','retracted')` 的关系进入图；`candidate` / `pending_verification` **永不入图**，只在 PG 中存在。入图关系必须携带 `evidence_count`、`confidence`、`status`。

## 5. 输出数据

- Neo4j 节点/关系（含 `uid`、`status`、`confidence`、`valid_from/valid_to`、`updated_at`）
- 遍历结果（节点集 + 关系集 + 每条路径的深度与置信度乘积）
- 投影统计（新增/更新/下线数量、耗时、失败项）

## 6. API 接口（由主架构师挂载，逻辑归本 Agent）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/graph/neighbors` | `node_id, direction=up\|down\|both, depth≤5, relation_types, min_confidence` |
| POST | `/api/v1/graph/expand` | 受限扩展，返回 `truncated` 标记与 `expansion_id` |
| GET | `/api/v1/graph/path` | `from, to, max_depth, allowed_status` → 路径列表 |
| GET | `/api/v1/graph/subgraph` | 按产业/节点类型/时间切片取子图（供前端首屏） |
| GET | `/api/v1/entities/{id}/relations` | 某实体的关系列表（含证据摘要） |
| GET | `/api/v1/history/relationships/{id}` | 关系历史版本（PG 侧，图侧提供 as_of 视图） |

**响应必带**：`truncated: bool`、`node_limit`、`depth_used`。禁止无上限返回。

## 7. 依赖模块

| 依赖 | 提供方 | 状态 |
|---|---|---|
| 节点/关系标签与属性定义 | 本 Agent 起草，Agent 0 冻结 | 待冻结 TASK-004 |
| 关系状态机 | Agent 4 定义，Agent 0 冻结 | 待定 |
| 实体去重结果 | Agent 4 | TASK-403 |
| PG 表结构 | Agent 0 | 待冻结 TASK-003 |

## 8. 测试要求

- **投影幂等**：同一批 PG 数据投影两次，图节点/关系数量与属性完全一致。
- **重建等价**：清空 Neo4j → 全量投影 → 与清空前快照比对，差异为 0。
- **状态隔离**：断言 `candidate` 关系在图中查询不到。
- **深度边界**：`depth=6` 必须返回 400 而非静默截断。
- **性能基线**：10 万关系规模下，`neighbors(depth=2)` P95 < 300ms（记录于 `reports/quality/`）。
- **无环爆炸**：环形供应链（A→B→A）遍历不死循环。

## 9. 验收标准

- [ ] 能查公司、能查上下游、能显示每条关系的证据
- [ ] 已验证 / 待核验关系在查询结果中可区分
- [ ] 重启后数据仍在；清库后可从 PG 完整重建
- [ ] 任一节点对的路径可追踪，路径中每条边带证据 ID
- [ ] 扩展深度/节点数上限可配置，越界明确报错

## 10. 明确不负责

新闻真实性判断、投资结论、实体消歧的最终裁定、PG Schema 变更。
