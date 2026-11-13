# Neo4j 图 Schema

> 版本 **v1.1** · 2026-11-13 · 状态：**frozen**
> 权威 DDL：`database/neo4j/constraints.cypher`、`indexes.cypher`（已应用到 Neo4j 5.26）
> 维护者：`graph-eng` ｜ 会签：`architect`

---

## 一、图的定位

**Neo4j 不是事实源，是一张为了多跳遍历而存在的物化视图。**

推论（每条都影响实现）：

1. 图上任何属性都必须能从 PG 重新算出来。算不出来的字段，不许出现在图上。
2. 图上不存证据正文，只存 `evidence_count` / `evidence_grade_max` / `evidence_missing`。
3. 图上不存审计历史，历史在 `relationship_history`。
4. **等价性断言**：清空全图 → 全量投影 → 与快照比对。比对**排除** `projected_at`、`projection_run_id` 两个元数据字段（它们每次投影都会变，属于投影自身的账本，不是业务属性）。
5. 只有 `app/graph/projector.py` 可以写图。任何其他模块写图 = 架构违规。

---

## 二、节点标签

统一 **主标签 `:Entity` + 类型子标签**。不建纯动态标签（避免全表扫）。

| 子标签 | PG 来源 `entity_type` | 必须携带的属性 |
|---|---|---|
| `:Country` | `country` | `uid, name` |
| `:Policy` | `policy` | `uid, name` |
| `:MacroEvent` | `macro_event` | `uid, name` |
| `:Industry` | `industry` | `uid, name, industry_code` |
| `:Sector` | `sector` | `uid, name, industry_code` |
| `:Technology` | `technology` | `uid, name` |
| `:Product` | `product` | `uid, name` |
| `:RawMaterial` | `raw_material` | `uid, name` |
| `:Equipment` | `equipment` | `uid, name` |
| `:ListedCompany` | `listed_company` | `uid, name, stock_code, exchange, industry_code` |
| `:PrivateCompany` | `private_company` | `uid, name` |
| `:Subsidiary` | `subsidiary` | `uid, name` |
| `:NewsEvent` | `news_event` | `uid, name, event_type, importance, published_at` |
| `:ResearchReport` | `research_report` | `uid, name` |
| `:EvidenceFile` | `evidence_file` | `uid, name, grade` |

**已删除 `:Stock` 标签**：股票不是独立实体，是 `:ListedCompany` 的属性。上一版把 `:Stock` 与 `:ListedCompany` 并列，导致两者争用同一个 `stock_code` 唯一约束，属于过度建模。

**已删除 `:Customer` / `:Supplier` / `:Competitor`**：它们是关系角色，不是实体种类。建标签会诱导把「客户」当实体存。

**通用属性**

| 属性 | 来源 | 说明 |
|---|---|---|
| `uid` | `entity.id` | 与 PG 完全相同 |
| `entity_type` | `entity.entity_type` | 便于统一过滤 |
| `name` | `entity.canonical_name` | — |
| `normalized_name` | `entity.normalized_name` | 匹配用 |
| `industry_code` | `entity.industry_code` | 冗余，便于按产业筛 |
| `projected_at` | 投影时间 | **元数据，等价性断言排除** |
| `projection_run_id` | 批次号 | **元数据，等价性断言排除** |

**`attributes` jsonb 不进图**。它是个白名单容器，不同实体类型 key 不同；进图会变成「什么都能塞」的垃圾桶。需要时由 API 从 PG 补。

---

## 三、关系类型

| Cypher 类型 | PG `relationship_type` | 方向 |
|---|---|---|
| `BELONGS_TO_INDUSTRY` | `belongs_to_industry` | (Entity)→(Industry) |
| `UPSTREAM_OF` | `upstream_of` | (Entity)→(Entity) |
| `DOWNSTREAM_OF` | `downstream_of` | (Entity)→(Entity) |
| `SUPPLIES_TO` | `supplies_to` | (Supplier)→(Customer) |
| `PURCHASES_FROM` | `purchases_from` | (Buyer)→(Supplier) |
| `CONTROLS` | `controls` | (Parent)→(Child) |
| `HOLDS_STAKE_IN` | `holds_stake_in` | (Investor)→(Investee) |
| `SUBSIDIARY_OF` | `subsidiary_of` | (Sub)→(Parent) |
| `CUSTOMER_OF` | `customer_of` | (Entity)→(Entity) |
| `COMPETES_WITH` | `competes_with` | 单向存 + `symmetric=true` |
| `APPLIES_TECHNOLOGY` | `applies_technology` | (Company)→(Technology) |
| `DEPENDS_ON_PRODUCT` | `depends_on_product` | (Entity)→(Product) |
| `AFFECTED_BY_POLICY` | `affected_by_policy` | (Entity)→(Policy) |
| `AFFECTED_BY_EVENT` | `affected_by_event` | (Entity)→(NewsEvent) |
| `DEMAND_TRANSMITS_TO` | `demand_transmits_to` | (Entity)→(Entity) |

**不进图的关系类型**（候选层专用，见 `CANDIDATE_LAYER_RELATIONSHIP_TYPES`）：
`potential_beneficiary`、`potential_loser`、`potential_supplier`、`potential_customer`。

> 决策依据（2026-11-13）：AI 的产业链推测如果进图，会沿上下游不断扩散，最后得到一张看起来完整、实际错误的图谱。这四类关系只存在于 PG 候选层，通过 `/claims` 与 `/relationships?status=candidate` 提供给前端。

**关系通用属性**

| 属性 | 来源 | 说明 |
|---|---|---|
| `rid` | `relationship.id` | 关系键，**不是端点组合** |
| `status` | `relationship.status` | 只可能是 verified / disputed / expired / revoked |
| `disputed_at` | `relationship_history`（进入 disputed 的时刻） | 仅 disputed 边有；前端据此显示「何时被挑战」 |
| `confidence` | `relationship.confidence` | 原值，图侧不做任何再计算 |
| `valid_from` / `valid_to` | 同名列 | — |
| `evidence_count` | `v_evidence_distinct` 计数 | 按 `content_hash` 去重后的条数 |
| `evidence_grade_max` | `min(evidence_grade)` | A 最强 |
| `evidence_missing` | `evidence_count = 0` | 显式标记，不隐藏 |
| `projected_at` | 投影时间 | 元数据 |

---

## 四、约束与索引（已应用）

```cypher
// stock_code 约束挂在 :Entity 上，不挂 :ListedCompany。
// 原因：投影是 MERGE (n:Entity {uid}) 再补子标签，若约束只挂子标签，
// 两个尚未打标的 :Entity 可以带同一个 stock_code 而不被拦。
// Neo4j 的唯一约束对 null 属性不生效，因此非公司实体（stock_code 为 null）不受影响。
CREATE CONSTRAINT entity_uid IF NOT EXISTS FOR (n:Entity) REQUIRE n.uid IS UNIQUE;
CREATE CONSTRAINT entity_stock_code IF NOT EXISTS FOR (n:Entity) REQUIRE n.stock_code IS UNIQUE;
CREATE CONSTRAINT industry_code IF NOT EXISTS FOR (n:Industry) REQUIRE n.industry_code IS UNIQUE;
CREATE CONSTRAINT news_event_uid IF NOT EXISTS FOR (n:NewsEvent) REQUIRE n.uid IS UNIQUE;
```

索引：`name`、`normalized_name`、`entity_type`、`industry_code` 节点属性；`SUPPLIES_TO`/`UPSTREAM_OF` 的 `status`，以及高频类型的 `rid`。

> 关系属性索引必须指定类型（Neo4j 5 限制），不能写 `()-[r]-()`。

---

## 五、投影规则

### 5.1 准入（唯一入口）

```sql
SELECT r.* FROM relationship r
WHERE r.status IN ('verified','disputed','expired','revoked')
  AND r.relationship_type NOT IN
      ('potential_beneficiary','potential_loser','potential_supplier','potential_customer')
  AND r.updated_at > :last_run_updated_at;
```

三重过滤，缺一不可：状态、类型、增量水位。

### 5.1b disputed 的投影语义（评审裁决 2026-11-13）

`disputed` **入图，但必须自证身份**：

| 要求 | 落地 |
|---|---|
| 可查询 | `status='disputed'`，`GET /graph/*` 默认不返回，需 `include_disputed=true` |
| 不得冒充事实 | 前端必须用虚线 + 「有争议」标签；不得与 verified 同色同线型 |
| 不得用于传导 | `assert_usable_for_propagation` 只放行 `verified`；传导算法过滤 disputed |
| 双方证据都要在 | `evidence_count` 只统计 supporting；`contradicting_count` 单独暴露 |

投影时**不合并** disputed 与 verified 为同一状态：两者并存于同一三元组是不允许的（部分唯一索引限制活跃三态），因此一条三元组在同一时刻要么 verified 要么 disputed，切换时更新同一条边。

### 5.2 写入语义

```cypher
MERGE (s:Entity {uid: $src_uid})
  SET s:ListedCompany, s.name = $src_name, s.stock_code = $src_stock_code,
      s.exchange = $src_exchange, s.industry_code = $src_industry,
      s.projected_at = $now, s.projection_run_id = $run
MERGE (t:Entity {uid: $tgt_uid}) SET t.projected_at = $now, t.projection_run_id = $run
MERGE (s)-[r:SUPPLIES_TO {rid: $rid}]->(t)
  SET r.status = $status, r.confidence = $confidence,
      r.evidence_count = $ev_count, r.evidence_grade_max = $ev_grade,
      r.evidence_missing = $ev_missing, r.projected_at = $now
```

- 一律 `MERGE`，不用 `CREATE`（幂等的前提）。
- **`stock_code` 必须在节点上写**，否则唯一约束形同虚设（上一版的实际缺陷）。
- 状态变为 `rejected` 的关系从图中移除（它已被证伪，不是事实）。`revoked` 保留在图中但 `status='revoked'`，痕迹不丢。

### 5.3 增量与全量

| 模式 | 触发 | 行为 |
|---|---|---|
| incremental | 每 5 分钟 / 状态变更事件 | 按 `updated_at > last_run` 拉取；处理下线 |
| full | 手动 / 每周校验 | 清空重建，与快照比对（排除元数据字段） |

每周一致性校验：`PG 应入图关系数` vs `图中关系数`，差异 > 0 记 `quality_issue(PRJ-001)`。

---

## 六、遍历约定

| 参数 | 默认 | 上限 | 超限行为 |
|---|---|---|---|
| `depth` | 1 | 5 | `400 DEPTH_LIMIT_EXCEEDED` |
| `max_nodes` | 300 | 2000 | 返回 `truncated=true` + 已取部分 |
| `min_confidence` | 0 | — | 低于阈值不返回，但计数在 `meta` 体现 |

- 默认只返回 `status='verified'`；`include_disputed=true` 才含 disputed；`revoked` 仅 admin。
- **防环**：必须用 visited 集合或 `apoc.path` 的 `NODE_PATH` 唯一性，禁止无限递归。
- **不分页**：`truncated=true` 即终态，客户端缩小范围重取（见 `api-contracts.md` 3.4）。

---

## 七、字段映射完整性（可重建性证明）

| 图属性 | PG 表达式 | 可算？ |
|---|---|---|
| `Entity.uid` | `entity.id` | ✅ |
| `Entity.name` | `entity.canonical_name` | ✅ |
| `Entity.entity_type` | `entity.entity_type` | ✅ |
| `Entity.stock_code` | `entity.stock_code` | ✅ |
| `Entity.industry_code` | `entity.industry_code` | ✅ |
| `NewsEvent.event_type` | `news_event.event_type` | ✅ |
| `NewsEvent.importance` | `news_event.event_importance` | ✅ |
| `NewsEvent.published_at` | `news_event.published_at` | ✅ |
| `r.rid` | `relationship.id` | ✅ |
| `r.status` | `relationship.status` | ✅ |
| `r.confidence` | `relationship.confidence` | ✅ |
| `r.evidence_count` | `count(*) from v_evidence_distinct join relationship_evidence` | ✅ |
| `r.evidence_grade_max` | `min(v_evidence_distinct.best_grade)` | ✅ |
| `r.evidence_missing` | `evidence_count = 0` | ✅ |

**上一版的问题**：`:Policy.policy_level`、`:ResearchReport.institution`、`:EvidenceFile.grade` 在图上有、PG 里算不出。现在这三类节点只保留 `uid + name`，其余信息由 API 从 `entity.attributes` 补。**宁可图上少一个属性，也不要一个算不出来的属性。**

---

## 八、已知未做

| 项 | 原因 |
|---|---|
| `COMPETES_WITH` 双向 vs 单向 | 暂定单向 + `symmetric=true`，查询需双向匹配；未压测 |
| `POTENTIAL_*` 是否需要一个独立的「推断子图」视图 | 当前完全不进图；若前端需要可视化候选网络，需单独设计，不在本版 |
| 全量重建期间的读一致性 | 未实现双写过渡，重建窗口内图不可用（秒级） |
| 投影器完整性 | 当前只实现「单条关系投影 + 单边删除」两个原语（`app/graph/projector.py`）；增量/全量调度属 TASK-202 |
| 投影性能基线 | 未压测 10 万关系规模 |
