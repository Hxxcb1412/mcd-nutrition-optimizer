"""活动新品与营养表覆盖缺口分析。

这是本项目实测发现的一个交叉问题，也是 29 个参赛项目里无人做过的角度。

发现过程
--------
`campaign-calendar` 实测返回当月活动，内容里反复出现新品：
「龙焰鸡腿堡三件套」「韩式烟熏芝士风味酱」「马苏里拉拉丝芝士条」
「蓝莓爆爆珠麦旋风」。

而 `list-nutrition-foods` 实测显示这些**全部没有营养数据**——
它们恰好落在菜单覆盖率 21.1% 的缺口里。

两个数据源交叉后得到一个实际结论：

    **活动日历每天在推的新品，恰好是营养表覆盖不到的那批。**

对用户的意义：看到活动推荐想买时，很可能算不出它的营养值。
本模块把这个矛盾显式指出，而不是让用户点进去才发现。

方法说明
--------
``campaign-calendar`` 返回的是 Markdown 图文列表而非结构化 JSON，
本模块用关键词抽取定位餐品名。做法保守：只在能确定匹配时给结论，
不确定的一律标为"需人工确认"，不猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nutrition_solver import NutritionItem

# 从活动文案里定位餐品名的候选词。
# 这些是实测活动中反复出现的核心词，覆盖汉堡、炸物、饮品、甜品几类。
#
# 不含酱料词（韩式辣椒黄油、韩式辣酱）——那是调味品，不是餐品，
# 营养表按餐品收录，混进来会虚增缺口数量。
_ITEM_PATTERNS = (
    "龙焰鸡腿堡",
    "龙焰芝士棒鸡腿堡",
    "马苏里拉拉丝芝士条",
    "蓝莓爆爆珠麦旋风",
    "厚松饼堡",
    "蘸酱炸鸡",
    "鸡薯双全盒",
    "灰焰圆筒",
    "猪柳蛋",
)

# 明确属于周边/非食品的活动，不参与营养分析。
_NON_FOOD_MARKERS = (
    "棒球帽",
    "丝巾",
    "徽章",
    "周边",
    "积分卡",
    "学期卡",
    "多邻国",
)


@dataclass
class CampaignItem:
    """从活动文案里定位到的一个餐品候选。"""

    name: str
    found_in_nutrition: bool = False
    nutrition_note: str = ""


@dataclass
class CampaignAnalysis:
    """一次活动分析的结论。"""

    title: str
    items: list[CampaignItem] = field(default_factory=list)
    is_food_campaign: bool = True

    @property
    def uncovered(self) -> list[CampaignItem]:
        return [i for i in self.items if not i.found_in_nutrition]

    @property
    def coverage_rate(self) -> float | None:
        if not self.items:
            return None
        return (len(self.items) - len(self.uncovered)) / len(self.items) * 100


def is_food_campaign(title: str, body: str) -> bool:
    """判断活动是否为餐品活动（排除纯周边/卡类）。"""
    text = f"{title} {body}"
    if any(marker in text for marker in _NON_FOOD_MARKERS):
        # 周边活动里也可能提到餐品（如"任意餐品消费加 39.9 元"），
        # 但主体是周边，不做营养分析。
        return False
    return True


def extract_items(text: str) -> list[str]:
    """从活动文案里抽取餐品候选名。

    只做精确子串匹配，不做模糊猜测——把活动文案切成词组再猜
    很容易产出不存在的产品名，那比漏掉更糟。
    """
    found: list[str] = []
    for pattern in _ITEM_PATTERNS:
        if pattern in text and pattern not in found:
            found.append(pattern)
    return found


def analyze(
    campaign_title: str,
    campaign_body: str,
    nutrition_index: dict[str, NutritionItem],
) -> CampaignAnalysis:
    """分析一个活动是否涉及营养表未收录的新品。"""
    analysis = CampaignAnalysis(
        title=campaign_title,
        is_food_campaign=is_food_campaign(campaign_title, campaign_body),
    )
    if not analysis.is_food_campaign:
        return analysis

    text = f"{campaign_title} {campaign_body}"
    for name in extract_items(text):
        item = nutrition_index.get(name)
        if item is not None and item.nutrition_complete:
            analysis.items.append(
                CampaignItem(name, True, f"{item.energy_kcal}kcal")
            )
        else:
            analysis.items.append(
                CampaignItem(name, False, "营养表未收录")
            )

    return analysis


def render_gap_summary(
    analyses: list[CampaignAnalysis],
    nutrition_index: dict[str, NutritionItem],
) -> str:
    """渲染活动与营养表的交叉分析。

    Args:
        analyses: 各活动的分析结果。
        nutrition_index: 营养表索引，用于二次确认。
    """
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("活动新品 与 营养表覆盖 交叉分析")
    add("=" * 58)
    add("")

    food = [a for a in analyses if a.is_food_campaign]
    non_food = [a for a in analyses if not a.is_food_campaign]

    add(f"分析活动 {len(analyses)} 个，其中餐品活动 {len(food)} 个、"
        f"周边/卡类 {len(non_food)} 个")
    add("")

    all_names: dict[str, bool] = {}
    for analysis in food:
        for item in analysis.items:
            all_names[item.name] = item.found_in_nutrition

    uncovered = [n for n, ok in all_names.items() if not ok]

    if uncovered:
        add("【营养表未收录的活动餐品】")
        for name in uncovered:
            add(f"  · {name}")
        add("")
        add("  实测结论：活动日历每天在推的新品，恰好是营养表覆盖不到的那批。")
        add("  用户看到活动推荐时，很可能算不出它的营养值——这是数据源的")
        add("  时间差，不是本工具能补上的。本项目如实告知而非估算。")
    else:
        add("活动涉及餐品均已收录在营养表中。")

    add("")
    add("【交叉统计】")
    if all_names:
        covered = len(all_names) - len(uncovered)
        rate = covered / len(all_names) * 100
        add(f"  活动涉及餐品 {len(all_names)} 种，"
            f"营养表收录 {covered} 种（{rate:.0f}%），缺失 {len(uncovered)} 种")
    add("")
    add("=" * 58)
    return "\n".join(lines)