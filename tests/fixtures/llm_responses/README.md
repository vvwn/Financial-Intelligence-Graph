# DS-06 llm replay

录制的模型响应，用于离线测试 Agent pipeline（CI 不联网）。

## 文件格式 `*.json`
```json
{
  "request_hash": "sha256:...",
  "model": "recorded-model",
  "prompt_version": "v1",
  "response": { "event": {}, "entities": [], "claims": [], "unknowns": [] },
  "expect": { "parse_ok": true }
}
```

## 必含样本
5 条畸形输出：缺 `claims` 字段、枚举值非法、JSON 截断、中文字段名、空 `unknowns` 但含 inferred claim。

## 状态
目录已建立，数据待 TASK-301/302 产出。
