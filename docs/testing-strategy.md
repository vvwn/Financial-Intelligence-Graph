# 测试策略

> 版本 **v1.1** · 2026-11-13 · 状态：**frozen**
> 维护者：`qa-audit` ｜ 会签：`architect`
> 原则：**测试是验收的唯一证据。没有测试输出的「完成」不算完成。**

---

## 一、测试根与运行方式（已修正）

**上一版的缺陷**：`backend/pyproject.toml` 里 `testpaths = ["tests"]` 是相对 `backend/` 解析的，仓库根目录的 `tests/{fixtures,acceptance,integration}` 永远不会被收集。

**现在**：配置移到仓库根 `pyproject.toml`：

```toml
[tool.pytest.ini_options]
testpaths = ["backend/tests", "tests"]
asyncio_mode = "auto"
pythonpath = ["backend"]
markers = ["db: requires a live PostgreSQL"]
```

运行（从仓库根）：

```bash
backend/.venv/Scripts/python.exe -m pytest              # 全部
backend/.venv/Scripts/python.exe -m pytest -m "not db"  # 不依赖数据库
backend/.venv/Scripts/python.exe -m pytest -m db        # 仅集成测试
```

---

## 二、12 类测试的归属与判据

| # | 类型 | 负责 | 工具 | 通过判据 | 当前状态 |
|---|---|---|---|---|---|
| 1 | 单元测试 | 各模块 | pytest | 核心模块覆盖率 ≥ 80% | 🟡 状态机/守卫已覆盖 |
| 2 | API 测试 | architect + qa | pytest + httpx | 每端点 1 正常 + 1 异常；错误码与契约一致 | 🟡 系统端点已覆盖 |
| 3 | 数据库测试 | architect | pytest + 真实 PG | 约束可被触发；迁移 upgrade/downgrade 通过 | ✅ 含不可变/生命周期用例 |
| 4 | 图谱查询测试 | graph-eng | pytest + Neo4j | 限深/限点生效；无环爆炸；状态过滤正确 | ⚪ 待 TASK-203 |
| 5 | Agent 输出 Schema | industry-ai | pytest + Pydantic | 畸形输出 100% 被拦截 | ⚪ 待 TASK-302 |
| 6 | 关系扩展测试 | graph-eng + ai | pytest | 深度超限报错；`truncated` 正确 | ⚪ 待 TASK-204 |
| 7 | 数据一致性 | qa-audit | pytest | PG 应入图数 == 图中数；重建前后相等 | ⚪ 待 TASK-202 |
| 8 | 错误检测 | qa-audit | pytest + 注入集 | 25 例检出率 ≥ 80%，误报 ≤ 20% | ⚪ 待 TASK-411 |
| 9 | 前端交互 | frontend | Vitest | 关键路径可点通；`tsc --noEmit` 零错误 | ✅ 2 passed + tsc 通过 |
| 10 | Docker 部署 | devops | shell + compose | 冷启动 ≤ 90s；`/ready` 200 | ✅ 已实测 |
| 11 | 备份恢复 | devops | shell | 备份→删库→恢复→条数一致 | ⚪ 未做 |
| 12 | 端到端集成 | qa + devops | pytest | 一条新闻 → 图谱可查 → 证据可见 | ⚪ 待 P2 |

---

## 三、固定测试数据集（规格）

| 数据集 | 位置 | 内容 | 用途 |
|---|---|---|---|
| `DS-01 companies` | `tests/fixtures/companies/` | 30 家 A 股公司，含 3 组易混（同名不同公司、母子公司、曾用名） | 实体消歧 |
| `DS-02 news` | `tests/fixtures/news/` | 50 条新闻，含 10 组同文转载、5 条弱相关、3 条纯传闻 | 去重/理解/防扩散 |
| `DS-03 evidence` | `tests/fixtures/evidence/` | A/B/C/D 各 10 条，含 5 组冲突证据 | 证据达标判定 |
| `DS-04 graph` | `tests/fixtures/graph/` | 200 节点 / 500 关系，含 1 条 5 跳链、1 个环、1 条断链 | 遍历与路径 |
| `DS-05 injected_errors` | `tests/fixtures/injected_errors/` | 25 个人为错误（见第四节） | 错误检测 |
| `DS-06 llm_replay` | `tests/fixtures/llm_responses/` | 录制的模型响应，含 5 条畸形输出 | 离线测 Agent |

**数据集版本化**：改动必须写 commit message 说明原因，并重跑基线。

**当前状态**：六个目录均为空。测试数据由 TASK-101 / TASK-413 产出。

---

## 四、错误注入清单（25 例，判据已全部定义）

> 上一版有 6 例「无法判定通过/失败」，因为阈值未定义。现在每个阈值都有落点。

| # | 注入错误 | 期望命中 | 判据（可执行） | 状态 |
|---|---|---|---|---|
| 1 | A 的供应商写成 B | REL-001 | 检测器返回 issue 且 `target_id` 命中该关系 | 待实现 |
| 2 | 客户关系无公告支撑 | REL-003 / EVD-001 | 关系的 `evidence_count = 0` | 待实现 |
| 3 | 同一公司两条实体（代码相同） | DUP-001 | 已由 `ux_entity_type_stock_code` 阻止写入 → 断言 IntegrityError | ✅ 由 DB 约束覆盖 |
| 4 | 同一公司两条实体（简称相同、代码不同） | DUP-002 | 归一化名相同且代码不同 → 检测器命中 | 待实现 |
| 5 | 已终止合作仍标 verified | TMP-002 | `valid_to < now()` 且 `status='verified'` | 待实现 |
| 6 | 子公司归属写反 | REL-002 | 控股关系成环检测 | 待实现 |
| 7 | 控股关系成环 A→B→C→A | REL-002 | 图遍历检测到环 | 待实现 |
| 8 | 关系无 evidence | EVD-001 | `evidence_count = 0` | 待实现 |
| 9 | 5 家媒体转载算 5 条证据 | EVD-002 | `v_evidence_distinct` 计为 1 → 断言提升被拒 | ✅ `test_reposts_do_not_count_twice` |
| 10 | D 级证据支撑 verified | EVD-003 | 提升时 `best_grade=D` → 422 | ✅ `test_single_grade_c_is_not_enough` |
| 11 | `valid_to < valid_from` | TMP-001 | DB CHECK `ck_relationship_valid_window` | ✅ 由约束覆盖 |
| 12 | verified 直接改回 candidate | STA-001 | `assert_transition_allowed` 抛 409 | ✅ `test_verified_cannot_go_back_to_candidate` |
| 13 | 传导深度 6 跳未报错 | PRP-001 | `depth=6` → 400 `DEPTH_LIMIT_EXCEEDED` | 待实现（端点） |
| 14 | 路径含 0.2 置信边却标「高置信」 | PRP-002 | **判据**：存在边 `confidence < 0.5`（`app_setting.impact.low_confidence_edge_threshold`）且 `path.confidence > 0.8` 且路径未标 `low_confidence` → 命中 | 待实现 |
| 15 | `inferred` Claim 被提升为 verified | STA-001 | 422 `CLAIM_TYPE_NOT_PROMOTABLE` | ✅ `test_inferred_claim_blocked_at_service_layer` |
| 16 | 一条新闻扩出 500 节点无截断 | PRP-001 | **判据修正**：原写「200 节点」与 `max_nodes=300` 自相矛盾。改为 500 节点、`max_nodes=300` → `truncated` 必须为 true | 待实现 |
| 17 | 影响方向写反 | 人工标注集 | **判据**：DS-02 中 5 条已人工标注方向的新闻，系统输出方向必须一致，允许 `uncertain` 但不允许反向 | 待实现 |
| 18 | 同一三元组重复插入 | I-8 | 部分唯一索引 → IntegrityError | ✅ `test_duplicate_active_triple_rejected` |
| 19 | 实体自环 | I-7 | DB CHECK `ck_relationship_no_self_loop` | ✅ `test_self_loop_rejected` |
| 20 | 股票代码格式非法 | VALIDATION_ERROR | `ck_entity_stock_code_format` 要求 6 位数字 | ✅ 由约束覆盖 |
| 21 | 新闻发布时间为未来 3 天 | 时间校验 | **判据**：超过 `app_setting.impact.future_time_tolerance_minutes`（默认 5 分钟）即标记异常 | 待实现 |
| 22 | `confidence = 1.5` | CHECK | `ck_relationship_confidence_range` | ✅ `test_confidence_above_one_rejected` |
| 23 | 撤销关系后下游未重算 | 重算缺失 | **判据**：撤销后相关 `impact_path.status` 必须变为 `invalidated`（列已存在） | 待实现（TASK-415） |
| 24 | 图中出现 candidate 关系 | I-1 | `assert_projectable` 抛错；投影器准入过滤 | ✅ `test_unverified_statuses_never_project` |
| 25 | 模型输出缺 `claims` 字段 | Schema 校验 | Pydantic 拦截，记 `parse_error` | 待实现（TASK-302） |

**当前可判定**：13/25 已有自动化覆盖（多为 DB 约束与状态机）；12/25 依赖尚未实现的功能（P2/P3）。

### 新增专项测试（本轮裁决要求）

| 类别 | 文件 | 覆盖 |
|---|---|---|
| 状态转换 | `test_state_guard.py` | 7×7 矩阵、`pending_review → disputed` 非法、`disputed` 仅从 verified 进入 |
| 阈值语义 | `test_state_guard.py`、`test_relationship_lifecycle.py` | 阈值只授予 pending_review；无 `approved_by` 不得 verified；自动化 actor 拒绝 |
| 独立性 | 同上 | 同 `origin_key` 多行只算 1 个来源 |
| 审计 | `test_relationship_lifecycle.py` | `trigger` / `actor` / `reason` / `evidence_ids` 落库；双方证据并存 |
| 图谱投影 | `test_projector.py` | candidate 不投影、POTENTIAL_* 拒绝、disputed 带状态投影、幂等、`evidence_count` 按 origin 去重 |
| 证据不可变 | `test_evidence_immutability.py` | 改正文/删除被拒；改 `verification_status` 允许；`supersedes_id` 追加合法、异源与倒序被拒 |
| 排序键 | `test_sortkey.py` | 拼音、多音字（重庆/银行）、大小写、数字补零、全角折叠、确定性 |

**特别测试（Phase 3 硬门禁）**：撤销 #6 或 #10 的关系后，系统必须
① 列出受影响 `impact_path`；② 重算；③ 输出前后 diff；④ 不成立的路径标 `invalidated`。

---

## 五、反幻觉测试（专项，部分已实现）

| 测试 | 断言 | 状态 |
|---|---|---|
| 弱相关新闻 | 扩展节点数 ≤ `max_nodes`，`truncated` 正确 | 待 P2 |
| 无证据 | Claim 必须 `hypothesis` 且 `confidence ≤ 0.3` | ✅ DB CHECK |
| 强行提升 | `inferred` → 422 | ✅ |
| 冲突证据 | 进 `disputed` 而非 `verified`，双方证据都保留 | ✅ `test_contradicting_evidence_forces_disputed` |
| 空 `unknowns` | 有 `inferred` Claim 却 `unknowns=[]` 判为异常 | 待 P2 |
| 无 Claim 的关系 | 不得 verified | ✅ `test_no_claim_means_no_verification` |

---

## 六、性能基线

| 场景 | 规模 | 目标 | 状态 |
|---|---|---|---|
| `neighbors(depth=2)` | 10 万关系 | P95 < 300ms | 未测 |
| `neighbors(depth=3)` | 10 万关系 | P95 < 1s | 未测 |
| 公司关系列表 | 单公司 200 关系 | P95 < 50ms | 未测 |
| 全量投影 | 10 万关系 | < 5 分钟 | 未测 |
| 质量全量扫描 | 10 万关系 | < 3 分钟 | 未测 |
| 单条新闻分析 | — | < 20s，token 记录 | 未测 |
| `alembic upgrade head` | 25 表 | < 10s | ✅ 实测约 2s |

---

## 七、测试报告模板

```markdown
# 测试报告 TASK-xxx / phase-N

- 执行时间 / 环境（Python、PG、Neo4j、commit）
- 数据集版本

## 汇总
| 项 | 数 |
|---|---|
| 总数 / 通过 / 失败 / 跳过 | |

## 失败明细
| # | 用例 | 期望 | 实际 | 原因 | 归属 |

## 未解决问题
（必须写，没有就写"无"）

## 与上次基线对比
```

**禁止**只写「全部通过」而不贴实际输出。

---

## 八、已知未做

| 项 | 原因 |
|---|---|
| 覆盖率门禁 | 未接入 CI，覆盖率只本地可见 |
| 前端交互测试 | 仅 2 个渲染用例，图谱交互未测 |
| 备份恢复演练 | 脚本未写 |
| 性能基线 | 数据量不足，P2 后才有意义 |
