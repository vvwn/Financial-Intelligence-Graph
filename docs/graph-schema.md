# Neo4j 图 Schema（草案）

> 版本 v0.1 · 2026-11-12 · 状态：**draft，待 TASK-004 冻结**
> 维护者：`graph-eng` ｜ 会签：`architect`

---

## 一、图的定位（先读这段）

**Neo4j 不是事实源。** 它是一张**为了快速遍历而存在的物化视图**。

推论：

1. 图上任何属性都必须能从 PG 重新算出来。
2. 图上不存「证据正文」——只存 `evidence_count` 和 `evidence_ids`（或干脆只存 count，靠 PG 补全）。
3. 图上不存审计历史——历史在 PG 的 `relationship_history`。
4. 删库重建必须等价：`TRUNCATE` 全图 + 全量投影 = 原图（属性逐项相等）。

---

## 二、节点标签

统一使用 **一个主标签 `:Entity` + 一个类型子标签**。不用纯动态标签（避免 `MATCH (n:任意)` 全表扫）。

| 子标签 | 中文 | 关键属性 |
|---|---|---|
| `:Country` | 国家/地区 | `code` |
| `:Policy` | 政策 | `policy_level`, `issuer` |
| `:MacroEvent` | 宏观事件 | `event_date` |
| `:Industry` | 产业 | `industry_code` |
| `:Sector` | 行业 | `industry_code` |
| `:Technology` | 技术 | — |
| `:Product` | 产品 | `product_category` |
| `:RawMaterial` | 原材料 | — |
| `:Equipment` | 设备 | — |
| `:ListedCompany` | A股上市公司 | `stock_code`, `exchange` |
| `:PrivateCompany` | 非上市企业 | — |
| `:Subsidiary` | 子公司 | — |
| `:Stock` | 股票 | `stock_code` |
| `:NewsEvent` | 新闻事件 | `event_type`, `importance`, `published_at` |
| `:ResearchReport` | 研究报告 | `institution` |
| `:EvidenceFile` | 证据文件 | `grade` |

**通用属性（所有节点必须有）**

| 属性 | 类型 | 说明 |
|---|---|---|
| `uid` | string | 与 PG `entity.id` 完全相同 |
| `entity_type` | string | 枚举值 |
| `name` | string | canonical_name |
| `normalized_name` | string | 匹配用 |
| `industry_code` | string? | 冗余，便于按产业过滤 |
| `updated_at` | datetime | 投影时间，用于增量与排查 |
| `projection_run_id` | string | 最近一次写入的投影批次 |

---

## 三、关系类型

| Cypher 类型 | 语义 | 方向 |
|---|---|---|
| `BELONGS_TO_INDUSTRY` | 属于某产业 | (Entity)→(Industry) |
| `UPSTREAM_OF` | 上游 | (Entity)→(Entity) |
| `SUPPLIES_TO` | 供应产品给 | (Supplier)→(Customer) |
| `PURCHASES_FROM` | 从某公司采购 | (Buyer)→(Supplier) |
| `CONTROLS` | 控股 | (Parent)→(Child) |
| `HOLDS_STAKE_IN` | 参股 | (Investor)→(Investee) |
| `SUBSIDIARY_OF` | 子公司关系 | (Sub)→(Parent) |
| `CUSTOMER_OF` | 客户关系 | (Entity)→(Entity) |
| `COMPETES_WITH` | 竞争 | 双向语义，存储单向 + `symmetric=true` |
| `APPLIES_TECHNOLOGY` | 技术应用 | (Company)→(Technology) |
| `DEPENDS_ON_PRODUCT` | 产品依赖 | (Entity)→(Product) |
| `AFFECTED_BY_POLICY` | 政策影响 | (Entity)→(Policy) |
| `AFFECTED_BY_EVENT` | 事件影响 | (Entity)→(NewsEvent) |
| `DEMAND_TRANSMITS_TO` | 需求传导 | (Entity)→(Entity) |
| `POTENTIAL_BENEFICIARY` | 潜在受益（**必带低置信标记**） | (Entity)→(NewsEvent) |
| `POTENTIAL_LOSER` | 潜在受损（**必带低置信标记**） | (Entity)→(NewsEvent) |

**关系通用属性（投影必写）**

| 属性 | 类型 | 说明 |
|---|---|---|
| `rid` | string | PG `relationship.id` |
| `status` | string | `verified` / `disputed` / `expired` / `retracted` |
| `confidence` | float | 0..1，直接取 PG 值，**图侧不做任何再计算** |
| `valid_from` / `valid_to` | datetime? | — |
| `evidence_count` | int | 独立证据数（按 `content_hash` 去重后） |
| `evidence_grade_max` | string | A/B/C/D |
| `evidence_missing` | bool | 无证据时 `true`（不隐藏） |
| `updated_at` | datetime | 投影时间 |

> `POTENTIAL_BENEFICIARY` / `POTENTIAL_LOSER` 永远 `status != 'verified'`（它们是推断关系）。若上游强行标 verified，投影器应**拒绝并记 quality_issue**。

---

## 四、约束与索引

```cypher
// database/neo4j/constraints.cypher
CREATE CONSTRAINT entity_uid IF NOT EXISTS
FOR (n:Entity) REQUIRE n.uid IS UNIQUE;

CREATE CONSTRAINT industry_code IF NOT EXISTS
FOR (n:Industry) REQUIRE n.industry_code IS UNIQUE;

CREATE CONSTRAINT stock_code IF NOT EXISTS
FOR (n:ListedCompany) REQUIRE n.stock_code IS UNIQUE;

CREATE CONSTRAINT event_uid IF NOT EXISTS
FOR (n:NewsEvent) REQUIRE n.uid IS UNIQUE;
```

```cypher
// database/neo4j/indexes.cypher
CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE INDEX entity_norm IF NOT EXISTS FOR (n:Entity) ON (n.normalized_name);
CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.entity_type);
CREATE INDEX entity_industry IF NOT EXISTS FOR (n:Entity) ON (n.industry_code);
CREATE INDEX rel_status IF NOT EXISTS FOR ()-[r:SUPPLIES_TO]-() ON (r.status);
CREATE INDEX rel_rid IF NOT EXISTS FOR ()-[r]-() ON (r.rid);
```

> 关系属性索引在 Neo4j 5 需显式类型，逐类型建；先建高频 4 类（`SUPPLIES_TO`、`UPSTREAM_OF`、`BELONGS_TO_INDUSTRY`、`AFFECTED_BY_EVENT`）。

---

## 五、投影规则（`GraphProjector`）

### 5.1 准入

```sql
-- 只有这些关系进图
SELECT * FROM relationship
WHERE status IN ('verified','disputed','expired','retracted')
  AND updated_at > :last_run_updated_at;
```

`candidate` / `pending_verification` / `refuted` **永不投影**。

### 5.2 写入语义

```cypher
MERGE (s:Entity {uid: $src})
  SET s:ListedCompany, s.name = $src_name, s.updated_at = $now, s.projection_run_id = $run
MERGE (t:Entity {uid: $tgt})
  SET t.updated_at = $now, t.projection_run_id = $run
MERGE (s)-[r:SUPPLIES_TO {rid: $rid}]->(t)
  SET r.status = $status, r.confidence = $confidence,
      r.evidence_count = $ev_count, r.evidence_grade_max = $ev_grade,
      r.evidence_missing = $ev_missing, r.updated_at = $now
```

- 一律 `MERGE`，**不用 `CREATE`**（幂等的前提）。
- 关系键是 `rid`，不是端点组合（同一对实体可有多条不同类型关系）。
- 状态变为 `refuted` 的关系：**从图中删除**（因为它已不是事实）。这不算「删除已验证关系」——`refuted` 本就是「证伪」，图里不该有。真正需要保留痕迹的是 `retracted`，它在图里保留但 `status='retracted'`。

### 5.3 增量与全量

| 模式 | 触发 | 行为 |
|---|---|---|
| incremental | 每 5 分钟 / 关系状态变更事件 | 按 `updated_at > last_run` 拉取；处理下线 |
| full | 手动 / 每周一次校验 | 清空后全量重建，与快照比对差异 |

**一致性校验**（每周）：`PG 中应入图关系数` vs `图中关系数`，差异 > 0 记 `quality_issue(PRJ-001)`。

---

## 六、遍历约定

| 参数 | 默认 | 上限 | 超限行为 |
|---|---|---|---|
| `depth` | 1 | 5 | `400 DEPTH_LIMIT_EXCEEDED` |
| `max_nodes` | 300 | 2000 | 返回 `truncated=true` + 已取部分 |
| `min_confidence` | 0 | — | 低于阈值的关系不返回，但计数在 `meta` 中体现 |

**必带状态过滤**：默认只返回 `status='verified'`；`include_disputed=true` 才返回 disputed；`retracted` 仅 admin 可见。

**防环**：遍历必须用 `apoc.path.expandConfig` 的 `uniqueness: 'NODE_PATH'` 或手写 visited 集合，禁止无限递归。

---

## 七、图与 PG 的字段映射表

| PG | Neo4j | 转换 |
|---|---|---|
| `entity.id` | `n.uid` | 直接 |
| `entity.canonical_name` | `n.name` | 直接 |
| `entity.entity_type` | 子标签 + `n.entity_type` | 映射表 |
| `relationship.id` | `r.rid` | 直接 |
| `relationship.relationship_type` | 关系类型 | 大写下划线 |
| `relationship.confidence` | `r.confidence` | `numeric → float` |
| 独立证据数（视图） | `r.evidence_count` | `COUNT(DISTINCT content_hash)` |
| `max(evidence_grade)` | `r.evidence_grade_max` | A 最高 |

**任何图上出现、PG 里没有的字段 = bug。** 评审时逐字段核对。

---

## 八、待评审项（TASK-004）

1. `:Stock` 与 `:ListedCompany` 是否合并？（当前分列，可能过度建模）
2. `COMPETES_WITH` 单向存 + `symmetric=true`，还是双向各存一条？（前者省空间，后者查询简单）
3. `POTENTIAL_BENEFICIARY` 是否应该完全不进图，只留在 PG + API 组装？（**倾向：不进图**，避免推断关系污染图）
4. 是否需要 `:Industry` 层级关系 `PARENT_OF`，还是靠 `industry_code` 前缀？
5. 全量重建期间如何保证读一致性？（双写过渡 vs 短暂只读）
