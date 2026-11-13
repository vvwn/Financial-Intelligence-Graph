# Phase 0 架构评审报告 v2（TASK-007 重新提交）

> 提交时间：2026-11-13 08:55 · 提交方：`architect`
> 评审状态：**awaiting_review — 等待独立评审方签署**
> 本版依据：评审方 2026-11-13 正式裁决（DISPUTED 批准 / locale=C 保留 / 阈值语义修正 / I-5 落地）
> **本报告不包含任何自我通过声明。TASK-007 保持 `review`，Phase 0 保持 `awaiting_review`。**

---

## 一、结论摘要

| 项 | 状态 | 证据 |
|---|---|---|
| 五项裁决执行 | ✅ 已实现 | 第二、三节逐条对照 |
| 单元测试（不依赖 DB） | ✅ **62 passed** | `reports/testing/2026-11-13-unit.log` |
| 静态检查 | ✅ All checks passed | `reports/testing/2026-11-13-ruff.log` |
| 全量测试（含 DB/Neo4j） | ⚠️ **66 passed / 34 errors** | `reports/testing/2026-11-13-db-blocked.log` |
| 迁移执行 | ❌ **未执行** | Docker 不可用 |
| 证据不可变测试 | ❌ **已编写未运行** | 9 个用例待 DB |
| 状态转换测试 | 🟡 **单元已过，集成未跑** | 38 个单测通过，14 个集成待 DB |
| 备份恢复演练 | ❌ **未执行** | 脚本已写 |
| CI | ❌ **未在 GitHub 运行** | 工作流文件已写 |

**必须说明**：本轮有 4 项验证因环境问题未执行。它们**不计为通过**，也不计为完成。

---

## 二、裁决 1：DISPUTED 状态（已批准）

| 评审要求 | 实现 | 验证 |
|---|---|---|
| 1. 区分 `pending_review` 与 `disputed` | 语义表：pending_review = 待首次核验；disputed = 已验证后受挑战 | `test_pending_review_cannot_become_disputed` |
| 2. disputed 表示已验证关系受新证据挑战 | 迁移矩阵删除 `pending_review → disputed`；仅 `verified → disputed` | `test_disputed_reachable_from_verified_only` |
| 3. 保留原始支持证据与反向证据 | `relationship_evidence.relation` 进主键，两侧并存 | `test_dispute_preserves_both_sides` |
| 4. 记录历史/原因/证据/操作者 | `relationship_history`：`trigger` + `actor` + `reason` + `evidence_ids` + 全行快照 | 同上（断言 trigger/actor/evidence_ids） |
| 5. disputed 不得参与投资传导 | `assert_usable_for_propagation` 只放行 `verified` | `test_disputed_projects_but_cannot_drive_propagation` |
| 6. 明确合法转换 | 7×7 表更新；disputed → verified / rejected / revoked | `test_disputed_can_return_to_verified_or_be_rejected` |
| 7. 状态转换 + 审计 + 投影测试 | 三类测试齐备 | 见下 |

**新增约束（DB 层）**：

```sql
CHECK (to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1)
```

即「进入 disputed 必须引用至少一条反向证据」——否则「有争议」是空话。

**投影测试**（`test_projector.py`，8 例，待 DB）：verified 投影、candidate 不投影、`POTENTIAL_*` 拒绝、disputed 带自身状态投影、幂等（投影两次只 1 条边）、`evidence_count` 按 origin 去重、删边不影响 PG。

---

## 三、裁决 2-4：locale=C、阈值、I-5

### 3.1 locale=C 保留 + 应用层排序键

| 要求 | 实现 |
|---|---|
| 不修改原始实体名称 | `canonical_name` 不动；新增 `name_sort_key` 独立列 |
| 处理中文/英文/数字/多音字 | `core/sortkey.py`：`pypinyin` 词组级转写（重庆→chongqing、银行→yinhang、行走→xingzou）、ASCII 小写、数字补零 6 位、全角 NFKC 折叠 |
| 排序键独立测试 | `test_sortkey.py` 12 例，**全部通过** |
| 变更可追溯 | `name_sort_key_version` 逐行 + `entity_sort_key_history`（旧键/新键/旧版本/新版本/原因/操作者）+ `scripts/backfill_sort_keys.py`（默认 dry-run） |

样例（实测）：

```
长江电力   → changjiangdianli
重庆银行   → chongqingyinhang     # 多音字按词组
5G通信    → 000005g tongxin       # 数字补零 + 脚本切换分隔
中芯国际-A → zhongxinguoji a
```

### 3.2 阈值语义修正

| 评审要求 | 实现 | 验证 |
|---|---|---|
| 保留 1×A/B 或 2×独立 C | `EvidenceThreshold(required_grades={A,B}, min_c_origins=2, version="v1")` | `test_grade_a_meets_threshold`、`test_two_independent_grade_c_is_enough` |
| 阈值只决定进入核验，不得自动 verified | `evaluate_review_eligibility` → `pending_review`；`evaluate_verification` 额外要求 `approved_by` | `test_threshold_only_grants_review_not_verification` |
| 不同 content_hash ≠ 独立来源 | 计数改为 `COUNT(DISTINCT origin_key)`；`syndicated_from_id` 继承来源 | `test_reposts_of_one_origin_cannot_enter_review` |
| 记录阈值版本/生效时间/修改人/原因 | `app_setting.version` + `app_setting_history`（含 `effective_from`） | 迁移内种子 + 服务层 `set_setting` 强制 `reason` |

**自动化 actor 一律拒绝批准**：`approved_by` 以 `system:` / `auto:` / `pipeline:` 开头直接 422（`test_automated_actor_cannot_approve`）。

### 3.3 I-5 证据不可变

| 评审要求 | 实现 |
|---|---|
| 原始内容不可直接 UPDATE | `trg_evidence_immutable` 比对 11 个受保护列，任一变化即抛异常 |
| 不允许物理删除 | 同触发器，`DELETE` 直接抛异常 |
| 合法修正走新版本/新记录 | 新增行 + `supersedes_id` |
| `supersedes_id` 受控追加 | `trg_evidence_linkage`：必须指向已存在行、`origin_key` 相同、`collected_at` 不早于原行 |
| 触发器或权限实现 | 触发器（DB 层，绕过 ORM 也拦得住） |
| 合法修正 + 非法修改各有测试 | `test_evidence_immutability.py` 9 例（见下） |

**测试清单（已编写，待 DB 运行）**：

| 用例 | 期望 |
|---|---|
| `test_update_excerpt_is_refused` | 抛异常，消息含 immutable |
| `test_update_grade_is_refused` | 抛异常 |
| `test_delete_is_refused` | 抛异常，消息含 append-only |
| `test_cannot_clear_supersedes_link` | 抛异常 |
| `test_verification_status_may_change` | **允许**（复核是合法动作） |
| `test_correction_via_new_row_is_allowed` | 允许，两行共存，新行指向旧行 |
| `test_repost_may_share_origin` | 允许，`syndicated_from_id` 指向首发 |
| `test_supersedes_with_different_origin_is_refused` | 抛异常 |
| `test_superseding_row_cannot_predate_the_original` | 抛异常 |

---

## 四、五条部分修复项的最终处理

| 原编号 | 原问题 | 本轮处理 | 最终状态 |
|---|---|---|---|
| D-04 | 无信源水位表；`seeds/sources.yaml` 空 | `source` 表已在 v1.0 交付；本轮补 `sources.yaml`（6 个信源，含许可状态 `pending`/`blocked`） | ✅ **已修复**（数据接入属 P2） |
| D-14 | `predicate` 无 DB 约束 | 迁移 `c7d1e4a92f10` 增加 `ck_claim_predicate_valid`，取值 = `RelationshipType` 19 个枚举 | ✅ **已修复**（待迁移执行验证） |
| D-18 | 六个 fixture 目录为空 | 六目录 + 格式规格 + 样例已建；实际数据属 TASK-101 / TASK-413 | 🟡 **规格已修复，数据待 P1/P3** |
| D-33 | `locale=C` 中文排序 | 保留 C；新增应用层排序键（ADR-0010）+ 变更审计 | ✅ **已修复** |
| D-35 | `.env` 明文、端口 0.0.0.0 | 端口已绑 `127.0.0.1`；新增 `*_PASSWORD_FILE` 支持（Docker secrets）；生产环境弱密码启动即拒（已实测触发） | ✅ **已修复**（未接 Vault 等外部密钥管理，非 P0 范围） |

---

## 五、其余未完成事项逐条说明（按阶段归类）

| 项 | 阶段归类 | 现状 | 为什么不现在做 |
|---|---|---|---|
| 采集器 / `/news` 等 P2 端点 | **P2 可完成** | 契约已冻结，代码未写 | 属 Phase 2 交付范围，P0 不写业务代码 |
| 增量/全量投影调度 | **P1 可完成** | 本轮交付单关系投影 + 删边原语 | 完整投影器需 TASK-202，依赖图遍历就绪 |
| 规则引擎 13 条 | **P3 可完成** | 阈值参数可调，规则未实现 | 属 Phase 3；且阈值需真实数据校准 |
| fixture 实际数据 | **P1/P3 可完成** | 目录与格式已定 | 需先有 TASK-101 种子公司数据 |
| CI 实际运行 | **P0 交付文件，未验证** | `.github/workflows/ci.yml` 已写 | 需 push 后由 GitHub 执行，本地无法验证 |
| 备份恢复演练 | **P0 交付脚本，未验证** | 三个脚本已写 | 需 Docker 可用 |
| 迁移 `c7d1e4a92f10` 执行 | **P0 必须完成，当前阻塞** | 手写完成，未执行 | Docker 不可用 |
| 34 个 DB/Neo4j 测试 | **P0 必须完成，当前阻塞** | 已编写 | 同上 |

**归类原则**：契约与约束属 P0；业务实现属对应阶段。**没有任何一项被标记为已完成而实际未做。**

---

## 六、测试原始输出

### 6.1 单元测试（不依赖数据库）

```
$ backend/.venv/Scripts/python.exe -m pytest -m "not db and not neo4j"
backend\tests\test_health.py .......                                     [ 11%]
backend\tests\test_sortkey.py ............                               [ 30%]
backend\tests\test_state_guard.py ...................................... [ 91%]
.....                                                                    [100%]

====================== 62 passed, 38 deselected in 8.07s ======================
```

完整日志：`reports/testing/2026-11-13-unit.log`

### 6.2 全量测试（含 DB / Neo4j）—— 失败原因是环境

```
$ backend/.venv/Scripts/python.exe -m pytest
ERROR backend/tests/test_relationship_lifecycle.py::test_dispute_from_pending_review_is_illegal
ERROR backend/tests/test_relationship_lifecycle.py::test_dispute_requires_contradicting_evidence
ERROR backend/tests/test_relationship_lifecycle.py::test_dispute_preserves_both_sides
...
66 passed, 34 errors in 184.99s (0:03:04)
```

34 个 error 全部是连接失败（PostgreSQL 未运行），**不是断言失败**。完整日志：`reports/testing/2026-11-13-db-blocked.log`

### 6.3 静态检查

```
$ backend/.venv/Scripts/python.exe -m ruff check backend/app backend/tests scripts
All checks passed!
```

### 6.4 数据库迁移结果

**未执行。** 迁移 `c7d1e4a92f10` 为手写（autogenerate 无法表达触发器/视图/主键变更），尚未在真实库跑过。
Docker 恢复后必须依次执行并回填本节：

```
alembic upgrade head
alembic check          # 期望：No new upgrade operations detected
```

### 6.5 证据不可变测试结果

**未运行**（9 个用例见 3.3）。Docker 恢复后回填。

### 6.6 状态转换测试结果

- 单元层：38 个用例全部通过（7×7 矩阵、disputed 可达性、阈值语义、独立性、传导准入）
- 集成层：14 个用例待 DB（生命周期、双方证据并存、冲突消解、撤销留痕）

---

## 七、环境阻塞（如实说明）

```
$ docker info
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine

$ cmd /c start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
PROGRAM BLOCKED BY SECURITY POLICY - The sandbox prevented a program on the
configured Program Blacklist from starting:
  - wsl.exe (C:\WINDOWS\System32\wsl.exe)
This block cannot be approved or bypassed from the current command.
```

本机安全策略把 `wsl.exe` 列入黑名单，Docker Desktop 无法由我启动。**需要评审方手动启动 Docker Desktop**，之后可补齐 6.4–6.6 三节。

---

## 八、修改文件清单

### 契约与文档（评审方指定 7 份）

| 文件 | 变更 |
|---|---|
| `docs/technical-decisions.md` | ADR-0007/0008/0009 转 Approved；新增 ADR-0010（排序键）、ADR-0011（证据不可变）；Q-06/07/08 关闭 |
| `docs/api-contracts.md` | v1.0 → **v1.1**：disputed 语义表、迁移矩阵修正、阈值语义、origin_key、证据不可变、端点调整 |
| `docs/database-schema.md` | v1.0 → **v1.1**：disputed 双向约束、排序键、origin_key、两个触发器、I-5/I-11~I-13 |
| `docs/graph-schema.md` | v1.0 → **v1.1**：disputed 投影语义（入图但自证身份、不参与传导） |
| `docs/testing-strategy.md` | v1.0 → **v1.1**：新增 7 类专项测试、判据更新 |
| `reports/development/phase0-architecture-review.md` | 本文件（v2） |
| `docs/task-board.md` | 新增 TASK-009（裁决执行）；后续任务按阶段归类；TASK-007 保持 review |

### 代码

| 文件 | 变更 |
|---|---|
| `backend/app/core/sortkey.py` | 新增：拼音排序键 |
| `backend/app/core/config.py` | 新增 `*_PASSWORD_FILE` 支持；弱密码名单补全 |
| `backend/app/models/{entity,evidence,relationship,claim,ops}.py` | 新增列 / 表 / CHECK |
| `backend/app/validation/state_guard.py` | 重写：矩阵修正、阈值/批准/传导三层判定 |
| `backend/app/services/relationship_service.py` | 重写：`submit_for_review` / `verify` / `dispute` / `transition` |
| `backend/app/services/settings_service.py` | 新增：带审计的配置读写 |
| `backend/app/graph/projector.py` | 新增：单关系投影 + 删边 |
| `database/migrations/versions/c7d1e4a92f10_*.py` | 新增：本轮全部 DB 变更 |
| `backend/tests/{test_sortkey,test_state_guard,test_relationship_lifecycle,test_evidence_immutability,test_projector}.py` | 新增 / 重写 |
| `scripts/{backup,restore,verify_backup}.sh`、`scripts/backfill_sort_keys.py` | 新增 |
| `.github/workflows/ci.yml` | 新增 |
| `database/seeds/sources.yaml`、`tests/fixtures/**` | 新增 |

### Git diff

见 `reports/development/phase0-diff-stat.txt`。

---

## 九、Phase 0 最终验收申请

申请内容：**请评审方就以下范围给出签署结论（APPROVED / APPROVED WITH CONDITIONS / REJECTED）。**

**可以现在评审的部分：**

1. 五项裁决的实现方式是否符合意图（第二、三节）
2. 五条部分修复项的最终处理是否可接受（第四节）
3. 未完成事项的阶段归类是否合理（第五节）
4. 契约 v1.1 的破坏性变更是否可接受

**建议以「有条件通过」处理的部分：**

- 迁移 `c7d1e4a92f10` 未在真实库执行 → 条件：Docker 恢复后执行并回填 6.4
- 34 个 DB/Neo4j 测试未运行 → 条件：回填 6.5、6.6
- CI 未在 GitHub 运行 → 条件：push 后确认首次流水线结果

**我不申请的：** 把上述三项标记为已完成。

**当前状态（不会被自行修改）：**

```
TASK-007 = review
Phase 0  = awaiting_review
```
