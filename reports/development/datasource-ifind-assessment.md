# 同花顺 iFinD MCP 可用性评估

> 调查时间：2026-11-13 23:40–00:10 · 调查方：`architect`
> Token：已存入 `.env` 的 `IFIND_MCP_TOKEN`（**未入库、未写进代码**，已用 `git grep` 确认）
> **结论：能用，而且这是目前唯一一个有供应链结构的数据源。**

---

## 一、接入方式（实测）

用户给的是网页地址 `mcp.51ifind.com`，那是文档站 + 控制台，**不是 MCP 端点**。
真实端点藏在官方 SKILL 包的 `scripts/call.py` 里：

```
BASE = https://api-mcp.51ifind.com:8643/ds-mcp-servers
```

十个服务分列：

| 服务 | 路径 |
|---|---|
| A股 | `/hexin-ifind-ds-stock-mcp` |
| 基金 | `/hexin-ifind-ds-fund-mcp` |
| 宏观行业 | `/hexin-ifind-ds-edb-mcp` |
| 新闻公告 | `/hexin-ifind-ds-news-mcp` |
| 债券 | `/hexin-ifind-ds-bond-mcp` |
| 港美股 | `/hexin-ifind-ds-global-stock-mcp` |
| 指数板块 | `/hexin-ifind-ds-index-mcp` |
| 期货期权 | `/hexin-ifind-ds-futures-mcp` |
| **快查企业** | `/kuaicha-enterprise-mcp` |
| 法律 | `/hexin-law-mcp` |

协议是 **MCP Streamable HTTP**：

```
POST <path>
Authorization: <token>          # 裸值，不加 Bearer
Content-Type: application/json
Accept: application/json, text/event-stream

1) initialize           → 响应头返回 mcp-session-id
2) notifications/initialized（带 mcp-session-id）
3) tools/list / tools/call
```

实测握手成功，返回 `protocolVersion: 2025-03-26`。

---

## 二、工具清单（实测）

### A股（10 个）
`get_stock_summary` / `search_stocks`（自然语言选股）/ `get_stock_performance`（日频行情+技术指标）/
`get_stock_info` / `get_stock_shareholders`（股本与股东）/ `get_stock_financials`（报表+财务指标）/
`get_risk_indicators`（alpha/beta/波动率/夏普/VaR）/ `get_stock_events`（IPO/再融资等）/
`get_esg_data` / `stock_highfreq_quotes`

### 快查企业（2 个元工具）
- `kuaicha_tool_discover`：**中文能力描述 → 检索匹配的数据接口**（传「企业股东信息」这类描述，不是用户原句）
- `kuaicha_tool_call`：按 `tool_id` + 参数执行

discover 出来的能力里，**有关键的三件**：

| tool_id | 能力 |
|---|---|
| `filter_get_industry_chain_tree_structure` | 产业链树层级结构（6 层，含 node_code） |
| `filter_get_industry_chain_atlas` | **产业链图谱：上游 / 下游 / 替代 / 互补 / 包含** |
| `filter_get_industry_chain_enterprise_list` | 生产链-企业列表（某节点的企业） |

---

## 三、关键突破：产业链图谱实测

调 `filter_get_industry_chain_atlas`，传 `node_code=23992`（光模块）：

```json
{
  "node_name": "光模块", "node_code": "23992",
  "up_stream":   [{"value": "原材料", "list": [
      {"node_code": "23976", "node_name": "光组件"},
      {"node_code": "23979", "node_name": "光通信器件"}]}],
  "down_stream": [{"value": "产品/业务", "list": [
      {"node_code": "33176", "node_name": "光通信设备"}]}],
  "replace_stream": [{"value": "替代", "list": [
      {"node_code": "26560", "node_name": "无线通信模组"},
      {"node_code": "29792", "node_name": "电力线载波通信模组"}]}],
  "contains_stream": [...]
}
```

树结构接口返回 430KB 的完整层级（6 层，node_code + node_name + sub_node），可以直接遍历。

**这意味着什么**：这是六个数据源里**第一个真正给出「谁在谁上游/下游」的**。
配合 `filter_get_industry_chain_enterprise_list`（某节点的企业列表），可以拼出：

```
公司A → 所属节点 → 上游节点 → 公司B
```

---

## 四、但必须说清楚它的性质

**这是产业节点级的上下游，不是公司级的披露关系。**

- 「光模块的上游是光通信器件」是**产业知识**，不是「中际旭创向天孚通信采购」这种事实
- 从「A 属于光模块」「B 属于光通信器件」推到「A 从 B 采购」，是**推断**，不是证据

按本项目的规则（ADR-0007 + 状态机），这类关系：

- 只能进**候选层**（`claim_type = inferred`，状态 `candidate` / `pending_review`）
- **不能自动 verified**，必须人工核验
- 置信度上限 0.6（`CONFIDENCE_CAPS` 已强制）

**这恰好是候选层设计的用途**：AI 推断进候选，人工核验后才提升。所以这个源非常契合，
但绝不能拿它直接生成"已验证的供应链关系"。

---

## 五、与其它六个源的对比

| 源 | 公司基础 | 行业分类 | 主营构成 | 股权/子公司 | 实控人 | 主题归属 | **产业链上下游** | 具名客户/供应商 |
|---|---|---|---|---|---|---|---|---|
| Baostock | ✅ | 证监会 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Tushare | ✅ | 申万 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 巨潮年报 | ✅ | 证监会 | ✅ | ✅ | 控股股东 | ❌ | ❌ | 🟡 匿名 |
| 巨潮关联交易公告 | — | — | — | — | — | — | ❌ | ✅ 限关联方 |
| 东方财富 | ✅ | 东财板块 | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ |
| gsxt | 工商 | — | — | 股东/对外投资 | ✅ | — | ❌ | ❌ |
| **iFinD MCP** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **✅ 产业节点级** | ❌ |

**iFinD 是目前覆盖最广的一个**，尤其补上了产业链上下游这个空白。

---

## 六、接入建议

### 6.1 优先级
**建议接入，但按「推断源」处理**，不能当事实源。

### 6.2 怎么接
两条路：

| 方式 | 优点 | 缺点 |
|---|---|---|
| A. 配成 WorkBuddy 的 MCP 连接器 | 零代码，我直接就能调 | 只在本会话可用，不能进采集流水线 |
| B. 写 `app/collectors/ifind_collector.py` | 可批量、可定时、可入库 | 要自己维护 MCP 客户端（约 100 行） |

**建议 B**：因为要进流水线、要落库、要有审计。协议已经摸清了（三步握手 + session id）。

### 6.3 落地顺序
1. 先跑通「光模块」一条链：树 → 节点 → atlas → 企业列表，把节点和企业落库
2. 生成 `inferred` 的候选关系（公司 → 上下游公司），全部 `candidate`
3. 人工核验一小批，确认推断质量
4. 再扩到全部 15 个细分产业

### 6.4 注意
- **token 等同账号权限**，官方文档明确警告不要外传。已只存 `.env`
- 有调用配额（`个人中心 -> 用量`），批量跑前先看额度
- 接口偶发 502 / 不返回 session id，需要重试逻辑（实测踩到 2 次）

---

## 七、结论

| 问题 | 回答 |
|---|---|
| 能拿到数据吗 | ✅ 能，token 有效，握手与工具调用都成功 |
| 有供应链关系吗 | ✅ **有，产业节点级的上下游/替代/互补/包含** |
| 能直接当事实用吗 | ❌ **不能**，是推断，必须进候选层 |
| 值得接入吗 | ✅ **值得**，这是目前唯一补上「上下游」的源 |

**一句话**：它给了我们一条真实的产业链骨架，但骨架到公司级关系之间还隔着一次推断，
那次推断必须由人（或严格规则）来背书，不能由代码自动升格为事实。
