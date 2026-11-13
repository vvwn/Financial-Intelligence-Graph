# DS-04 graph

200 节点 / 500 关系，含 1 条 5 跳链、1 个环、1 条断链，用于遍历与路径测试。

## 文件格式
- `nodes.json`：`[{ "uid": "...", "entity_type": "listed_company", "name": "..." }]`
- `edges.json`：`[{ "rid": "...", "source": "...", "target": "...", "type": "supplies_to", "status": "verified" }]`

## 必含结构
| 结构 | 用途 |
|---|---|
| 5 跳链 | 验证 `depth=5` 可达、`depth=6` 报错 |
| 环 A→B→C→A | 验证遍历不死循环 |
| 断链（悬空 rid） | 验证投影一致性校验能发现 |

## 状态
目录已建立，数据待 TASK-202 产出。
