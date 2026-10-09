# MCP 集成说明

本项目只使用麦当劳 MCP Server 的**两个只读工具**，不调用任何会改动账户、
产生消费或消耗额度的接口。

## 接入信息

| 项 | 值 |
|---|---|
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer <token>` |
| 限流 | 每 Token 每分钟 600 次，超限返回 429 |
| 协议版本上限 | MCP Version 2025-06-18 |

配置示例见 `mcp-config.example.json`，其中 Token 为环境变量占位符，
不含任何真实凭据。

## 使用的工具

### 1. list-nutrition-foods（餐品营养信息列表）

**入参**：无。调用一次返回全量 160 条记录（158 个唯一名称）。

**返回格式不是标准 JSON**，而是 TOON（Token-Oriented Object Notation）紧凑格式，
官方说明是为降低 LLM token 消耗：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
```

由 `scripts/parse_nutrition.py` 解析为 dict 列表。

**字段与单位**：接口不声明单位，按麦当劳中国营养标示惯例为
energyKj=kJ、energyKcal=kcal、protein/fat/carbohydrate=g、sodium/calcium=mg。

**业务价值**：这是本项目唯一的主数据源。用户提供的是口语化的营养偏好，
需要真实的营养数值才能计算，而这是麦当劳官方唯一的免费营养数据来源。

### 2. query-meal-detail（餐品详情）

**入参**：`storeCode`、`orderType`、`beType`、`code`，其中 `code` 为套餐编码。

**返回**：`rounds[]` 选配轮次，每轮次的 `choices[]` 含
code、name、quantity、isDefault、diffPrice。

**业务价值**：计算套餐总热量。这是菜单聚合与营养表规格维度之间的唯一桥梁——
详见下文「为什么必须用这个工具的名称」。

## 为什么套餐拆解必须用 meal-detail

实测同一个编码 `4810`：

| 来源 | 名称 | 匹配营养表 |
|---|---|---|
| `query-meals` | 薯条 | 失败 |
| `query-meal-detail` | 中薯条 | 成功 |

`query-meals` 按"商品"聚合（薯条一个编码），营养表却按"规格"展开
（中薯条/大薯条/小薯条三条独立记录）。用菜单名匹配会漏掉大量条目。

代价是每个套餐多一次工具调用，换来默认搭配 8/9 的实测命中率。

## 调用流程

```
用户口语需求
  ↓ SKILL.md 负责翻译
数值约束（钠/热量/蛋白）
  ↓
list-nutrition-foods ──→ parse_nutrition.py ──→ 营养表
  ↓                                              ↓
  └──→ Solver.solve() ←── Constraint ←── 数值约束
  ↓
候选组合（正餐优先 → 钠升序 → 热量升序）

用户问套餐时：
query-meal-detail ──→ combo_resolver.py ──→ 用 choice.name 匹配营养表
  ↓
套餐合计营养（任一子项缺失则拒绝输出部分和）
```

## 只读边界

本项目**不调用**以下 7 个会产生消费或账户变更的工具：

| 工具 | 若调用的后果 | 本项目为何不调用 |
|---|---|---|
| `create-order` | 真实下单并产生费用 | 项目定位为营养决策辅助，不代用户下单 |
| `cancel-order` | 取消用户已有订单 | 越权操作 |
| `mall-create-order` | 扣减积分并发券 | 涉及用户资产 |
| `draw-lottery` | 消耗抽奖次数，不可逆 | 官方未公开限领/限次规则 |
| `auto-bind-coupons` | 不可逆领券，且会污染后续决策 | 属高影响动作，需用户显式确认 |
| `delivery-create-address` | 写入用户地址 | 涉及个人信息 |
| `party-order-create` | 真实下单 | 同 create-order |

其中 `auto-bind-coupons` 虽然免费，但领券会占用额度且无法撤销，
还会改变 `query-store-coupons` 的输出使决策结果不可复现。

## 数据获取与再验证

`tests/fixtures/` 下的数据为 2026-10-09 实测抓取。复现方式见
`references/data-notes.md`，其中记录了完整的接口返回形态与已知陷阱。

因为只依赖只读工具，重新抓取不会产生任何消费或账户变更。