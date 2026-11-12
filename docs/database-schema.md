# PostgreSQL 数据结构（草案）

> 版本 v0.1 · 2026-11-12 · 状态：**draft，待 TASK-003 冻结**
> 维护者：`architect`（唯一写入者）｜ 会签：`graph-eng`、`qa-audit`、`data-eng`

---

## 一、设计原则

1. **PG 是唯一事实源。** 图库、缓存、前端状态都是派生。
2. **证据不可变。** `evidence` 表只插入，不更新正文；修正靠新增记录 + `supersedes_id`。
3. **关系不物理删除。** 只有状态迁移；`relationship_history` 记录每次变化。
4. **Claim 与 Relationship 是两张表。** 一条关系可由多个 Claim 支撑；一个 Claim 可拆成多条关系。
5. **所有时间用 `timestamptz`**，存 UTC。
6. **主键统一 `uuid`（UUIDv7）**，由应用生成，不用自增（跨库投影需要稳定 ID）。

---

## 二、核心表

### 2.1 实体

```sql
CREATE TABLE entity (
    id              uuid PRIMARY KEY,
    entity_type     text NOT NULL,          -- 见 api-contracts.md 枚举
    canonical_name  text NOT NULL,
    normalized_name text NOT NULL,          -- 去空格/全半角/后缀，用于匹配
    stock_code      text,                   -- 仅 listed_company / stock
    exchange        text,                   -- SSE / SZSE / BSE
    industry_code   text,                   -- 关联 industry_taxonomy
    description     text,
    attributes      jsonb NOT NULL DEFAULT '{}',
    status          text NOT NULL DEFAULT 'active',  -- active / merged / deprecated
    merged_into_id  uuid REFERENCES entity(id),      -- 合并留痕，不删除
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_entity_stock_code ON entity (stock_code) WHERE stock_code IS NOT NULL;
CREATE UNIQUE INDEX ux_entity_type_norm  ON entity (entity_type, normalized_name)
    WHERE status = 'active' AND stock_code IS NULL;
CREATE INDEX ix_entity_type ON entity (entity_type);
CREATE INDEX ix_entity_name_trgm ON entity USING gin (canonical_name gin_trgm_ops);

CREATE TABLE entity_alias (
    id         uuid PRIMARY KEY,
    entity_id  uuid NOT NULL REFERENCES entity(id),
    alias      text NOT NULL,
    alias_type text NOT NULL DEFAULT 'name',  -- name / former_name / abbr / english
    source_id  uuid,                          -- 来源证据（可空）
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_alias ON entity_alias (entity_id, alias);
```

**上市公司档案**（业务扩展，与 `entity` 一对一）

```sql
CREATE TABLE company_profile (
    entity_id            uuid PRIMARY KEY REFERENCES entity(id),
    full_name            text,
    former_names         text[],
    main_business        text,
    core_products        jsonb,       -- [{name, revenue_share, mass_production}]
    revenue_mix          jsonb,       -- [{segment, ratio, period}]
    chain_position       text,        -- 上游 / 中游 / 下游
    listed_at            date,
    updated_at           timestamptz NOT NULL DEFAULT now()
);
```

**产业分类**

```sql
CREATE TABLE industry_taxonomy (
    code        text PRIMARY KEY,     -- 自定义编码，如 AI-COMPUTE-GPU
    name        text NOT NULL,
    parent_code text REFERENCES industry_taxonomy(code),
    level       int  NOT NULL,
    description text
);
```

### 2.2 新闻与采集

```sql
CREATE TABLE news_raw (
    id            uuid PRIMARY KEY,
    source_id     text NOT NULL,
    source_name   text NOT NULL,
    url           text NOT NULL,
    title         text,
    content       text,
    raw_payload   jsonb,                -- 原始响应快照（可截断，但保留结构）
    published_at  timestamptz,
    fetched_at    timestamptz NOT NULL,
    raw_hash      text NOT NULL,        -- 全文/结构指纹
    duplicate_of  uuid REFERENCES news_raw(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_news_raw_hash ON news_raw (raw_hash);
CREATE INDEX ix_news_raw_url ON news_raw (url);

CREATE TABLE news_event (
    id                  uuid PRIMARY KEY,
    primary_raw_id      uuid NOT NULL REFERENCES news_raw(id),
    title               text NOT NULL,
    summary             text,
    event_type          text,           -- policy / earnings / capex / order / technology / ...
    event_importance    smallint,       -- 1..5
    verification_status text NOT NULL DEFAULT 'unverified', -- unverified/partially_verified/verified/disputed
    published_at        timestamptz,
    collected_at        timestamptz NOT NULL,
    dedup_key           text NOT NULL,  -- 归一化后的事件指纹
    attributes          jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_news_event_dedup ON news_event (dedup_key);

CREATE TABLE news_raw_event (           -- 转载归并：N 条 raw → 1 条 event
    raw_id   uuid PRIMARY KEY REFERENCES news_raw(id),
    event_id uuid NOT NULL REFERENCES news_event(id)
);

CREATE TABLE collect_run (
    id            uuid PRIMARY KEY,
    source_ids    text[],
    started_at    timestamptz NOT NULL,
    finished_at   timestamptz,
    fetched_count int NOT NULL DEFAULT 0,
    new_count     int NOT NULL DEFAULT 0,
    dup_count     int NOT NULL DEFAULT 0,
    error_count   int NOT NULL DEFAULT 0,
    status        text NOT NULL DEFAULT 'running'   -- running/succeeded/partial/failed
);

CREATE TABLE dead_letter (
    id          uuid PRIMARY KEY,
    run_id      uuid REFERENCES collect_run(id),
    source_id   text NOT NULL,
    payload     jsonb,
    error_type  text NOT NULL,     -- http_429 / http_5xx / parse_error / schema_drift
    error_msg   text,
    retry_count int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

### 2.3 证据（不可变）

```sql
CREATE TABLE evidence (
    id                 uuid PRIMARY KEY,
    source_type        text NOT NULL,   -- announcement / annual_report / gov_doc / media / research
    source_name        text NOT NULL,
    source_url         text,
    title              text,
    original_excerpt   text NOT NULL,   -- 原文摘录，禁止改写
    published_at       timestamptz,
    collected_at       timestamptz NOT NULL,
    evidence_grade     char(1) NOT NULL CHECK (evidence_grade IN ('A','B','C','D')),
    verification_status text NOT NULL DEFAULT 'unverified',
    content_hash       text NOT NULL,   -- 去重：同文转载同 hash
    supersedes_id      uuid REFERENCES evidence(id),
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_evidence_hash ON evidence (content_hash);
```

> **同一 `content_hash` 的多条转载视为 1 条独立证据。** 计数时按 `DISTINCT content_hash`。

### 2.4 Claim（AI 产出，可被质疑）

```sql
CREATE TABLE claim (
    id                      uuid PRIMARY KEY,
    subject_entity_id       uuid REFERENCES entity(id),
    predicate               text NOT NULL,       -- relationship_type 之一，或事件型谓词
    object_entity_id        uuid REFERENCES entity(id),
    claim_type              text NOT NULL CHECK (claim_type IN
                              ('fact_reported','inferred','hypothesis','disputed')),
    confidence              numeric(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status                  text NOT NULL DEFAULT 'candidate'
                              CHECK (status IN ('candidate','supported','refuted','disputed')),
    source_news_event_id    uuid REFERENCES news_event(id),
    analysis_run_id         uuid,
    unknowns                jsonb NOT NULL DEFAULT '[]',
    needs_human_review      jsonb NOT NULL DEFAULT '[]',
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_claim_status ON claim (status);
CREATE INDEX ix_claim_subject ON claim (subject_entity_id);

CREATE TABLE claim_evidence (
    claim_id    uuid NOT NULL REFERENCES claim(id),
    evidence_id uuid NOT NULL REFERENCES evidence(id),
    relation    text NOT NULL CHECK (relation IN ('supporting','contradicting')),
    PRIMARY KEY (claim_id, evidence_id, relation)
);
```

### 2.5 关系（正式事实）

```sql
CREATE TABLE relationship (
    id                  uuid PRIMARY KEY,
    source_entity_id    uuid NOT NULL REFERENCES entity(id),
    target_entity_id    uuid NOT NULL REFERENCES entity(id),
    relationship_type   text NOT NULL,
    status              text NOT NULL DEFAULT 'candidate'
                          CHECK (status IN ('candidate','pending_verification','verified',
                                            'disputed','refuted','expired','retracted')),
    confidence          numeric(4,3) NOT NULL DEFAULT 0,
    valid_from          timestamptz,
    valid_to            timestamptz,
    last_verified_at    timestamptz,
    version             int NOT NULL DEFAULT 1,
    derived_from_claim_ids uuid[] NOT NULL DEFAULT '{}',
    attributes          jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_rel_valid_window CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CONSTRAINT ck_rel_no_self CHECK (source_entity_id <> target_entity_id)
);
CREATE UNIQUE INDEX ux_rel_triple ON relationship (source_entity_id, relationship_type, target_entity_id)
    WHERE status NOT IN ('refuted','retracted');
CREATE INDEX ix_rel_status ON relationship (status);
CREATE INDEX ix_rel_target ON relationship (target_entity_id);

CREATE TABLE relationship_evidence (
    relationship_id uuid NOT NULL REFERENCES relationship(id),
    evidence_id     uuid NOT NULL REFERENCES evidence(id),
    weight          numeric(4,3) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (relationship_id, evidence_id)
);

CREATE TABLE relationship_history (
    id              uuid PRIMARY KEY,
    relationship_id uuid NOT NULL REFERENCES relationship(id),
    from_status     text,
    to_status       text NOT NULL,
    actor           text NOT NULL,        -- agent:qa-audit / human:kevin / system:projector
    reason          text,
    evidence_ids    uuid[] NOT NULL DEFAULT '{}',
    snapshot        jsonb NOT NULL,       -- 迁移后的整行快照
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rel_hist ON relationship_history (relationship_id, created_at DESC);
```

> `relationship_history` **只追加**。禁止 UPDATE / DELETE。审计与回滚都基于它。

### 2.6 传导路径

```sql
CREATE TABLE impact_path (
    id                 uuid PRIMARY KEY,
    event_id           uuid NOT NULL REFERENCES news_event(id),
    path_nodes         uuid[] NOT NULL,
    path_relationships uuid[] NOT NULL,
    propagation_depth  int NOT NULL,
    impact_direction   text NOT NULL CHECK (impact_direction IN ('positive','negative','uncertain')),
    impact_horizon     text,           -- short / medium / long
    confidence         numeric(4,3) NOT NULL,
    evidence_count     int NOT NULL DEFAULT 0,
    min_evidence_grade char(1),
    uncertain_factors  jsonb NOT NULL DEFAULT '[]',
    truncated          boolean NOT NULL DEFAULT false,
    algorithm_version  text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_impact_event ON impact_path (event_id);
```

### 2.7 质量与运行

```sql
CREATE TABLE quality_issue (
    id             uuid PRIMARY KEY,
    issue_type     text NOT NULL,        -- rule_id 或类别
    severity       text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    target_table   text NOT NULL,
    target_id      uuid NOT NULL,
    detected_by    text NOT NULL,        -- rule_id
    evidence       jsonb NOT NULL,
    suggested_fix  text,
    status         text NOT NULL DEFAULT 'open',  -- open/acknowledged/resolved/wontfix
    resolved_by    text,
    resolution_note text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz
);
CREATE INDEX ix_qi_status ON quality_issue (status, severity);

CREATE TABLE analysis_run (
    id             uuid PRIMARY KEY,
    news_event_id  uuid NOT NULL REFERENCES news_event(id),
    model_provider text NOT NULL,
    model_name     text NOT NULL,
    prompt_version text NOT NULL,
    input_tokens   int,
    output_tokens  int,
    latency_ms     int,
    status         text NOT NULL,        -- succeeded / parse_error / failed
    error_msg      text,
    output_snapshot jsonb,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE graph_projection_run (
    id            uuid PRIMARY KEY,
    mode          text NOT NULL,         -- full / incremental
    nodes_upserted int NOT NULL DEFAULT 0,
    edges_upserted int NOT NULL DEFAULT 0,
    edges_removed  int NOT NULL DEFAULT 0,
    started_at    timestamptz NOT NULL,
    finished_at   timestamptz,
    status        text NOT NULL
);

CREATE TABLE app_setting (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL
);
-- 初始：expansion.default_depth=3, expansion.max_depth=5,
--       expansion.max_nodes=300, evidence.min_grade_for_verified='C',
--       confidence.isolation_threshold=0.5
```

---

## 三、关键约束与不变量

| # | 不变量 | 落地方式 |
|---|---|---|
| I-1 | 未验证关系不得进入图谱 | 投影器只读 `status IN ('verified','disputed','expired','retracted')` |
| I-2 | `inferred` / `hypothesis` 的 Claim 不可生成 `verified` 关系 | `state_guard.py` 硬校验 + DB 触发器（可选） |
| I-3 | 每条 `verified` 关系至少 1 条 `grade IN (A,B)` 或 ≥2 条独立 C 级证据 | `state_guard.py` |
| I-4 | 关系不物理删除 | 撤销应用权限 + 只允许 `status` 迁移 |
| I-5 | 证据不可变 | `evidence` 表无 UPDATE 路径，修正走 `supersedes_id` |
| I-6 | 同一 `content_hash` 只算 1 条证据 | 证据计数视图 `v_evidence_distinct` |
| I-7 | `valid_to >= valid_from` | CHECK 约束 |

---

## 四、索引与性能预算

| 查询 | 目标 P95 | 手段 |
|---|---|---|
| 按股票代码查公司 | < 20ms | `ux_entity_stock_code` |
| 公司关系列表 | < 50ms | `ix_rel_status` + 覆盖索引 |
| 待核验关系队列 | < 50ms | 部分索引 `WHERE status='pending_verification'` |
| 质量指标聚合 | < 500ms | 物化视图 `mv_quality_metrics`，10 分钟刷新 |
| 事件传导路径读取 | < 100ms | `ix_impact_event` |

---

## 五、待评审项（TASK-003）

1. `claim.predicate` 与 `relationship.relationship_type` 是否共用一套枚举？（当前倾向共用）
2. 实体合并用 `merged_into_id` 软合并，是否需要 `entity_merge_log` 独立审计表？
3. `news_event.dedup_key` 的算法需与 Agent 1 的正文指纹统一，谁来定？（建议 architect 定，data-eng 实现）
4. 是否需要 `relationship` 的时间维度双表（`relationship_version`）而非 history 快照？（当前用 history 快照）
5. `attributes jsonb` 是否会变成「什么都能塞」的垃圾桶？建议每类关系定义白名单 key。
