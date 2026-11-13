# DS-02 news

50 条新闻，用于去重、事件理解与「防过度扩散」测试。

## 文件格式 `*.json`
```json
{
  "source_key": "sse_announcement",
  "url": "https://example.com/a",
  "title": "关于签订重大合同的公告",
  "content": "……",
  "published_at": "2026-11-10T00:00:00Z",
  "origin_key": "origin-abc",
  "syndicated_from": null,
  "expected": {
    "event_type": "contract",
    "is_repost_of": null
  }
}
```

## 必含样本
- 10 组同文转载（同 `origin_key`，不同 `url`）
- 5 条与 AI 算力产业链弱相关
- 3 条纯市场传闻（不得产生 verified 关系）

## 状态
目录已建立，数据待 TASK-101 / TASK-413 产出。
