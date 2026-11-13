# DS-03 evidence

A/B/C/D 四级各 10 条，含 5 组冲突证据，用于证据阈值与 disputed 测试。

## 文件格式 `*.json`
```json
{
  "evidence_grade": "A",
  "source_type": "announcement",
  "source_name": "巨潮资讯",
  "source_url": "https://example.com/e1",
  "original_excerpt": "原文摘录，禁止改写",
  "content_hash": "sha256:...",
  "origin_key": "origin-abc",
  "supersedes": null,
  "syndicated_from": null,
  "expected": { "independent_of": ["origin-def"] }
}
```

## 判据要点
- 同 `origin_key` 的多条证据只算 1 个独立来源（不同 content_hash 也不算独立）
- 冲突组必须能触发 `disputed`，且双方证据都保留

## 状态
目录已建立，数据待 TASK-413 产出。
