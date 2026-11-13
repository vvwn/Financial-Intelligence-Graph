# DS-01 companies

30 家 A 股公司，含 3 组易混样本，用于实体消歧测试。

## 文件格式 `*.json`
```json
{
  "stock_code": "300001",
  "canonical_name": "示例科技股份有限公司",
  "aliases": ["示例科技", "示例科技股份"],
  "former_names": ["旧名科技"],
  "industry_code": "AI-COMPUTE-OPTICAL",
  "entity_type": "listed_company"
}
```

## 必含的易混组
1. 同名不同公司（简称相同、代码不同）
2. 母子公司（母公司控股子公司，两者都有股票代码）
3. 曾用名（改名前后同属一家公司）

## 状态
目录已建立，数据待 TASK-101 产出。**当前为空是已知未完成项。**
