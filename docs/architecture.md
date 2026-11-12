# 总体架构设计（FIG）

> 版本 v0.1 · 2026-11-12 · 状态：**待 Phase 0 评审**
> 维护者：`architect` ｜ 会签：`graph-eng`、`qa-audit`

---

## 一、架构形态：模块化单体 + 单一受控写图管道

**不做微服务。** 初期用模块化单体（Modular Monolith）：一个 FastAPI 进程，内部按职责分包，包间只经服务层接口调用。

理由：
1. 团队是 AI Agent，跨进程调试成本远高于跨包调用。
2. 图谱一致性需要事务边界——微服务会把一致性变成分布式事务问题。
3. 后续真要拆，包边界清晰就够拆；反之现在拆了也合不回来。

**唯一例外**：Neo4j 与 PostgreSQL 是独立进程（数据库），必须处理双写一致性——见第四节。

---

## 二、总体架构图

```mermaid
graph TB
    subgraph EXT["外部世界"]
        SRC1["交易所公告<br/>上交所/深交所"]
        SRC2["监管与官方<br/>央行/证监会/统计局"]
        SRC3["权威媒体<br/>RSS / 公开页"]
        LLM["大模型服务<br/>多 provider"]
    end

    subgraph ING["采集层 · collectors"]
        AD["SourceAdapter<br/>每个源一个适配器"]
        NM["normalize / dedup<br/>标准化 + 指纹去重"]
    end

    subgraph APP["应用层 · FastAPI (backend/app)"]
        API["api/<br/>路由 · 鉴权 · 参数校验"]
        SVC["services/<br/>业务编排"]
        AGT["agents/<br/>理解 · 抽取 · 传导"]
        GRP["graph/<br/>投影 · 遍历 · 路径"]
        VAL["validation/<br/>规则 · 状态守卫 · 指标"]
        TSK["tasks/<br/>APScheduler 定时任务"]
    end

    subgraph AI["模型适配层 · integrations/llm"]
        LLMC["LLMClient 协议<br/>provider 无关"]
    end

    subgraph DATA["数据层"]
        PG[("PostgreSQL 16<br/>★ 事实源 SoR")]
        NEO[("Neo4j 5<br/>派生投影（可重建）")]
    end

    subgraph UI["前端 · frontend"]
        WEB["React + TS + Vite<br/>Cytoscape.js 工作台"]
    end

    subgraph OPS["运维"]
        DC["Docker Compose"]
        OBS["健康检查 / 日志 / 备份"]
    end

    SRC1 --> AD
    SRC2 --> AD
    SRC3 --> AD
    AD --> NM --> PG
    PG --> SVC
    SVC --> AGT
    AGT --> LLMC --> LLM
    AGT -->|"写 Claim（candidate）"| PG
    SVC --> VAL
    VAL -->|"状态迁移<br/>verified / disputed / retracted"| PG
    PG -->|"GraphProjector<br/>唯一写图通道"| NEO
    NEO --> GRP --> SVC
    SVC --> API --> WEB
    TSK --> SVC
    DC -.-> APP
    DC -.-> PG
    DC -.-> NEO
    OBS -.-> APP
```

**读图要点**：注意 `PG → Neo4j` 那一条单向箭头。**没有任何其他箭头指向 Neo4j。** 这是本架构最重要的一条线。

---

## 三、核心架构决策

### ADR-0001：PostgreSQL 是唯一事实源，Neo4j 是派生投影

| | 内容 |
|---|---|
| **决策** | 所有实体、关系、证据、状态、审计历史只写 PG。Neo4j 由 `GraphProjector` 从 PG 单向投影，可随时清空重建。 |
| **理由** | ① 避免双写不一致；② 图可重建 = 可修复 = 可回滚；③ 满足「禁止多个 Agent 同时写正式图谱」；④ 关系历史与状态机在关系型库更好表达。 |
| **代价** | 图查询前需保证投影新鲜（秒级延迟可接受）；投影器成为单点，需监控。 |
| **替代方案** | 以 Neo4j 为主库（否决：历史版本、复杂约束、审计查询弱）；双主（否决：一致性不可控）。 |

### ADR-0002：Python 版本锁定 3.12

当前机器为 3.13.14。部分 C 扩展（如某些 async 驱动、科学计算轮子）在 3.13 上轮子覆盖不全，容器内统一用 3.12-slim。本地开发建议 pyenv 装 3.12。

### ADR-0003：Claim / Evidence / Verified Relationship 三层分离

```
Evidence（证据，不可变）
   ↑ 引用
Claim（主张，可被支持/反驳，状态：candidate / supported / refuted / disputed）
   ↓ 通过状态守卫 + 规则校验后才可生成
VerifiedRelationship（正式关系，进入图谱）
```

- Claim **不能** 直接变成 VerifiedRelationship——必须经过 `state_guard` 的合法性校验 + 至少一条达标证据。
- Claim 与 Relationship 是**两张表**，不是一张表的两个状态。原因：一条关系可能由多个 Claim 支撑，一个 Claim 可能拆成多条关系。
- 详见 [database-schema.md](database-schema.md) 与 [graph-schema.md](graph-schema.md)。

### ADR-0004：LLM 只能通过 `LLMClient` 协议访问

业务代码禁止 `import openai`。所有模型调用走 `integrations/llm/base.py` 定义的协议，支持 provider 切换、录制回放（测试用）、token 计量。

### ADR-0005：任务调度用 APScheduler，不引 Prefect（初期）

单进程 + 定时采集 + 定时投影 + 定时质量扫描，APScheduler 足够。任务规模上来（>50 个 DAG 依赖）再评估 Prefect。**先别为未来的规模付现在的复杂度。**

---

## 四、数据流：一条新闻的完整旅程

```mermaid
sequenceDiagram
    autonumber
    participant SRC as 外部信源
    participant COL as collectors
    participant PG as PostgreSQL
    participant AGT as agents（LLM）
    participant VAL as validation
    participant PRJ as GraphProjector
    participant NEO as Neo4j
    participant API as api
    participant WEB as 前端

    SRC->>COL: 拉取（RSS / 公告 / 公开页）
    COL->>COL: normalize + dedup（raw_hash / 正文指纹）
    COL->>PG: 写 news_raw（原文快照）+ news_event（unverified）
    Note over PG: 去重命中则挂 duplicate_of，不新建 event

    AGT->>PG: 读 news_event
    AGT->>AGT: 事件分类 → 实体识别 → 链接已有实体
    AGT->>AGT: 抽取关系候选（Claim）+ 绑定证据引用
    AGT->>PG: 写 claim（status=candidate, claim_type=fact_reported/inferred/...）
    Note over AGT,PG: 无证据的 Claim 只能是 hypothesis，confidence ≤ 0.3

    VAL->>PG: 规则扫描（EVD-001 无证据 / EVD-003 D级标verified / DUP-001 重复实体 ...）
    VAL->>PG: state_guard 判定是否允许 candidate → verified
    alt 证据达标
        VAL->>PG: relationship.status = verified（留 history 记录）
        PRJ->>PG: 增量拉取 verified/disputed/expired 关系
        PRJ->>NEO: MERGE 节点与关系（幂等，带 status/confidence/evidence_count）
    else 证据不足
        VAL->>PG: 保持 pending_verification 或退回 candidate
        Note over NEO: 不入图。图谱里查不到未验证关系。
    end

    WEB->>API: GET /graph/neighbors?node_id=...&depth=2
    API->>NEO: Cypher 遍历（限深/限点）
    NEO-->>API: 节点 + 关系 + 每条边的 evidence_id
    API->>PG: 补全实体详情与证据摘要
    API-->>WEB: 统一响应信封（含 truncated 标记）
```

**关键约束（在代码里必须成立）**：

1. 未验证关系**永不出现在**任何图查询结果中。
2. 每条边必须能返回至少一个 `evidence_id`；若历史数据缺失，返回 `evidence_missing: true` 而不是编造。
3. 投影是幂等的：同一份 PG 数据投影 N 次，图状态一致。
4. 一条关系的状态变化必须写 `relationship_history`，禁止原地覆盖。

---

## 五、事件传导的扩展边界

```mermaid
graph LR
    E["事件<br/>AI数据中心资本开支↑"] --> I1["数据中心"]
    I1 --> I2["服务器"]
    I2 --> I3["GPU / AI芯片"]
    I2 --> I4["光模块"]
    I4 --> I5["光通信设备"]
    I1 --> I6["液冷"]
    I1 --> I7["电源设备"]
    I3 --> C1["A股公司（直接）"]
    I4 --> C2["A股公司（直接）"]
    I6 --> C3["A股公司（间接）"]

    classDef d1 fill:#1b3a2f,stroke:#3ddc97,color:#e6f4ef
    classDef d2 fill:#1f2f45,stroke:#5aa9e6,color:#e8f1fa
    classDef d3 fill:#3a2f1b,stroke:#e6b95a,color:#faf3e3
    class E d1
    class I1,I2,I3,I4,I5,I6,I7 d2
    class C1,C2,C3 d3
```

**约束（必须落到代码与配置）**：

| 参数 | 默认 | 上限 | 可配置 |
|---|---|---|---|
| 扩展深度 | 3 | 5 | 系统设置 |
| 单次节点上限 | 300 | 2000 | 系统设置 |
| 最低证据质量 | C | — | 系统设置 |
| 低置信隔离阈值 | 0.5 | — | 系统设置 |

每条路径必须输出：起始事件、路径节点、路径关系、影响方向（正/负/不确定）、影响周期、证据数量与质量分布、置信度、关键不确定因素。
**禁止把多个模型的置信度简单累加**——评分规则统一在 `validation/scoring.py`，且同一新闻的多家转载按 1 条独立证据计。

---

## 六、部署拓扑

```mermaid
graph TB
    subgraph HOST["开发机 / 服务器"]
        subgraph NET["docker network: fig-net"]
            W["web<br/>vite dev :5173 / nginx :80"]
            A["api<br/>uvicorn :8000"]
            P[("postgres:16<br/>:5432  volume: pgdata")]
            N[("neo4j:5<br/>:7474/:7687  volume: neo4jdata")]
        end
        ENV[".env（不入库）"]
        BK["scripts/backup.sh<br/>pg_dump + neo4j-admin dump"]
    end
    W -->|"/api/v1"| A
    A --> P
    A --> N
    ENV -.-> A
    BK -.-> P
    BK -.-> N
```

健康检查：`GET /health`（存活）｜`GET /ready`（PG + Neo4j + 迁移版本，任一失败 503）。
**当前状态：Docker daemon 未运行，容器拓扑尚未实测**（见 project-status.md 风险 R-01）。

---

## 七、模块依赖方向（单向，禁止反向）

```
api → services → { collectors, agents, graph, validation } → models / schemas
tasks → services
integrations/llm ← agents（只允许 agents 调用）
```

**禁止**：
- `models` / `schemas` 依赖任何业务包（它们是最底层）。
- `collectors` 依赖 `graph` 或 `agents`（采集层不认识产业关系）。
- `agents` 直接调 `graph.repository`（必须经 `services`，保证规则统一）。
- 任何包绕过 `services` 直接写 `relationship` 表。

---

## 八、技术选型与风险

| 选型 | 版本 | 风险 | 缓解 |
|---|---|---|---|
| FastAPI | ≥0.115 | 低 | — |
| SQLAlchemy | 2.0（async） | 中：async session 生命周期易错 | 统一 `core/db.py` 提供 session 依赖 |
| Alembic | ≥1.13 | 低 | Migration 只由 architect 生成 |
| PostgreSQL | 16 | 低 | — |
| Neo4j | 5.x Community | 中：Community 无集群、内存受限 | 单机够用；投影可重建降低风险 |
| Cytoscape.js | 3.x | 中：万级节点性能 | 首屏 ≤300 节点 + 聚合展开 |
| APScheduler | 3.x | 中：多进程会重复执行 | 单 worker 部署，或加 DB 锁 |
| Python 3.13（现机） | — | **高：轮子覆盖** | 锁 3.12（ADR-0002） |
| Docker daemon | 未运行 | **阻塞** | 人工启动（R-01） |

---

## 九、Phase 0 待评审问题

1. 该架构是否合理？（模块化单体 + 单一投影管道）
2. 哪些技术有兼容性/实现风险？（Python 3.13、Neo4j Community、Cytoscape 性能）
3. 哪些可并行？——见 [task-dependencies.md](task-dependencies.md) 波次划分
4. 哪些必须串行？——Schema 冻结 → Migration → 投影器 → 采集入库
5. 最容易卡壳？——实体消歧、证据达标判定、投影一致性
6. 如何降低协作冲突？——目录归属矩阵 + 契约先冻结 + 单一写图管道
7. 如何验证 AI 生成的产业关系？——Claim/Evidence/Verified 三层 + 规则引擎 + 错误注入测试
8. 如何避免错误向下游扩散？——状态守卫 + 撤销触发重算 + 下游影响清单
9. 如何保证可追溯？——evidence 不可变 + relationship_history + 每次投影留 run_id
10. 如何控制初期成本？——不拆微服务、不引 Prefect、先单产业（AI 算力）50–100 家公司
