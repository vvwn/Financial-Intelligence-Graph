# 本地开发环境搭建

> 版本 v0.1 · 2026-11-12 · 维护者：`devops` ｜ 会签：`architect`
> 目标：新机器按本文 5 步内跑起来。

---

## 前置要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.12.x** | 3.13 部分 C 扩展轮子不全（ADR-0002）。用 `uv python install 3.12` 或 pyenv |
| uv | ≥ 0.5 | 包管理与虚拟环境 |
| Node.js | ≥ 20（实测 22.22.2） | 前端 |
| Docker Desktop | 已启动 | **必须确认 daemon 在跑**：`docker info` 能返回 ServerVersion |
| Git | ≥ 2.40 | — |

---

## 第 1 步 · 克隆与配置

```bash
git clone https://github.com/vvwn/Financial-Intelligence-Graph.git
cd Financial-Intelligence-Graph
cp .env.example .env
```

编辑 `.env`，至少改这两个密码，且保持 `DATABASE_URL` 与 `POSTGRES_PASSWORD` 一致：

```ini
POSTGRES_PASSWORD=你的密码
DATABASE_URL=postgresql+asyncpg://fig:你的密码@localhost:5432/fig
NEO4J_PASSWORD=你的密码
```

---

## 第 2 步 · 启动数据库

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d
docker compose -f deploy/docker-compose.yml ps
```

期望：`fig-postgres` 与 `fig-neo4j` 都是 `healthy`。

- PostgreSQL: `localhost:5432`，库/用户均为 `fig`
- Neo4j Browser: http://localhost:7474 （用户 `neo4j`，密码见 `.env`）
- Bolt: `localhost:7687`

数据在具名卷 `fig_fig_pgdata` / `fig_fig_neo4jdata` 中，`down` 不会丢；`down -v` 会**删除数据**。

---

## 第 3 步 · 后端

```bash
cd backend
uv sync                      # 创建 .venv 并安装依赖（含 dev）
uv run alembic upgrade head  # 建表（当前尚无 revision，待 TASK-111）
uv run uvicorn app.main:app --reload --port 8000
```

验证：

```bash
curl http://localhost:8000/health   # 200 {"data":{"status":"ok",...}}
curl http://localhost:8000/ready    # 200 表示 PG 与 Neo4j 都通；503 会列出哪个挂了
```

接口文档：http://localhost:8000/docs

---

## 第 4 步 · 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Vite 已配置 `/api` 代理到 `localhost:8000`，无需处理 CORS。

---

## 第 5 步 · 跑测试

```bash
# 后端
cd backend && uv run pytest

# 前端
cd frontend && npm test && npm run typecheck
```

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `failed to connect to the docker API at npipe:...` | Docker Desktop 未启动 | 启动 Docker Desktop，等托盘图标变绿 |
| `/ready` 返回 503 且 `postgres.ok=false` | 容器没起或密码不一致 | `docker compose ps`；核对 `.env` 与 `DATABASE_URL` |
| `/ready` 返回 503 且 `neo4j.ok=false` | Neo4j 还在启动（首次约 30–60s） | 等一会儿再试；`docker logs fig-neo4j` |
| `uv sync` 报找不到 3.12 | 本机无 3.12 | `uv python install 3.12` |
| 端口被占用 | 本机已有 PG/Neo4j | 改 `.env` 的 `POSTGRES_PORT`，或停掉本机服务 |
| 中文乱码 | 终端编码 | PG 容器已强制 UTF8；Windows 终端设 `chcp 65001` |

---

## 目录与配置的对应关系

```
.env                       ← 唯一配置来源（gitignored）
backend/pyproject.toml     ← 后端依赖真源（uv sync）
backend/.python-version    ← 锁 3.12
backend/alembic.ini        ← 迁移配置，DSN 运行时注入，不写死
database/migrations/       ← Alembic 脚本目录
deploy/docker-compose.yml  ← PG + Neo4j
frontend/vite.config.ts    ← /api 代理
```

---

## 已验证的基线（2026-11-12 实测）

| 项 | 实测结果 |
|---|---|
| `docker compose up -d` | PG + Neo4j 均 `healthy`（Neo4j 首次约 20–30s） |
| `curl /health` | 200，返回统一信封，`x-request-id` 为 UUIDv7 |
| `curl /ready` | 200，`postgres.ok=true`、`neo4j.ok=true` |
| 数据持久化 | 写临时表 → `compose restart` → 数据仍在 |
| Neo4j 图 Schema | 4 约束 / 15 索引（含默认），`scripts/apply_neo4j_schema.py` 可重复执行 |
| 后端测试 | `pytest` 5 passed |
| 前端 | `vitest` 2 passed；`tsc --noEmit` 零错误；`vite build` 185 KB（61 KB gzip） |

---

## 尚未完成（不谎报）

- 容器化的 api / web 服务镜像（`deploy/backend.Dockerfile`）未做，当前 api 跑在宿主机
- 备份 / 恢复脚本（`scripts/backup.sh`）未做
- CI（GitHub Actions）未接
- Alembic 尚无 revision（等 TASK-003 冻结 + TASK-111）
