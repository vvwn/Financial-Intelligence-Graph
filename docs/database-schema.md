# PostgreSQL 数据结构

> 版本 **v1.1** · 2026-11-13 · 状态：**frozen**
> 权威 DDL：`bdaf9a0511cb_init_schema.py` + `c7d1e4a92f10_disputed_sortkeys_evidence_origin.py`
> 本文解释设计意图与约束理由；两者不一致时以迁移文件为准，并立即修正本文。
> 维护者：`architect`（唯一写入者）

---

## 一、设计原则

1. **PG 是唯一事实源**（ADR-0001）。Neo4j、缓存、前端状态都是派生。
2. **证据不可变**。修正靠新增 `evidence` 行 + `supersedes_id`，不改正文。
3. **关系不物理删除**。只做状态迁移；`relationship_history` 只追加，DB 触发器强制。
4. **Claim 与 Relationship 是两张表**。一条关系可由多个 Claim 支撑（`claim_relationship`）。
5. **所有时间 `timestamptz`**，存 UTC。主键统一 `uuid`（UUIDv7，应用侧生成）。
6. **枚举用 `text + CHECK`**，不用 PG 原生 enum（原生 enum 改值需要 ALTER TYPE，迁移成本高）。

---

## 二、表目录（25 张）

| 域 | 表 | 说明 |
|---|---|---|
| 实体 | `entity` | 统一实体表，含 `entity_type`、`stock_code`、`attributes`、**`name_sort_key`** |
| | `entity_sort_key_history` | **排序键变更审计（只追加）** |
| | `entity_alias` | 别名/曾用名/英文名 |
| | `company_profile` | 上市公司业务档案（主营、产品收入构成、产业链位置） |
| | `industry_taxonomy` | 产业分类树（自引用 `parent_code`） |
| 采集 | `source` | 信源 + **抓取水位** `last_fetched_at` |
| | `news_raw` | 原始抓取记录，含 `raw_hash`、`duplicate_of` |
| | `news_event` | 归一化事件，`dedup_key` 唯一 |
| | `news_raw_event` | N 条转载 → 1 条事件 |
| | `collect_run` | 一次采集的汇总 |
| | `collect_run_source` | **per-source 明细**（一行汇总看不出哪个源坏了） |
| | `dead_letter` | 失败条目 + `http_status` + `next_retry_at` |
| 证据 | `evidence` | 不可变证据，含 **`origin_key`**（原始报道标识）与 `syndicated_from_id` |
| 主张 | `claim` | AI 产出的主张，含 `object_text` 字面量对象 |
| | `claim_evidence` | 主张↔证据（supporting / contradicting） |
| | `entity_mention` | 实体提及位置（实体合并后可回溯重链） |
| | `claim_relationship` | 主张↔关系（替代无外键的 `uuid[]`） |
| 关系 | `relationship` | 正式关系，7 态状态机 |
| | `relationship_evidence` | 关系↔证据 + **`relation`（supporting/contradicting）** + `weight` |
| | `relationship_history` | **只追加**的状态迁移审计，含 **`trigger`** |
| 传导 | `impact_path` | 事件影响路径，含 `status`（valid / invalidated / stale） |
| 运维 | `app_setting_history` | **阈值等配置的变更审计（只追加）** |
| | `quality_issue` | 质检问题 |
| | `analysis_run` | 每次 LLM 分析的 token/耗时/状态 |
| | `graph_projection_run` | 每次投影统计 |
| | `idempotency_key` | `Idempotency-Key` 落库，否则该请求头只是装饰 |
| | `app_setting` | 可调参数（扩展深度、阈值等），迁移时已种入 7 项 |

---

## 三、关键约束（有理由的才列）

### 3.1 实体

```sql
-- 股票代码在「同一 entity_type 内」唯一，不是全局唯一。
-- 全局唯一会让 :Stock 与 :ListedCompany 抢同一个代码，分列建模直接不可能。
CREATE UNIQUE INDEX ux_entity_type_stock_code
  ON entity (entity_type, stock_code) WHERE stock_code IS NOT NULL;

-- 无股票代码的实体（产业、技术、产品）按 (类型, 归一化名) 唯一
CREATE UNIQUE INDEX ux_entity_type_norm_name
  ON entity (entity_type, normalized_name)
  WHERE status = 'active' AND stock_code IS NULL;

CREATE INDEX ix_entity_name_trgm ON entity USING gin (canonical_name gin_trgm_ops);
-- 依赖扩展：CREATE EXTENSION IF NOT EXISTS pg_trgm（迁移首行执行）
```

### 3.2 采集与去重

```sql
-- 唯一键是 (source_id, url)，不是 raw_hash。
-- 同一篇文章被 5 家媒体转载必须能存 5 条 raw，否则「转载算 1 条证据」无从计算。
CREATE UNIQUE INDEX ux_news_raw_source_url ON news_raw (source_id, url);
CREATE INDEX ix_news_raw_hash ON news_raw (raw_hash);   -- 普通索引，用于找同文
```

**去重三层**：

| 层 | 键 | 作用 |
|---|---|---|
| 原始层 | `(source_id, url)` | 同一源同一链接不重复入库 |
| 转载层 | `raw_hash`（正文指纹） | 识别同文转载，`duplicate_of` 指向首条 |
| 事件层 | `news_event.dedup_key` | 归一化后的语义指纹，唯一 |

`dedup_key` 算法（`data-eng` 实现，`architect` 定）：`sha256(normalize(title) + "|" + event_type + "|" + date(published_at))`，`normalize` 去空白、全半角、标点、HTML 标签。

### 3.3 主张

```sql
-- 推断不得看起来确定
CHECK (claim_type <> 'hypothesis' OR confidence <= 0.3)
CHECK (claim_type <> 'inferred'   OR confidence <= 0.6)
-- 无主语或无宾语（实体或字面量）就不是一条主张
CHECK (subject_entity_id IS NOT NULL
       AND (object_entity_id IS NOT NULL OR object_text IS NOT NULL))
```

### 3.4 关系

```sql
-- 一个三元组同时只能有一条「活跃」关系。
-- rejected / revoked / expired 允许并存，因为撤销的边必须留痕，不能删。
CREATE UNIQUE INDEX ux_relationship_active_triple
  ON relationship (source_entity_id, relationship_type, target_entity_id)
  WHERE status IN ('pending_review','verified','disputed');

CHECK (source_entity_id <> target_entity_id)
CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
CHECK (confidence >= 0 AND confidence <= 1)
```

### 3.4b disputed 与证据双向

```sql
-- 一条证据可能同时被双方引用（不同来源对同一材料的解读相反），
-- 因此 relation 必须进主键，否则后写入的一侧会覆盖前一侧。
PRIMARY KEY (relationship_id, evidence_id, relation)
CHECK (relation IN ('supporting','contradicting'))

-- 进入 disputed 必须引用至少一条反向证据，否则「有争议」是空话。
CHECK (to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1)

-- 迁移原因必须可归类，便于审计与统计。
CHECK (trigger IN ('claim_promotion','evidence_threshold','manual_approval',
                   'new_evidence','rule','migration','manual'))
```

### 3.4c 排序键（locale=C 的配套）

```sql
-- 原始名称不动，另存一个可排序的键；版本号用于批量重算时区分算法。
entity.name_sort_key          text NOT NULL DEFAULT ''
entity.name_sort_key_version  varchar(8) NOT NULL DEFAULT 'v1'
CREATE INDEX ix_entity_name_sort_key ON entity (name_sort_key);

-- 键变化必须留痕，否则整张产业列表会被静默重排。
CREATE TABLE entity_sort_key_history (
  entity_id uuid, old_key text, new_key text,
  old_version varchar(8), new_version varchar(8),
  reason varchar(64), actor varchar(64), created_at timestamptz
);
```

键生成规则见 `backend/app/core/sortkey.py`：中文转无声调拼音（词组级，多音字按上下文）、ASCII 小写、数字补零到 6 位、标点转单一分隔符。**算法变更必须升 `SORT_KEY_VERSION` 并跑 `scripts/backfill_sort_keys.py`。**

### 3.4d 证据独立性与不可变（I-5、I-6）

```sql
-- 独立性看原始报道，不看文本哈希：转载、引用、摘编共用 origin_key。
evidence.origin_key        varchar(64) NOT NULL CHECK (origin_key <> '')
evidence.syndicated_from_id uuid REFERENCES evidence(id)

CREATE VIEW v_evidence_origin AS
SELECT origin_key, count(*) AS evidence_rows,
       count(DISTINCT content_hash) AS distinct_texts,
       min(evidence_grade) AS best_grade, min(collected_at) AS first_collected_at
FROM evidence GROUP BY origin_key;
```

**不可变触发器**（`trg_evidence_immutable`）：

| 操作 | 结果 |
|---|---|
| UPDATE `original_excerpt` / `content_hash` / `origin_key` / `source_*` / `evidence_grade` / 时间戳 | 抛异常 |
| UPDATE `supersedes_id` / `syndicated_from_id` | 抛异常（只能插入时设定） |
| DELETE | 抛异常 |
| UPDATE `verification_status` | **允许**（复核是合法动作） |

**追加式修正校验**（`trg_evidence_linkage`，BEFORE INSERT）：

- `supersedes_id` 必须指向已存在的行，且 `origin_key` 相同（同一报道的更正）
- 新行 `collected_at` 不得早于被替代行
- `syndicated_from_id` 必须指向已存在的行，且 `origin_key` 相同（转载继承来源）

### 3.5 视图与触发器

```sql
-- I-6：同 content_hash 的多次转载算 1 条独立证据
CREATE VIEW v_evidence_distinct AS
SELECT content_hash,
       (array_agg(id ORDER BY collected_at, id))[1] AS representative_id,
       min(evidence_grade)                          AS best_grade,  -- A<B<C<D，min 即最强
       count(*)                                     AS repost_count
FROM evidence GROUP BY content_hash;

-- I-4：历史表只追加，UPDATE/DELETE 直接抛异常
CREATE TRIGGER trg_relationship_history_immutable
  BEFORE UPDATE OR DELETE ON relationship_history
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
```

---

## 四、不变量与强制手段（逐条对应）

> 上一版的失败在于：不变量只写在文档里。现在每条都有代码或 DB 层面的落点。

| # | 不变量 | 强制手段 | 测试 |
|---|---|---|---|
| I-1 | 未验证关系不得进入图谱 | `validation.state_guard.assert_projectable` + 投影器只读 `PROJECTABLE_STATUSES` | `test_unverified_statuses_never_project` |
| I-2 | `inferred`/`hypothesis` 不可提升 | `PROMOTABLE_CLAIM_TYPES` + `relationship_service.transition` | `test_inferred_claim_can_never_be_promoted`、`test_inferred_claim_blocked_at_service_layer` |
| I-3 | verified 需 A/B 或 ≥2 条独立 C | `evaluate_promotion` + `VERIFIED_MIN_C_EVIDENCE` | `test_single_grade_c_rejected_two_accepted` |
| I-4 | 关系不物理删除；历史只追加 | DB 触发器 `trg_relationship_history_immutable` | `test_history_is_append_only` |
| I-5 | 证据不可变；修正只能追加 | DB 触发器 `trg_evidence_immutable` + `trg_evidence_linkage` | `test_update_excerpt_is_refused`、`test_delete_is_refused`、`test_correction_via_new_row_is_allowed` |
| I-6 | 同源转载只算 1 条独立证据 | `origin_key` 计数 + `v_evidence_origin` | `test_reposts_of_one_origin_cannot_enter_review` |
| I-7 | `valid_to >= valid_from` | DB CHECK `ck_relationship_valid_window` | 由 CHECK 保证 |
| I-8 | 三元组无活跃重复 | 部分唯一索引 `ux_relationship_active_triple` | `test_duplicate_active_triple_rejected` |
| I-9 | 无 Claim 支撑的关系不得 verified | `relationship_service.transition` 前置校验 | `test_no_claim_means_no_verification` |
| I-10 | 推断置信度不得超上限 | Python 守卫 + DB CHECK 双份 | `test_inferred_claim_confidence_capped_in_db` |
| I-11 | 阈值不得自动验证 | `evaluate_verification` 要求 `approved_by` | `test_threshold_alone_does_not_verify` |
| I-12 | disputed 必须有反向证据且双方并存 | DB CHECK + `dispute()` 服务 | `test_dispute_requires_contradicting_evidence`、`test_dispute_preserves_both_sides` |
| I-13 | disputed 不得用于传导 | `assert_usable_for_propagation` | `test_disputed_projects_but_cannot_drive_propagation` |

**I-5 已落地**：上一版只有代码约定，现在由触发器强制——禁改正文列、禁 DELETE、只允许改 `verification_status`；合法修正走 `supersedes_id` 追加，并有同源校验与时间顺序校验。双向测试见 `backend/tests/test_evidence_immutability.py`。

---

## 五、索引与性能预算

| 查询 | 目标 P95 | 手段 |
|---|---|---|
| 按股票代码查公司 | < 20ms | `ux_entity_type_stock_code` |
| 实体名模糊搜索 | < 50ms | `ix_entity_name_trgm`（GIN + pg_trgm） |
| 公司关系列表 | < 50ms | `ix_relationship_status` + `ix_relationship_target` |
| 待核验队列 | < 50ms | `ix_relationship_status`（`pending_review` 选择性高） |
| 质量指标聚合 | < 500ms | 实时聚合；>10 万关系后改物化视图 |
| 事件传导路径 | < 100ms | `ix_impact_path_event` |

---

## 六、排序与中文（已知取舍）

`POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C"`：数据库级 collation 为 C。

- **后果**：`ORDER BY name` 按字节序，中文不是拼音序；`lower()`/`upper()` 对非 ASCII 不生效。
- **不受影响**：`pg_trgm` 的 trigram 匹配与 collation 无关，模糊搜索正常。
- **应对**：需要中文排序时查询里显式 `COLLATE "zh-x-icu"`；名称匹配走 `normalized_name`（应用层归一化）。
- **为什么不用 ICU 初始化**：`postgres:16-alpine` 的 ICU 数据不保证完整，换 ICU 有初始化失败风险；而 C collation 索引更快、行为确定。这是**有意识的取舍**，不是疏忽。

---

## 七、已验证结果（2026-11-13 实测）

| 项 | 结果 |
|---|---|
| `alembic upgrade head` | 成功，25 张表 + 1 视图 + 1 触发器 |
| `alembic check` | **No new upgrade operations detected**（模型与库无差异） |
| 扩展 | `pg_trgm` 已创建 |
| 种子设置 | `app_setting` 7 项已插入 |
| 测试 | 51 passed（含 18 个 DB 集成测试） |
