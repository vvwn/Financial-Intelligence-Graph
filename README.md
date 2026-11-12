# Financial Intelligence Graph (FIG)

面向中国 A 股市场的 AI 金融情报、动态产业知识图谱与事件传导分析平台。

> 本仓库当前处于 **Phase 0（架构设计与可行性验证）**。
> 未通过 Phase 0 评审前，不进入大规模代码开发。

## 项目最高原则

**系统能否准确识别一条重要事件的产业影响，找到真实关联的上市公司，提供可靠证据，并在发现错误时及时修正。**

不是收集了多少新闻、建了多少节点。

## 三条不可妥协的红线

1. **Claim / Evidence / Verified Relationship 逻辑分离** —— 模型输出只能进 Claim，永远不能直接写成已验证关系。
2. **PostgreSQL 是事实源，Neo4j 是派生投影** —— 图谱可随时从 PG 重建；任何写图都必须经过同一条受控投影管道。
3. **关系只允许状态迁移，不允许物理删除** —— 已验证关系的撤销必须留痕，并触发下游影响重算。

## 快速导航

| 文档 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | 多智能体协作章程、目录归属矩阵、任务协议 |
| [docs/architecture.md](docs/architecture.md) | 总体架构图、数据流图、部署拓扑 |
| [docs/agent-responsibilities.md](docs/agent-responsibilities.md) | 七个 Agent 职责总表与边界 |
| [docs/api-contracts.md](docs/api-contracts.md) | 统一 API 规范 v0.1 |
| [docs/task-dependencies.md](docs/task-dependencies.md) | 任务依赖图、任务清单、并行波次 |
| [docs/database-schema.md](docs/database-schema.md) | PostgreSQL 数据结构（草案） |
| [docs/graph-schema.md](docs/graph-schema.md) | Neo4j 节点/关系 Schema（草案） |
| [docs/project-status.md](docs/project-status.md) | 当前阶段、阻塞、风险 |
| [docs/task-board.md](docs/task-board.md) | 任务看板（唯一任务真源） |
| [docs/technical-decisions.md](docs/technical-decisions.md) | 技术决策记录（ADR 索引） |
| [docs/testing-strategy.md](docs/testing-strategy.md) | 测试体系与错误注入方案 |
| [docs/development-roadmap.md](docs/development-roadmap.md) | Phase 0–5 里程碑与验收标准 |

## 技术栈（已实测，2026-11-12）

后端 Python **3.12.12** + FastAPI 0.162 + Pydantic 2.14 + SQLAlchemy 2.1 + Alembic 1.20（uv 管理依赖）；
业务库 PostgreSQL 16（容器）；图库 Neo4j 5.26；前端 React 18 + TypeScript 5.7 + Vite 6 + Cytoscape.js；
调度 APScheduler；部署 Docker Compose；AI 经统一模型适配层调用。

## 目录结构

```
docs/          规范与文档（唯一权威来源）
backend/app/   模块化单体后端
frontend/src/  React 工作台
database/      Migration、种子数据、Cypher 初始化
integrations/  LLM 适配层、OpenClaw 对接
tests/         跨模块集成与验收测试
deploy/        Docker Compose 与环境配置
reports/       开发/测试/质量报告
```

## 本地起步

```bash
cp .env.example .env                                  # 1. 填写两个数据库密码
docker compose -f deploy/docker-compose.yml --env-file .env up -d   # 2. PG + Neo4j

cd backend && uv sync && uv run uvicorn app.main:app --reload       # 3. 后端 :8000
cd frontend && npm install && npm run dev                           # 4. 前端 :5173
```

验证：`curl localhost:8000/ready` 返回 200 且 `postgres` / `neo4j` 均 `ok`。
详细步骤与排错见 [docs/deployment.md](docs/deployment.md)。
