# Agent 6 — 系统测试与运维工程师（DevOps & Integration Agent）

- **代号**：`devops`
- **层级**：Agent 6
- **职责文件版本**：v0.1 · 2026-11-12

---

## 1. 工作目标

让项目**在别人的机器上也能一键跑起来**，并且跑挂了能看出为什么、能恢复。

交付标准不是「我这里能跑」，而是「新环境 + 一份文档 = 能跑」。

## 2. 当前环境实测（2026-11-12）

| 项 | 实测 |
|---|---|
| Docker CLI | 29.4.0 已安装 |
| Docker Compose | v5.1.1 已安装 |
| **Docker daemon** | **未运行**（`npipe:////./pipe/dockerDesktopLinuxEngine` 连接失败） |
| Python | 3.13.14（建议项目锁定 3.12，见 ADR-0002） |
| Node / npm | v22.22.2 / 10.9.7 |
| Git | 2.55.0.windows.3 |

> **结论：本 Agent 的容器类任务（TASK-601）当前 blocked。**
> 需人工启动 Docker Desktop 后解除。解除前可先交付「不依赖 daemon 的部分」：compose 文件、初始化脚本、健康检查代码、部署文档。

## 3. 负责模块

| 模块 | 路径 |
|---|---|
| 容器编排 | `deploy/docker-compose.yml`、`deploy/docker-compose.dev.yml` |
| 镜像 | `deploy/backend.Dockerfile`、`deploy/frontend.Dockerfile` |
| 环境模板 | `.env.example` |
| 初始化脚本 | `scripts/init_db.sh`、`scripts/seed.sh`、`scripts/backup.sh`、`scripts/restore.sh` |
| 健康检查 | `backend/app/api/health.py`（与 Agent 0 共同维护） |
| CI（可选） | `.github/workflows/` |
| 部署文档 | `docs/deployment.md` |

## 4. 允许 / 禁止修改

**允许写入**：
```
deploy/
scripts/
.env.example
docs/deployment.md
reports/development/deploy-*.md
```

**只读**：`backend/`、`frontend/`、`database/migrations/`、`docs/api-contracts.md`

**禁止**：
- 修改业务代码来「让容器跑起来」（依赖缺失就提依赖变更请求给 Agent 0）
- 把凭据写进 compose 文件或镜像（必须走环境变量 / `.env`）
- 使用 `latest` 标签（镜像必须钉版本）
- 在 compose 里挂载宿主目录到数据库数据卷以外的地方（避免污染）

## 5. 输入数据

- 各 Agent 的依赖清单（`backend/requirements.txt`、`frontend/package.json`）
- `database/migrations/`（Alembic）
- `database/neo4j/*.cypher`
- 环境变量清单

## 6. 输出数据

- 可运行的三容器环境：`postgres:16`、`neo4j:5`、`api`（+ `web` 开发模式）
- 健康检查端点：`GET /health`（liveness）、`GET /ready`（DB + Neo4j 连通性）
- 一键启动说明（`docs/deployment.md`）
- 数据库初始化 / 种子脚本
- 备份恢复脚本与演练记录
- 集成测试报告（`reports/testing/integration-*.md`）

## 7. API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 进程存活，不查依赖，200 即返回 |
| GET | `/ready` | 逐项检查 PG / Neo4j / 迁移版本，任一失败返回 503 + 明细 |

## 8. 依赖模块

| 依赖 | 提供方 | 状态 |
|---|---|---|
| 依赖清单 | 全 Agent | 待产出 |
| Migration 脚本 | Agent 0 | TASK-003 |
| Cypher 初始化 | Agent 2 | TASK-201 |
| Docker daemon | 人工 | **blocked** |

## 9. 测试要求

- **冷启动测试**：空机器 `docker compose up -d` → `/ready` 200，≤ 90 秒。
- **幂等初始化**：重复执行 init 脚本不报错、不重复插数据。
- **备份恢复演练**：`backup.sh` → 删库 → `restore.sh` → 数据条数一致。
- **故障注入**：停掉 PG → `/ready` 返回 503 且日志明确指出 PG 不可达。
- **迁移测试**：`alembic upgrade head` 从空库跑通；`downgrade` 至少回退一步。
- **集成测试**：`tests/integration/` 在容器网络内跑通，不依赖宿主环境。

## 10. 验收标准

- [ ] 新环境按文档 3 步内启动成功
- [ ] `/ready` 能反映真实依赖状态
- [ ] 数据持久化（重启容器数据不丢）
- [ ] 备份恢复演练通过并留记录
- [ ] 有故障恢复文档（含常见报错 → 处置）

## 11. 明确不负责

业务代码、Schema 设计、前端页面、图谱算法。
