# DS-05 injected errors

25 个人为植入的错误，用于验证质量规则真的能发现问题。

## 文件格式 `*.json`
```json
{
  "case_id": "INJ-01",
  "description": "A 的供应商写成 B",
  "expected_rule": "REL-001",
  "severity": "high",
  "payload": { }
}
```

## 判据
逐条见 `docs/testing-strategy.md` 第四节。**每条都必须写明期望命中的 rule_id，
否则该用例无法判定通过/失败。**

## 状态
目录已建立，数据待 TASK-413 产出。当前 25 例中 11 例已由 DB 约束/状态机覆盖，
其余依赖 P2/P3 功能。
