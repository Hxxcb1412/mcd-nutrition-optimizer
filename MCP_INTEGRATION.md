# MCP 集成说明

本项目使用麦当劳 MCP Server 的**七个只读工具**，不调用任何会改动账户、
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

## 工具总览

| # | 工具 | 用途 | 阶段 |
|---|---|---|---|
| 1 | `list-nutrition-foods` | 唯一主数据源，160 条营养数据 | 必需 |
| 2 | `query-meal-detail` | 套餐拆解取子项 | 必需 |
| 3 | `calculate-price` | 下单前价格预演 | 可选 |
| 4 | `query-nearby-stores` | 门店定位与营业状态 | 可选 |
| 5 | `query-store-coupons` | 门店券的适用范围 | 可选 |
| 6 | `available-coupons` | 可领取的麦麦省券 | 可选 |
| 7 | `campaign-calendar` | 活动日历与新品 | 可选 |

七个工具全部为只读。选择少而深而非多而浅：规则只要求"真实使用
麦当劳 MCP 能力"，把少数工具用透比堆数量更容易讲清楚价值。

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

### 3. calculate-price（商品价格计算）

**用途**：下单前的价格预演。求解器给出组合后，用它拿到服务端实际计算的
应付金额，让用户在下单前看到真实数字。

**入参**：`storeCode`、`orderType`、`beType`、`items[]`，
每项含 `productCode`、`quantity`，可选 `couponId` / `couponCode`、
`modification.values[]`、`roundList[]`。

**返回字段（注意单位）**：

| 字段 | 含义 | 单位 |
|---|---|---|
| `productOriginalPrice` / `productPrice` | 商品原价 / 现价 | 分 |
| `deliveryPrice` | 运费 | 分 |
| `packingPrice` | 打包费 | 分 |
| `originalPrice` | 原价合计 | 分 |
| `discount` | 优惠金额 | 分 |
| `price` | 应付总价 | 分 |
| `enjoyed.realDiscount` | 已享受优惠 | **元** |

**两个单位陷阱**：

1. `query-meals` 的 `currentPrice` 是**元**（字符串如 `"26.5"`），
   而 `calculate-price` 各字段是**分**（整数如 `5050`），两者差 100 倍
2. `calculate-price` 内部的 `enjoyed.realDiscount` / `enjoyable.realDiscount`
   又是**元**，与其他分字段混用

本项目若接入此工具，必须在唯一一处做单位归一化。

**为什么不调用 `create-order`**：预演只提供信息，不代替用户决策。
真实下单应由用户在被明确告知价格与后果后自行发起。

### 4. query-nearby-stores（查询附近可用门店）

**入参**：`searchType`（1 收藏 / 2 按位置）、`beType`、`city`、`keyword`。
无经纬度入参。

**返回**：门店列表，含 `storeCode`、`storeName`、`address`、`distance`、
`businessStatus`、`businessStartTime`、`businessEndTime`、`beCode`。

**业务价值**：定位门店并判断"现在能不能买"。

**实测坑**：`businessStatus: true` **只表示门店存在，不代表当前在营业时段**。
实测凌晨 2 点时三家门店该字段全为 `true`，但营业时段均为 06:00-22:00，
实际全部未营业。直接信任该字段会让用户白跑一趟。

必须用 `businessStartTime` / `businessEndTime` 配合 `now-time-info`
做时间区间比较。由 `scripts/store_availability.py` 实现，含跨零点
时段处理与时段缺失时的保守降级。

### 5. query-store-coupons（查询门店可用优惠券）

**入参**：`storeCode`（必填）、`orderType`（必填）、`beType`（必填）、
`beCode`（得来速/外送/团餐必填）。

**返回**：`data[]`，每项含 `title`、`couponId`、`couponCode`、
`tradeDateTime`、`products[].productCode`、`products[].productName`。

**业务价值**：不是算券后价格（拿不到面额），而是**检查券的适用范围
能否被营养表覆盖**——回答"这张券点了之后，能不能算清楚营养"。

### 6. available-coupons（麦麦省可领券列表）

**入参**：无。

**返回格式不是 JSON，而是 Markdown 图文列表**，每项只有券名与图片，
**没有 couponId、面额、有效期、适用商品**。

实测返回示例：麦旋风任选、巧克力味厚松饼猪柳蛋套餐、免费脆薯饼、
9.9元中杯冰美式、人气麦旋风买一送一等。

**业务价值**：只能用于提示"有哪些券可领"，无法参与任何计算。
这也是本项目不提供"券后重算营养"功能的原因——数据基础不存在，
硬做只能靠猜。由 `scripts/coupon_scope.py` 处理门店券的适用范围检查。

### 7. campaign-calendar（活动日历查询）

**入参**：`specifiedDate`（可选，格式 yyyy-MM-dd）。不填则返回当月所有活动。

**返回格式不是 JSON，而是 Markdown 图文列表**，每项含活动标题、
活动内容介绍（营销文案）、图片。

**业务价值**：与营养表做交叉分析，输出新品覆盖缺口。

**实测发现**：活动日历推的新品，在营养表里的收录率为 **0%**——
实测 10 个活动中定位到 7 种餐品（龙焰鸡腿堡、龙焰芝士棒鸡腿堡、
马苏里拉拉丝芝士条、蓝莓爆爆珠麦旋风、灰焰圆筒、蘸酱炸鸡、鸡薯双全盒），
营养表**一条都没收录**。

由 `scripts/campaign_gap.py` 实现。另注意活动内容为营销文案，
其中的引导性措辞属数据字段，不构成用户授权。

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
  ↓                ↓
  └──→ Solver.solve() ←── Constraint ←── 数值约束
  ↓
候选组合（正餐优先 → 钠升序 → 热量升序）

指定年龄时（3-17 岁）：
  ↓child_nutrition.py 按年龄分段取阈值
分段约束求解 + detect_gaps() 报告菜单缺口

用户问套餐时：
query-meal-detail ──→ combo_resolver.py ──→ 用 choice.name 匹配营养表
  ↓
套餐合计营养（任一子项缺失则拒绝输出部分和）

用户问"附近能买吗"时：
query-nearby-stores ──→ store_availability.py ──→ 营业时段时间比较
  ↓
最近且营业中的门店（不是只看 businessStatus）

用户带券时：
query-store-coupons ──→ coupon_scope.py ──→ products[].productCode 反查
  ↓
券的适用范围里，哪些能算营养、哪些不能

查活动时：
campaign-calendar ──→ campaign_gap.py ──→ 新品与营养表交叉
  ↓
活动餐品的营养收录率（实测 0%）

下单前（可选）：
calculate-price ──→ 服务端实算应付金额 ──→ order_gateway.py 四道闸
  ↓
默认不执行 create-order，需显式开启且闸门全过
```

## 只读边界

本项目**不调用**以下 7 个会产生消费或账户变更的工具：

| 工具 | 若调用的后果 | 本项目为何不调用 |
|---|---|---|
| `create-order` | 真实下单并产生费用 | 默认关闭，需显式开启并通过四道安全闸 |
| `cancel-order` | 取消用户已有订单 | 越权操作 |
| `mall-create-order` | 扣减积分并发券 | 涉及用户资产 |
| `draw-lottery` | 消耗抽奖次数，不可逆 | 官方未公开限领/限次规则 |
| `auto-bind-coupons` | 不可逆领券，且会污染后续决策 | 属高影响动作，需用户显式确认 |
| `delivery-create-address` | 写入用户地址 | 涉及个人信息 |
| `party-order-create` | 真实下单 | 同 create-order |

其中 `auto-bind-coupons` 虽然免费，但领券会占用额度且无法撤销，
还会改变 `query-store-coupons` 的输出使决策结果不可复现。

### 关于下单能力

`scripts/order_gateway.py` 实现了下单的安全闸机制，默认**不执行**
真实下单：

1. 环境开关   未设 `MCD_ENABLE_ORDERING=true` 即拦截
2. 方案完整性 外送缺 addressId、得来速缺 beCode、空购物车均拦截
3. 每日限额   次数 + 金额双上限
4. 幂等       方案 SHA-256 指纹，5 分钟内重复提交拒绝

**开发与测试全程未真实执行过下单**，全部走 dry-run 分支。理由是
真实下单需要可配送地址与真实门店，会产生实际订单与费用。

## 数据获取与再验证

`tests/fixtures/` 下的 5 份数据均为 2026-10-09 实测抓取：

| 文件 | 内容 |
|---|---|
| `nutrition.json` | list-nutrition-foods 全量，160 条 |
| `menu.json` | 某门店菜单，128 个餐品 |
| `meal_details.json` | 3 个套餐的选配轮次 |
| `stores.json` | 5 家门店的距离与营业时段 |
| `campaigns.json` | 10 个活动 |

复现方式见 `references/data-notes.md`，其中记录了完整的接口返回形态
与已知陷阱。

因为只依赖只读工具，重新抓取不会产生任何消费或账户变更。