# WorkBuddy 使用上下文

本项目在 WorkBuddy 中开发，用于核验是否符合 WorkBuddy 专项奖励条件。

## 开发流程

### 阶段一：情报收集

通过 WebFetch 读取赛事官方仓库，确认关键约束：

- 排名只看 GitHub 公开 Star 总数，前 100 名进榜
- 同一账号多个项目只有 Star 最高的进榜，故只能做一个项目
- 必带文件 5 个，其中 `CONTEST_DECLARATION.md` 内容一字不可改
- 仓库创建时间必须落在 2025-12-25 至 2026-10-25 之间
- 内容合规红线：不得宣扬不健康饮食、不得与其他品牌对比

### 阶段二：实测替代文档查阅

关键转折点。官方 API 文档页`open.mcd.cn/mcp/doc` 是前端渲染的，
WebFetch 抓不到正文；GitHub 仓库只有两个 README、无 API 文档。

改用**直接调用线上 MCP Server 逐个抓取真实返回报文**，权威度高于文档转述。
这一步发现了三个改变方案设计的结论：

1. `list-nutrition-foods` 返回 TOON 格式而非 JSON，且**零编码字段**
2. `query-meals` 与 `query-meal-detail` 对同一编码给出**不同名称**
3. 营养表对菜单的覆盖率仅 17~22%，因营养表滞后于新品

### 阶段三：需求收敛

原设想是「热量预算 + 距离 + 门店」的综合决策。实测发现菜单覆盖率过低
会中途翻车，主动放弃距离与门店匹配，改为以营养表为核心资产。

### 阶段四：实现与踩坑

三个真实缺陷，均由实测数据暴露而非单元测试假设：

1. **零值判定错误**——原判据"四字段全为 0"漏判无糖可乐
   （其碳水字段为 1 而非 0），导致它以"0 大卡 2mg 钠"成为最优解。
   改为「热量与蛋白质同时为 0」。

2. **排序策略错误**——纯钠优先使「清淡午餐」收敛到
   「冰美式 + 可乐 + 纯牛奶」三样饮品。原因是低钠食物集中在奶品类，
   而正餐类钠普遍500mg 以上。改为「正餐优先 → 钠升序 → 热量升序」。

3. **套餐匹配源错误**——同一编码 `4810` 在 `query-meals` 叫「薯条」
   （匹配失败）、在 `query-meal-detail` 叫「中薯条」（匹配成功）。
   必须使用后者的choice name。

### 阶段五：基线固化

将实测抓取的数据固化为 `tests/fixtures/` 下的夹具，
`scripts/smoke_test.py` 对其跑基线断言，确保 README 中的每个数字可复现。

## 工具使用

| 环节 | 用到的工具 |
|---|---|
| 赛事与 API 情报 | WebFetch、WebSearch |
| 数据实测 | `mcd-mcp` 全部为只读工具 |
| 代码实现与验证 | Python 3.13（托管运行时） |

## 未使用的写入类工具

`create-order`、`cancel-order`、`mall-create-order`、`draw-lottery`、
`auto-bind-coupons`、`delivery-create-address`、`party-order-create`

这 7 个会改动账户或产生消费，本项目全程未调用，
理由记录在 `MCP_INTEGRATION.md`。

## 可复现验证

```bash
python scripts/test_solver.py   # 单元测试
python scripts/smoke_test.py    # 真实数据基线
```

两者均不依赖 MCP 连接，直接读本地夹具。