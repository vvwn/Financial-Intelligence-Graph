# Phase 0 架构评审报告 v3（最终提交）

> 提交时间：2026-11-13 18:20 · 提交方：`architect`
> 评审状态：**awaiting_review — 等待独立评审方签署**
> 本轮范围：只做收尾核验，**未新增功能，未进入 Phase 1**
> 结论口径：全文严格区分 **已完成（代码/文档）**、**已验证（有原始输出）**、**因外部原因暂缓**。三者不混用。

---

## 一、本轮四件事

| # | 任务 | 状态 | 证据 |
|---|---|---|---|
| 1 | I-5 / DISPUTED / 证据独立性落地核验 | ✅ **已验证** | `reports/testing/2026-11-13-invariants.log`（19 项 PASS / 0 FAIL） |
| 2 | 取得一次真实 GitHub Actions 成功记录 | ✅ **已验证** | run **#3**（最终提交）`success`，见 `reports/testing/github-actions-evidence.md` |
| 3 | 重建 `fig-api:0.1.1` + 部署 + `/ready` | ✅ **已验证** | `reports/testing/2026-11-13-container-deploy.log` |
| 4 | 更新最终评审报告 | ✅ 本文件 | — |

**本轮没有做的事**：没有新增业务端点、没有写采集器、没有动 Phase 1 任何任务。唯一代码改动是修复下面这个被核验抓出来的缺陷。

---

## 二、本轮抓到的真实缺陷（最重要的一节）

> 核验的价值不在「全绿」，而在它抓到了什么。

### 缺陷：`disputed` 的证据约束是假的

上一版我声称「进入 disputed 必须有反向证据，已由 DB CHECK 强制」：

```sql
CHECK (to_status <> 'disputed' OR array_length(evidence_ids, 1) >= 1)
```

`scripts/verify_invariants.py` 用裸 SQL 插一条空证据的 disputed 记录，**没有报错**。

根因是 PostgreSQL 的 NULL 语义：

| 表达式 | 结果 |
|---|---|
| `array_length('{}'::uuid[], 1)` | **NULL**（不是 0） |
| `NULL >= 1` | NULL |
| CHECK 遇到 NULL | **视为通过** |

所以约束存在、名字正确、`alembic check` 无差异、ORM 测试全绿——**但它从来没生效过**。应用层 `assert_can_dispute` 挡住了，所以测试没暴露；一旦有人写裸 SQL 或换一条代码路径，就绕过去了。

**修复**：迁移 `d91f2b6c4a07`，改用 `cardinality(evidence_ids) >= 1`（空数组返回 0）。

**修复后**：

```
PASS  I-12 空证据进 disputed 被拒    violates check constraint "ck_relationship_history_disputed_requires_evidence"
PASS  I-12 带反向证据进 disputed 允许  allowed as intended
```

**这件事说明什么**：如果只跑 ORM 测试，这个洞会一路带进 Phase 1。用裸 SQL 撞数据库的核验方式，是这轮唯一能发现它的手段。

---

## 三、I-5 证据不可变：19 项核验逐条

核验脚本 `scripts/verify_invariants.py` 直连 PostgreSQL、用裸 SQL、整段事务最后回滚（证据行不可删，只能回滚不能清理）。原始输出：`reports/testing/2026-11-13-invariants.log`。

### 3.1 拒绝非法修改（4 项）

| 检查 | 结果 | 数据库返回 |
|---|---|---|
| 改 `original_excerpt` | PASS | `evidence content is immutable (I-5): insert a new row with supersedes_id` |
| 改 `evidence_grade`（C→A） | PASS | 同上 |
| 改 `source_name` | PASS | 同上 |
| 物理删除 | PASS | `evidence is append-only (I-5): insert a new row with supersedes_id` |

### 3.2 允许合法操作（2 项）

| 检查 | 结果 |
|---|---|
| 改 `verification_status`（复核） | PASS — allowed as intended |
| 追加式修正（同 `origin_key`、时间不早于原行） | PASS — allowed as intended |

### 3.3 追加式修正的边界（2 项）

| 检查 | 结果 | 数据库返回 |
|---|---|---|
| 异源 supersedes | PASS | `supersedes_id must share origin_key (correction of the same report)` |
| 倒序 supersedes（早于原件） | PASS | `superseding evidence cannot predate the row it supersedes` |

### 3.4 历史表只追加（2 项）

| 检查 | 结果 | 数据库返回 |
|---|---|---|
| UPDATE `relationship_history` | PASS | `relationship_history is append-only (I-4)` |
| DELETE `relationship_history` | PASS | 同上 |

（其余为 §四 的 disputed / 独立性 / 阈值项，合计 19 项，全部 PASS。）

---

## 四、DISPUTED 与证据独立性

### 4.1 DISPUTED（裁决 1 的落地核验）

| 要求 | 验证方式 | 结果 |
|---|---|---|
| 仅 `verified → disputed` | `test_pending_review_cannot_become_disputed` | PASS |
| 必须带反向证据 | 裸 SQL 撞 CHECK（见第二节） | PASS（修复后） |
| 双方证据并存 | `test_dispute_preserves_both_sides` 断言 `relation` 集合 = {supporting, contradicting} | PASS |
| 记录 trigger/actor/reason/evidence | 断言 `history.trigger='new_evidence'`、`evidence_ids` 命中 | PASS |
| 不得参与传导 | `assert_usable_for_propagation('disputed')` → `STATE_TRANSITION_INVALID` | PASS |
| 冲突未消解时不得验证 | `test_disputed_cannot_be_verified_while_conflict_stands` | PASS |
| 冲突消解后可恢复 verified | `test_conflict_resolution_allows_verification_again` | PASS |

### 4.2 证据独立性（裁决 3 的落地核验）

| 检查 | 结果 |
|---|---|
| 5 条同 `origin_key` 的 C 级 → 只算 1 个来源，不达标 | PASS（`origins=1, met=False`） |
| 2 条不同 `origin_key` 的 C 级 → 达标 | PASS（`origins=2, met=True`） |
| 阈值只授予 `pending_review`，不自动 verified | PASS |
| 无 `approved_by` 不得 verified | PASS |
| `system:` / `auto:` / `pipeline:` 前缀不得批准 | PASS |
| 人工批准可 verified | PASS |

---

## 五、GitHub Actions 真实记录

工作流 `.github/workflows/ci.yml`，公开仓库，可用 REST API 复核。

| run | commit | 结论 | 失败位置 |
|---|---|---|---|
| #1 | `d6b58ec` | ❌ `failure` | backend / **Tests** |
| #2 | `3f71592` | ✅ `success` | — |
| **#3** | **`46ea361`（最终提交）** | ✅ **`success`**（约 90s） | — |

run #3 / #2 逐步结果（全部 success）：

- **backend**：checkout → uv → Python 3.12 → `uv sync --frozen` → ruff → `alembic upgrade head` → `alembic check` → `apply_neo4j_schema.py` → pytest → 上传测试日志
- **frontend**：checkout → setup-node → `npm ci` → `tsc --noEmit` → `vitest` → `vite build`

**关于 #1 的失败，如实记录**：当时本地 Docker 不可用，那 34 个 DB/Neo4j 测试从未真正跑过。CI 第一次运行就暴露了其中 8 个（2 个测试写错 + 6 个 Neo4j driver 跨事件循环）。修复后 #2 通过。

**这说明流水线有效**——它先于本地发现坏测试，而不是事后补一条「CI 通过」。完整证据：`reports/testing/github-actions-evidence.md`（含两次运行的原始 JSON）。

---

## 六、容器部署与 `/ready`

```
$ docker compose --profile full ps
fig-api       fig-api:0.1.1              Up (healthy)   127.0.0.1:8000->8000/tcp
fig-neo4j     neo4j:5.26-community       Up (healthy)
fig-postgres  postgres:16-alpine         Up (healthy)

$ curl /ready                      # 首次
{"data":{"status":"ready","checks":{
  "postgres":{"ok":true},"neo4j":{"ok":true},
  "migration":{"ok":true,"current":"d91f2b6c4a07","expected":"d91f2b6c4a07"}}}}

$ curl /ready                      # 第二次
... "meta":{"cached":true}

$ docker exec fig-api ... print(expected head)
d91f2b6c4a07
```

镜像 `fig-api:0.1.1`（ID `d9633bb58a85`，494MB）内含迁移 `d91f2b6c4a07`，与库版本一致。

**一处需要说明的行为**：容器刚启动时首次 `/ready` 可能返回 503（`neo4j: TimeoutError`），几秒后转绿。这是**正确行为**——探针本就该在依赖未就绪时拒绝；容器 healthcheck 配了 `start-period=20s`。不是缺陷，也没有做「预热」之类的掩盖。

---

## 七、干净环境可重复部署

| 证据 | 说明 |
|---|---|
| **CI 就是干净环境** | 每次 run 都是全新 Ubuntu runner + 全新 PostgreSQL/Neo4j service 容器，从 `alembic upgrade head` 建库到 100 个测试通过，全自动 |
| 空库迁移 | CI 与本地均从空库 `upgrade head` 一次通过，`alembic check` 无差异 |
| 依赖可复现 | 后端 `uv.lock`、前端 `package-lock.json` 均入库 |
| 镜像可重建 | `deploy/backend.Dockerfile` 构建成功（本轮 3 次构建，2 次因 Hub 502 失败，1 次成功） |

**未做的**：没有在真正的干净物理机/VM 上从零走一遍。CI 是最接近的等价物，但不是同一件事。

---

## 八、三类清单（严格区分）

### A. 已完成（代码或文档已落地）

| 项 | 位置 |
|---|---|
| 契约 v1.1（API / DB / Graph / 测试策略） | `docs/*.md`，状态 `frozen` |
| 状态机 7 态 + 阈值/批准/传导三层判定 | `app/validation/state_guard.py` |
| 关系生命周期（submit/verify/dispute/reject/revoke） | `app/services/relationship_service.py` |
| 排序键（拼音 / 多音字 / 数字 / 大小写） | `app/core/sortkey.py` |
| 投影原语（单关系投影 + 删边，幂等） | `app/graph/projector.py` |
| 3 个迁移 | `bdaf9a0511cb` → `c7d1e4a92f10` → `d91f2b6c4a07` |
| 运维脚本（备份/恢复/演练/回填） | `scripts/*.sh`、`backfill_sort_keys.py` |
| 不变量核验脚本 | `scripts/verify_invariants.py` |
| CI 工作流 | `.github/workflows/ci.yml` |
| 信源清单 + 6 个 fixture 目录规格 | `database/seeds/sources.yaml`、`tests/fixtures/` |

### B. 已验证（有原始输出，可复核）

| 项 | 结果 | 日志 |
|---|---|---|
| 全量测试 | **100 passed / 0 failed** | `reports/testing/2026-11-13-full.log` |
| 不变量核验（裸 SQL） | **19 passed / 0 failed** | `reports/testing/2026-11-13-invariants.log` |
| 迁移执行 + 模型一致性 | 成功；`No new upgrade operations detected` | 本报告 §六 |
| GitHub Actions | run **#3**（最终提交）`success`，11 步 + 7 步全绿 | `github-actions-evidence.md` |
| 容器部署 + `/ready` | 三检全绿，缓存生效 | `2026-11-13-container-deploy.log` |
| 备份恢复演练 | PASSED（含真实数据比对） | `2026-11-13-backup-drill.log` |
| 静态检查 | All checks passed | `2026-11-13-ruff.log` |

### C. 因外部原因暂缓（不是代码缺陷）

| 项 | 外部原因 | 影响 | 可替代证据 |
|---|---|---|---|
| 真正干净物理机/VM 部署 | 无可用干净环境 | 无法声称「换台机器一定能跑」 | CI 全新 runner 是最接近的等价物 |
| Docker Hub 稳定性 | 本轮 3 次构建中 2 次被 `502 Bad Gateway` 阻断 | 镜像重建耗时不稳 | 第 3 次成功；镜像与库版本已核对一致 |

**这两项不计入「已完成」，也不当作代码缺陷。**

上一轮我把「Docker daemon 未启动」也归在此类——那是我误判为环境问题，实际可以手动启动解决；本轮评审方启动后已全部补齐。**这是上一轮的分类错误，在此更正。**

---

## 九、对评审方四条最终标准的自评

| 标准 | 自评 | 依据 |
|---|---|---|
| 能在干净环境重复部署 | **基本达成，有保留** | CI 全自动从空库建到 100 测试通过；但没在独立物理机验过 |
| 能可靠检测错误 | **达成** | 本轮用裸 SQL 抓出一个「测试全绿但约束失效」的缺陷；CI 首跑抓出 8 个坏测试 |
| 能保护证据 | **达成** | I-5 九项核验全过，含改正文/改等级/删除/改来源/倒序 5 类非法操作被数据库拒绝 |
| 出现矛盾时正确停止错误传导 | **达成（机制层）** | disputed 阻断传导、冲突未消解不得验证、`POTENTIAL_*` 永不进图、阈值不自动验证。传导算法本身属 P2，尚未实现 |

---

## 十、状态与申请

```
TASK-007 = review
Phase 0  = awaiting_review
```

申请：**请评审方给出签署结论。** 若为 `APPROVED WITH CONDITIONS`，建议条件写成「独立物理机部署验证（属外部环境项，不计代码缺陷）」。

签署通过后由评审方指示，我才把 Phase 0 置为 `completed`。
