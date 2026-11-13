# GitHub Actions 真实运行记录

> 仓库：`github.com/vvwn/Financial-Intelligence-Graph`（公开）
> 工作流：`.github/workflows/ci.yml`
> 采集时间：2026-11-13T18:30+08:00
> 数据来源：GitHub REST API（`/actions/runs`、`/actions/runs/{id}/jobs`），原始 JSON 见同目录

---

## 一、最终提交的成功记录（验收证据）

| 项 | 值 |
|---|---|
| run number | **#3** |
| run id | `43408295452` |
| commit | `46ea361` — verify(phase0): 收尾核验 — 裸 SQL 撞出 disputed CHECK 失效并 |
| 结论 | **`success`** |
| 开始 / 结束 | 2026-11-13T10:19:44Z → 2026-11-13T10:20:59Z（约 90s） |
| 页面 | https://github.com/vvwn/Financial-Intelligence-Graph/actions/runs/43408295452 |

### 逐步结果（全部 success）


**[backend]** → `success`

| # | step | conclusion |
|---|---|---|
| 1 | Set up job | `success` |
| 2 | Initialize containers | `success` |
| 3 | Run actions/checkout@v4 | `success` |
| 4 | Install uv | `success` |
| 5 | Install Python 3.12 | `success` |
| 6 | Sync dependencies | `success` |
| 7 | Lint | `success` |
| 8 | Apply migrations | `success` |
| 9 | Verify models match the database | `success` |
| 10 | Apply Neo4j schema | `success` |
| 11 | Tests | `success` |
| 12 | Upload test log | `success` |
| 22 | Post Install uv | `success` |
| 23 | Post Run actions/checkout@v4 | `success` |
| 24 | Stop containers | `success` |
| 25 | Complete job | `success` |

**[frontend]** → `success`

| # | step | conclusion |
|---|---|---|
| 1 | Set up job | `success` |
| 2 | Run actions/checkout@v4 | `success` |
| 3 | Run actions/setup-node@v4 | `success` |
| 4 | Install | `success` |
| 5 | Typecheck | `success` |
| 6 | Unit tests | `success` |
| 7 | Build | `success` |
| 13 | Post Run actions/setup-node@v4 | `success` |
| 14 | Post Run actions/checkout@v4 | `success` |
| 15 | Complete job | `success` |

---

## 二、前一次成功记录（上一提交，含完整的迁移与测试链）

| 项 | 值 |
|---|---|
| run number | #2 |
| run id | `43343426657` |
| commit | `3f71592` |
| 结论 | `success` |
| 页面 | https://github.com/vvwn/Financial-Intelligence-Graph/actions/runs/43343426657 |

---

## 三、首次失败记录（如实保留，不删除）

| 项 | 值 |
|---|---|
| run number | #1 |
| run id | `43339585863` |
| commit | `d6b58ec` |
| 结论 | `failure` |
| 失败步骤 | **backend / Tests** |
| 页面 | https://github.com/vvwn/Financial-Intelligence-Graph/actions/runs/43339585863 |


**[frontend]** → `success`

| # | step | conclusion |
|---|---|---|
| 1 | Set up job | `success` |
| 2 | Run actions/checkout@v4 | `success` |
| 3 | Run actions/setup-node@v4 | `success` |
| 4 | Install | `success` |
| 5 | Typecheck | `success` |
| 6 | Unit tests | `success` |
| 7 | Build | `success` |
| 13 | Post Run actions/setup-node@v4 | `success` |
| 14 | Post Run actions/checkout@v4 | `success` |
| 15 | Complete job | `success` |

**[backend]** → `failure`

| # | step | conclusion |
|---|---|---|
| 1 | Set up job | `success` |
| 2 | Initialize containers | `success` |
| 3 | Run actions/checkout@v4 | `success` |
| 4 | Install uv | `success` |
| 5 | Install Python 3.12 | `success` |
| 6 | Sync dependencies | `success` |
| 7 | Lint | `success` |
| 8 | Apply migrations | `success` |
| 9 | Verify models match the database | `success` |
| 10 | Apply Neo4j schema | `success` |
| 11 | Tests | `failure` |
| 12 | Upload test log | `success` |
| 22 | Post Install uv | `skipped` |
| 23 | Post Run actions/checkout@v4 | `success` |
| 24 | Stop containers | `success` |
| 25 | Complete job | `success` |

**失败原因**：当时本地 Docker 不可用，那 34 个 DB/Neo4j 测试从未真正跑过；CI 第一次跑就暴露了其中 8 个
（2 个测试写错 + 6 个 Neo4j driver 跨事件循环）。修复后 run #2、#3 连续通过。

**这说明流水线有效**：它先于本地发现了坏测试，而不是事后补一条「CI 通过」。

---

## 四、复现命令

```bash
# 本地等价序列（CI 执行的就是这些）
backend/.venv/bin/python -m ruff check backend/app backend/tests scripts
cd backend && .venv/bin/python -m alembic upgrade head && .venv/bin/python -m alembic check
cd .. && backend/.venv/bin/python scripts/apply_neo4j_schema.py
backend/.venv/bin/python -m pytest -q
cd frontend && npm ci && npm run typecheck && npm test && npm run build
```

## 五、附：依赖机器人运行

同仓库另有 Dependabot 的 `npm_and_yarn` / `Graph Update` 工作流，与本项目 CI 无关，未计入本节证据。
