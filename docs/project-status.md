# 项目状态

> 最后更新：2026-11-12 22:40 · 维护者：`architect`
> **状态语义严格区分**：未开始 / 已写代码 / 已运行 / 测试通过 / 已合并 / 已部署 / 已验证实际数据。
> 禁止把「写了代码」说成「做完了」。

---

## 一、当前阶段

**Phase 0 — 架构设计与可行性验证**（进行中，约 60%）

| 交付物 | 状态 | 备注 |
|---|---|---|
| architecture.md | ✅ 已写 | 含架构图、数据流、部署拓扑、ADR-0001~0005 |
| agent-responsibilities.md + 7 份职责文件 | ✅ 已写 | 含目录归属矩阵 |
| api-contracts.md | 🟡 draft | 端点/信封/错误码/枚举/状态机已定义，待冻结 |
| database-schema.md | 🟡 draft | 核心表 DDL 已写，5 个待评审项未决 |
| graph-schema.md | 🟡 draft | 标签/关系/投影规则已写，5 个待评审项未决 |
| task-dependencies.md | ✅ 已写 | 依赖图无环，10 个并行波次 |
| testing-strategy.md | 🟡 draft | 12 类测试已归类，固定数据集规格待定 |
| development-roadmap.md | ✅ 已写 | P0–P5 里程碑 |
| 架构评审报告 | ⚪ 未开始 | TASK-007，Phase 0 门禁 |
| 代码 | ⚪ 未开始 | **Phase 0 评审通过前不写业务代码** |

---

## 二、环境事实（2026-11-12 实测）

| 组件 | 状态 | 说明 |
|---|---|---|
| Python | ✅ 3.13.14 | 建议项目锁 3.12（ADR-0002），未验证 3.12 是否已装 |
| Node / npm | ✅ 22.22.2 / 10.9.7 | — |
| Docker CLI | ✅ 29.4.0 | — |
| Docker Compose | ✅ v5.1.1 | — |
| **Docker daemon** | 🔴 **未运行** | `npipe:////./pipe/dockerDesktopLinuxEngine` 不可达 |
| Git | ✅ 2.55.0 | 仓库已初始化，远端 `github.com/vvwn/Financial-Intelligence-Graph` |
| PostgreSQL | ⚪ 未验证 | 依赖容器，随 daemon 一起阻塞 |
| Neo4j | ⚪ 未验证 | 同上 |

---

## 三、已完成

| 项 | 证据 |
|---|---|
| 项目目录骨架 | `backend/ frontend/ database/ integrations/ tests/ deploy/ reports/ docs/` 已建 |
| 协作章程 | `AGENTS.md` v0.1 |
| 7 个 Agent 职责文件 | `docs/agents/agent-0..6` |
| 架构设计 | `docs/architecture.md` v0.1（含 4 张 mermaid 图） |
| 接口规范 | `docs/api-contracts.md` v0.1 |
| 任务依赖图 | `docs/task-dependencies.md` v0.1（30 个任务、10 波次） |
| Git 仓库初始化 | 首次提交已推送 |

**注意：以上全部是文档，零业务代码。** 这是 Phase 0 的应有状态，不是进度落后。

---

## 四、正在进行

| 任务 | 负责人 | 当前动作 |
|---|---|---|
| TASK-003 PG Schema 冻结 | architect | 5 个待评审项待决策（见 database-schema.md 第五节） |

---

## 五、阻塞

| # | 阻塞 | 影响 | 解除条件 |
|---|---|---|---|
| B-01 | Docker daemon 未运行 | TASK-601/602 及全部容器验证 | 人工启动 Docker Desktop |
| B-04 | 实体消歧标准未定 | TASK-101/302/401 | architect + qa-audit 会签规则 |

---

## 六、风险清单

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R-01 | Docker daemon 长期不可用，容器化验证缺失 | 中 | 高 | 先做本地 PG/Neo4j 直装验证，不阻塞设计 |
| R-02 | Python 3.13 依赖轮子不全 | 中 | 中 | 锁 3.12，容器内验证 |
| R-03 | 实体消歧不准 → 关系挂错公司 | 高 | **严重** | 别名表 + 股票代码强约束 + qa-audit DUP 规则 + 人工复核队列 |
| R-04 | LLM 把推断写成事实 | 高 | **严重** | claim_type 硬约束 + state_guard + 反幻觉测试 |
| R-05 | 投影器与 PG 不一致 | 中 | 高 | 幂等测试 + 每周一致性校验 + 全量重建能力 |
| R-06 | Neo4j Community 内存限制，大图遍历超时 | 中 | 中 | 限深限点 + 首屏聚合 |
| R-07 | 数据源许可/频控不清，采集违规 | 中 | 中 | 只接官方/许可源，频控配置化 |
| R-08 | 证据质量判定阈值拍脑袋 | 高 | 中 | 用 TASK-101 种子数据校准，不预设数字 |
| R-09 | 任务粒度过大，Agent 交付不可验收 | 中 | 中 | 每任务必须有可执行验收命令 |
| R-10 | 多 Agent 同时改同一文件 | 中 | 中 | 目录归属矩阵 + 串行守门 |

---

## 七、技术债务（已知，先记账不还）

| # | 债务 | 何时还 |
|---|---|---|
| D-01 | 无鉴权（P0–P3 单用户） | P4 引入 Bearer token |
| D-02 | 无 CI（本地手动跑测试） | P2 前补 GitHub Actions |
| D-03 | 图谱时态查询 `as_of` 未实现 | P4 或按需 |
| D-04 | 质量指标用实时聚合而非物化视图 | 数据量 > 10 万关系时改 |
| D-05 | 无分布式锁，APScheduler 单进程假设 | 多实例部署前必须解决 |

---

## 八、下一步（按顺序）

1. 决策 TASK-003 的 5 个待评审项 → Schema 冻结
2. TASK-004 图 Schema 冻结（会签 graph-eng）
3. TASK-005 API 契约冻结 + OpenAPI 骨架
4. TASK-006 测试策略冻结
5. TASK-007 出架构评审报告 → **等用户评审通过**
6. 评审通过后才进入 Phase 1
