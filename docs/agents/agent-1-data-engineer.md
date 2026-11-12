# Agent 1 — 金融数据采集工程师（Data Engineer）

- **代号**：`data-eng`
- **层级**：Agent 1
- **职责文件版本**：v0.1 · 2026-11-12

---

## 1. 工作目标

把外部世界的原始信息，**可追溯、可去重、可重放**地变成结构化的 `NewsRaw` → `NewsEvent`。
不判断产业关系，不判断新闻真伪——只保证「我拿到了什么、从哪拿的、什么时候拿的」。

## 2. 负责模块

| 模块 | 路径 |
|---|---|
| 数据源适配层 | `backend/app/collectors/`（每个源一个 adapter，统一接口） |
| 采集编排 | `backend/app/collectors/runner.py` |
| 清洗与去重 | `backend/app/collectors/normalize.py`、`dedup.py` |
| 入库服务 | `backend/app/services/ingest_service.py` |
| 采集调度任务 | `backend/app/tasks/collect_jobs.py`（注册到主架构师的调度器） |
| 数据源配置 | `database/seeds/sources.yaml` |

## 3. 允许 / 禁止修改

**允许写入**：
```
backend/app/collectors/
backend/app/services/ingest_service.py
backend/app/tasks/collect_jobs.py
backend/tests/test_collectors*.py
database/seeds/sources.yaml
reports/development/
```

**只读**：`backend/app/models/`、`backend/app/schemas/`、`docs/api-contracts.md`

**禁止**：
- 修改 `database/migrations/`（改表需求走 Migration 请求）
- 写入任何图谱相关代码或 Cypher
- 在采集层做产业关系判断、实体合并、情感/影响分析
- 直接写 Neo4j

## 4. 输入数据

| 输入 | 形式 |
|---|---|
| 数据源清单 | `database/seeds/sources.yaml`（名称、类型、URL、许可、频率、优先级） |
| 原始响应 | HTML / JSON / RSS / PDF |
| 模型约束 | `docs/database-schema.md` 中 `news_raw` / `news_event` 定义 |

**首批信源（P1 范围）**：上交所/深交所公告、证监会、中国人民银行、国家统计局、新华社/证券时报等权威媒体 RSS。
**硬约束**：只用官方 API、公开公告页、明确许可的 RSS；遵守 robots 与频控；不抓付费墙内容。

## 5. 输出数据

- `news_raw`：原始标题、正文、HTML 快照、source、source_url、published_at、collected_at、`raw_hash`
- `news_event`：标准化后的事件记录，含 `event_type`、`verification_status=unverified`、去重指纹 `dedup_key`
- `collect_run`：每次采集的统计（成功/失败/新增/重复/耗时）
- `dead_letter`：失败条目 + 错误类型 + 重试次数

## 6. API 接口

对外暴露（供 Agent 3 与前端消费，路由由主架构师在 `api/` 中挂载）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/ingest/run` | 触发一次采集（支持 `source_ids`、`since`） |
| GET | `/api/v1/ingest/runs/{run_id}` | 采集运行结果 |
| GET | `/api/v1/news` | 分页查询新闻（`since`、`source`、`event_type`） |
| GET | `/api/v1/news/{id}` | 单条详情 + 原文快照 |

内部契约（Python 层）：
```python
class SourceAdapter(Protocol):
    source_id: str
    async def fetch(self, since: datetime | None) -> AsyncIterator[RawItem]: ...
```
`RawItem` 必须包含 `title, content, url, published_at, fetched_at, raw_html_or_json`。

## 7. 依赖模块

| 依赖 | 提供方 | 状态 |
|---|---|---|
| `news_raw` / `news_event` 表结构 | Agent 0 | 待冻结 TASK-003 |
| 去重键规则 | Agent 0 + Agent 4 会签 | 待定 |
| 调度器注册点 | Agent 0 | 待冻结 |
| 离线 fixture 数据 | Agent 4 | TASK-402 |

## 8. 测试要求

- **去重**：同 URL 重复采集、转载同文不同 URL（正文指纹）两类用例。
- **时间解析**：时区、缺发布时间、未来时间异常值。
- **失败处理**：HTTP 429/5xx、结构变更（选择器失效）→ 进 dead_letter，不抛穿整批。
- **离线可跑**：全部测试基于 `tests/fixtures/news/`，CI 不联网。
- **幂等**：同一 `run` 重放两次，`news_event` 数量不变。

## 9. 验收标准

- [ ] 3 个以上真实信源跑通，连续 3 天无未处理异常
- [ ] 同一新闻转载 N 次只入库 1 条 `news_event`，其余记 `news_raw` 并挂 `duplicate_of`
- [ ] 每条记录可回放到原始 URL 与原始快照
- [ ] 采集失败率与原因可见（`collect_run` + `dead_letter`）
- [ ] 单测覆盖率 ≥ 80%，全部离线通过

## 10. 明确不负责

产业关系判断、正式图谱审批、前端页面、实体消歧的最终裁定（只提供候选）。
