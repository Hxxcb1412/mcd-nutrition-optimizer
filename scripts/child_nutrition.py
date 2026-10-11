"""儿童营养求解。

用户告知年龄后，按年龄段的目标值在麦当劳营养表里求解适合的组合。

关于阈值来源，必须说清楚
------------------------
营养**数值**全部来自麦当劳官方 MCP 的实测数据，这是本项目唯一的一手数据。

年龄分段的**参考阈值**来自《中国居民膳食指南》的通用人群参考值，
**不是麦当劳官方数据，也不是医疗建议**。这两者在本模块里严格分开：

- ``NUTRITION_SOURCE`` 标记数据来自官方接口
- 每条profile 都带 ``reference_only: True`` 标记，输出时必须原样呈现

这是刻意的。家长最容易质疑的是"你凭什么说这个适合我家孩子"，
诚实的答案是"营养数值来自麦当劳官方，参考阈值来自膳食指南，两者都不是医疗意见"。

不做的事
--------
- 不做医疗或营养处方建议
- 不诊断、不给治疗建议
- 不替代儿科医生或营养师的意见
- 不用「适合」「健康」「推荐」这类断言性措辞描述结果
"""

from __future__ import annotations

from dataclasses import dataclass

from nutrition_solver import (
    Combination,
    Constraint,
    NutritionItem,
    Solver,
    _category_of,
)

# 数据来源标注，所有输出必须携带
NUTRITION_SOURCE = "mcd-mcp list-nutrition-foods 实测"
THRESHOLD_SOURCE = "《中国居民膳食指南》通用人群参考值（非麦当劳官方，非医疗建议）"

# 年龄分段。阈值是每日推荐摄入的上限参考值，不是精准处方量。
#
# 数值口径说明：热能量取该年龄段常见参考区间的下限到上限，钠取上限。
# 之所以不取精确值，是因为个体差异（体重、活动量、是否有特殊状况）极大，
# 任何精确数字都会显得比实际更权威 —— 那是不诚实的。
AGE_PROFILES: dict[str, dict] = {
    "3-6": {
        "label": "学龄前（3-6 岁）",
        "min_kcal": 350,
        "max_kcal": 500,
        "max_sodium": 800,
        "max_fat": 18,
        "note": "学龄前儿童每日钠参考上限 800mg，麦麦套餐的钠普遍超出该范围，"
                "这是数据事实，不做粉饰",
    },
    "7-12": {
        "label": "学龄儿童（7-12 岁）",
        "min_kcal": 550,
        "max_kcal": 750,
        "max_sodium": 1000,
        "max_fat": 25,
        "note": "学龄儿童每日钠参考上限 1000mg",
    },
    "13-17": {
        "label": "青少年（13-17 岁）",
        "min_kcal": 700,
        "max_kcal": 950,
        "max_sodium": 1500,
        "max_fat": 32,
        "note": "青少年每日钠参考上限 1500mg，接近成人水平",
    },
}

DEFAULT_PROFILE = "7-12"


def resolve_age_band(age: int) -> str:
    """把年龄映射到分段键。超出范围时返回None 由调用方处理。"""
    if age <= 0 or age >= 18:
        return ""
    if age <= 6:
        return "3-6"
    if age <= 12:
        return "7-12"
    return "13-17"


@dataclass
class ChildProfile:
    """某个年龄段的目标值。"""

    band: str
    label: str
    min_kcal: float
    max_kcal: float
    max_sodium: float
    max_fat: float
    note: str
    reference_only: bool = True

    @property
    def threshold_source(self) -> str:
        return THRESHOLD_SOURCE

    @property
    def nutrition_source(self) -> str:
        return NUTRITION_SOURCE

    def to_constraint(self) -> Constraint:
        """转成求解器约束。

        注意 max_kcal 传的是本年龄段上限，求解器会据此派生 min_kcal
        （上限的 60%），对儿童场景是合理的下限保护。

        strict_protein 对儿童不启用：儿童餐的蛋白质目标因人而异，
        且低钠餐品天然蛋白低，强制会直接导致无解。
        """
        return Constraint(
            min_kcal=self.min_kcal,
            max_kcal=self.max_kcal,
            max_sodium=self.max_sodium,
            max_fat=self.max_fat,
        )


def get_profile(age: int) -> tuple[ChildProfile | None, str]:
    """按年龄取阈值档案。

    Returns:
        (档案, 说明)。年龄超出 3-17 时档案为 None，说明给出原因。
    """
    band = resolve_age_band(age)
    if not band:
        if age >= 18:
            return None, (
                f"{age} 岁已超出本模块覆盖范围（3-17 岁）。"
                "成人场景请用通用营养求解，不需要儿童分段的保守阈值。"
            )
        return None, "年龄需在 3-17 岁之间。"

    spec = AGE_PROFILES[band]
    profile = ChildProfile(
        band=band,
        label=spec["label"],
        min_kcal=spec["min_kcal"],
        max_kcal=spec["max_kcal"],
        max_sodium=spec["max_sodium"],
        max_fat=spec["max_fat"],
        note=spec["note"],
    )
    return profile, ""


def solve_for_child(
    items: list[NutritionItem],
    age: int,
    limit: int = 5,
    max_items: int = 3,
) -> tuple[ChildProfile | None, list[Combination], str]:
    """为指定年龄求解适合的组合。

    Returns:
        (档案, 组合列表, 说明)。档案为 None 时组合为空。
        无解时组合为空列表，说明里给出原因，不返回近似解。
    """
    profile, message = get_profile(age)
    if profile is None:
        return None, [], message

    solver = Solver(items)
    constraint = profile.to_constraint()

    # 儿童场景必须过滤掉纯饮品组合。
    #
    # 实测问题：4 岁段位的热量下限 350kcal 无法下调（否则不是一餐），
    # 而低钠食物几乎全是饮品，于是求解器给出「可乐大杯 + 纯牛奶」——
    # 353kcal / 蛋白 7g / 钠 73mg。数字上满足所有约束，但它不是儿童餐。
    #
    # 这个错误在成人场景只是荒谬，在儿童场景是严重不当，因此这里加一道
    # 独立过滤：组合必须含主食或蛋白类，且饮品不超过 1 个。
    combos = _filter_child_appropriate(
        solver.solve(constraint, max_items=max_items, limit=limit * 4)
    )[:limit]

    if not combos:
        reason = (
            f"麦当劳 {len([i for i in items if i.nutrition_complete])} 条有营养数据的餐品里，"
            f"没有组合能同时满足 {profile.label}的热量下限 {profile.min_kcal:.0f}kcal、"
            f"钠上限 {profile.max_sodium}mg、脂肪上限 {profile.max_fat}g，"
            f"且包含主食或蛋白类餐品。"
        )
        return profile, [], reason

    return profile, combos, ""


def _filter_child_appropriate(combos: list[Combination]) -> list[Combination]:
    """只保留适合儿童正餐的组合。

    三条规则，复用求解器已有的类别判定，不另立标准：

    1. 必须含主食或蛋白类——饮品凑不出「一顿饭」
    2. 饮品不超过 1 个——实测不加这条时 4 岁场景会算出
       「可乐大杯 + 纯牛奶」三样饮品
    3. **正餐类（主食+蛋白）的数量必须多于甜品**
       ——不加这条时 7 岁场景首解是「yeyeyeye奶冻款 + 大杯怡泉+C
       + 麦乐鸡4块」。奶冻能提供热量但不该作为儿童正餐主体，
       判据是「正餐必须多于甜品」而非「甜品≤1」：单个奶冻搭配
       一份主食时，两边数量相等，甜品仍是主角。
    """
    result = []
    for combo in combos:
        categories = [_category_of(i.product_name) for i in combo.items]
        mains = categories.count("主食") + categories.count("蛋白")
        if mains == 0:
            continue
        if categories.count("饮品") > 1:
            continue
        if categories.count("甜品") >= mains:
            continue
        result.append(combo)
    return result


def detect_gaps(profile: ChildProfile, items: list[NutritionItem]) -> list[str]:
    """检查这份菜单在该年龄段的营养结构缺口。

    这是本模块最有价值的部分：不只推荐，还诚实指出菜单满足不了什么。
    实测学龄前段落的钠上限 800mg 极难满足，必须说出来而不是硬凑。
    """
    gaps: list[str] = []

    feasible = [
        i
        for i in items
        if i.nutrition_complete
        and (i.energy_kcal or 0) <= profile.max_kcal
        and (i.sodium or 0) <= profile.max_sodium
        and (i.fat or 0) <= profile.max_fat
    ]

    categories = {_category_of(i.product_name) for i in feasible}

    if not feasible:
        gaps.append(
            f"没有任何单个餐品同时满足 {profile.label}的热量、钠与脂肪上限。"
        )
        return gaps

    if "主食" not in categories:
        gaps.append(
            "该年龄段约束下没有可用主食类餐品。麦当劳的儿童友好主食"
            "（麦满分、儿童鱼排堡）钠含量普遍在 400-850mg，"
            "容易超出低龄段落的钠上限。"
        )

    if "配菜" not in categories:
        gaps.append("缺少配菜类。薯条是主要配菜，但中薯条 165mg 钠已占学龄前上限的两成。")

    high_sodium = [
        i for i in items
        if i.nutrition_complete
        and (i.sodium or 0) > profile.max_sodium
    ]
    if high_sodium:
        ratio = len(high_sodium) / len([i for i in items if i.nutrition_complete]) * 100
        gaps.append(
            f"全表 {ratio:.0f}% 的餐品钠含量超过 {profile.max_sodium}mg 上限。"
            "这是数据事实——麦当劳的菜单设计本就不是低钠餐。"
        )

    return gaps


def render(profile: ChildProfile, combos: list[Combination]) -> str:
    """渲染儿童方案为可读文本。所有来源标注必须出现。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add(f"儿童营养参考方案 · {profile.label}")
    add("=" * 58)
    add("")
    add(f"参考阈值（{profile.threshold_source}）")
    add(f"  热量 {profile.min_kcal:.0f}-{profile.max_kcal:.0f} kcal")
    add(f"  钠≤ {profile.max_sodium:.0f} mg")
    add(f"  脂肪 ≤ {profile.max_fat:.0f} g")
    add("")
    add(f"营养数值来源：{profile.nutrition_source}")
    add("")

    for idx, combo in enumerate(combos, start=1):
        add(f"方案 {idx}")
        for item in combo.items:
            add(
                f"  · {item.product_name}"
                f"  {item.energy_kcal:.0f}kcal / 蛋白 {item.protein:.0f}g /"
                f" 钠 {item.sodium:.0f}mg"
            )
        add(
            f"  合计 {combo.total_kcal:.0f}kcal · 蛋白 {combo.total_protein:.0f}g ·"
            f" 钠 {combo.total_sodium:.0f}mg"
        )
        add("")

    return "\n".join(lines)