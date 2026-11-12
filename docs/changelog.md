# 变更日志

格式参考 Keep a Changelog。版本号与项目阶段对应。

---

## [0.1.0] — 2026-11-12 · Phase 0 启动

### 新增

- 项目骨架：`backend/ frontend/ database/ integrations/ tests/ deploy/ reports/ docs/`
- `README.md`：项目定位、三条红线、文档导航
- `AGENTS.md` v0.1：团队编制、**环境能力实测结论**、目录归属矩阵、10 条协作硬规则、任务协议、交付协议
- `docs/agents/`：7 份 Agent 职责文件（Agent 0–6），含允许/禁止修改目录、输入输出、API、依赖、测试、验收
- `docs/agent-responsibilities.md`：职责总表、6 个交接点、禁止越权清单、分阶段启用计划
- `docs/architecture.md` v0.1：总体架构图、新闻端到端数据流、事件传导边界、部署拓扑、模块依赖方向、技术风险表
- `docs/api-contracts.md` v0.1：统一响应信封、14 个错误码、封闭枚举集合、关系状态机 + 合法迁移表、约 40 个端点、幂等与重试、契约变更流程
- `docs/database-schema.md` v0.1：18 张表 DDL、7 条不变量、索引性能预算
- `docs/graph-schema.md` v0.1：16 类节点标签、16 种关系类型、约束与索引、投影规则、字段映射表
- `docs/task-dependencies.md` v0.1：任务依赖图（30 任务、无环）、10 个并行波次、关键路径、阻塞清单
- `docs/task-board.md`：10 个任务的完整 YAML 任务单
- `docs/project-status.md`：阶段进度、环境实测、风险 R-01~R-10、技术债 D-01~D-05
- `docs/agent-status.md`：角色状态与派发记录
- `docs/technical-decisions.md`：ADR-0001~0006、5 个待决问题
- `docs/testing-strategy.md` v0.1：12 类测试归属、6 个固定数据集、25 例错误注入清单、性能基线
- `docs/development-roadmap.md` v0.1：P0–P5 里程碑与验收标准

### 决策

- ADR-0001 PostgreSQL 为唯一事实源，Neo4j 为派生投影
- ADR-0002 Python 锁定 3.12
- ADR-0003 Claim / Evidence / VerifiedRelationship 三层分离
- ADR-0004 LLM 只能经 `LLMClient` 协议访问
- ADR-0005 初期用 APScheduler，不引 Prefect
- ADR-0006 模块化单体，不做微服务

### 已知阻塞

- B-01 Docker daemon 未运行 → TASK-601 / TASK-602 blocked

### 说明

本版本**无业务代码**。Phase 0 评审通过前不写业务代码，这是设计约束，不是进度问题。

---

## 版本号规则

| 版本 | 含义 |
|---|---|
| 0.x.0 | Phase 0 期间迭代 |
| 1.0.0 | Phase 1 验收通过（图谱底座可用） |
| 2.0.0 | Phase 2 验收通过（自动扩展可用） |
| 3.0.0 | Phase 3 验收通过（质量闭环） |
| 4.0.0 | Phase 4 验收通过（Web 可用） |
| 5.0.0 | Phase 5 验收通过（投资研究可用） |
