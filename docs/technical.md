# 技术细节

主README 面向「想快速了解并使用这个项目的人」。
这份文档面向想了解**实现细节与实测数据**的人。

数据获取方式、接口陷阱、算法设计、测试覆盖都在这里。

---

## 已知限制

**官方营养表对门店菜单的覆盖率有限。** 实测某门店菜单 128 个餐品中，
只有 27 个能在营养表里找到（**21.1%**）。这个数字可用下面的命令自己验证：

```bash
python scripts/coverage_report.py
```

工具会输出分层覆盖率、规格歧义清单和套餐拆解完整性：

```
【匹配层级】
  精确同名21 个   16.4%
  + 剥规格后缀     5 个   20.3%
  + 括号归一化     1 个   21.1%

完全无营养数据  101 个
```

根因是**官方营养表滞后于菜单**，龙焰鸡腿堡、双层脆鸡堡、
厚薯泥培根肉酱双牛堡、马苏里拉拉丝芝士条、韩式烟熏芝士系列等新品
均未收录。归一化只多救回 1 个条目，收益极低。

>一个口径说明：`100%苹果汁(盒装)`（菜单）与 `100%苹果汁`（营养表）
> 只差"(盒装)"这个包装描述。本项目**不剥离括号内容**，
> 因为包装差异可能对应不同配方。只有全角括号与 `【】` 类装饰符会被归一化，
> 因此口径比"激进匹配"少命中 1 个餐品。

另外，菜单里的「可乐」对应营养表的中杯/大杯/小杯三条，钠含量不同。
工具会把这类列为**规格歧义**并列出全部候选，不静默取第一个：

```
【规格歧义：这些餐品对应多个营养表条目】
  可乐
    -> 可乐中杯, 可乐大杯, 可乐小杯
```

所以本项目**只对营养表已收录的餐品做推荐**，不承诺覆盖全部菜单。
遇到未收录餐品如实说明，不估算、不猜测。

**麦当劳没有低钠正餐。** 蛋白质 ≥5g 的餐品里钠最低的是优品豆浆（32mg），
再往下全是饮品和奶品，汉堡类钠普遍在 500-1000mg。要求「低钠午餐」
时本 Skill 会如实告知，而不是硬凑一个没有意义的答案。

其他限制：

- 只支持单品与套餐默认搭配。换套餐选配项后覆盖率会下降
  （实测三件套 77%、四件套 55%、随心配 53%）
- 不支持历史订单热量复盘。`order-list` 不返回任何营养字段，
  且营养表无编码，两者无法可靠关联

---

## 项目结构

```
docs/
  demo.html                演示页，单文件内联无需依赖
scripts/
  parse_nutrition.py     TOON 格式解析（官方返回非标准 JSON）
  nutrition_solver.py    多目标求解器，正餐优先 + 钠升序
  combo_resolver.py      套餐拆解与子项营养匹配
  child_nutrition.py     儿童按年龄分段求解 + 缺口报告
  store_availability.py  门店营业时段判断
  coupon_scope.py        券适用范围与营养可算性检查
  campaign_gap.py        活动新品与营养表交叉分析
  order_gateway.py       下单安全网关，默认 dry-run
  coverage_report.py     门店营养覆盖率体检
  precheck.py            下单前数据可信度预检
  sodium_ledger.py       钠累计账本（附带能力）
  smoke_test.py          对实测夹具跑基线，验证可复现
  test_solver.py         单元测试
  test_child_nutrition.py  儿童模块测试
  test_store_and_campaign.py  门店/券/活动模块测试
  test_precheck.py       预检与钠账本测试
tests/fixtures/          5 份 MCP 实测抓取数据
references/data-notes.md 全部实测踩坑记录
```

## 使用的 MCP 工具

七个，全部只读：

| 工具 | 用途 |
|---|---|
| `list-nutrition-foods` | 唯一主数据源，160 条营养数据 |
| `query-meal-detail` | 套餐拆解取子项 |
| `calculate-price` | 下单前价格预演（可选） |
| `query-nearby-stores` | 门店定位与营业状态 |
| `query-store-coupons` | 券的适用范围检查 |
| `available-coupons` | 可领取的麦麦省券 |
| `campaign-calendar` | 活动日历与新品 |

**不调用** `create-order`、`cancel-order`、`mall-create-order`、
`draw-lottery`、`auto-bind-coupons`、`delivery-create-address`、
`party-order-create` 这 7 个会改动账户或产生消费的工具。

下单能力由 `order_gateway.py` 提供，默认关闭。开发与测试全程未真实执行过
下单，全部走 dry-run 分支。

## 本地验证

```bash
python scripts/test_solver.py              # 单元测试 19 项
python scripts/test_child_nutrition.py     # 儿童模块 113 项
python scripts/test_store_and_campaign.py  # 门店/券/活动 38 项
python scripts/test_precheck.py            # 预检与钠账本 58 项
python scripts/smoke_test.py               # 真实数据基线 24 项
python scripts/coverage_report.py          # 覆盖率体检
```

共 252 项断言，全部不需要 MCP 连接，直接读 `tests/fixtures/` 下的实测数据。

---

## 声明

本项目为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，
非麦当劳官方产品。

输出仅供参考，不构成医疗、营养或其他专业建议。
餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。

---

**觉得有用的话，点个 ⭐ Star 支持一下。** 本项目参加麦当劳程序员节创意开发大赛，
排名看 Star 数。