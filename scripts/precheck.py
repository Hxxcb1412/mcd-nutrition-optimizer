"""下单前的数据可信度预检。

这是本 Skill 的核心能力，也是唯一不依赖任何新增数据源的能力。

它回答一个问题：**用户准备下单的这份方案，哪些营养结论算得出来，
哪些算不出来。**

为什么这个能力不可替代
--------------------
实测麦当劳官方营养表对门店菜单的覆盖率只有 21.1%，活动新品的收录率是 0%。
这意味着一个真实存在的风险：用户看活动推荐下单，
点完之后才发现算不出钠含量。

多数工具在这里会两种表现之一——要么假装能算（用估算值填充），
要么直接报错。两种都是错的：前者给出可能错误的数字，
后者让用户以为自己配错了。

本模块的做法是**在算之前先说清楚哪些算不出来**。

与本项目其他模块的关系
--------------------
- `nutrition_solver`负责求解，本模块负责**判断结果可不可信**
- `combo_resolver` 拆套餐时已能识别缺失子项，本模块把该能力扩展到
  单品组合、活动推荐、整单预检三个入口

明确的边界
----------
本模块**不做健康建议**，只做数据质量检查。它不会告诉用户"该不该吃"，
只告诉用户"这个数字能不能信"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from combo_resolver import build_nutrition_index
from nutrition_solver import NutritionItem, _category_of

# 预检结论等级
class Confidence:
    """一份方案的数据可信度。"""

    FULL = "完整可信"      # 全部餐品有营养数据
    PARTIAL = "部分可信"   # 部分能算，缺失部分已标注
    UNCOMPUTABLE = "无法计算"  # 关键项缺失，无法给出结论


@dataclass
class PrecheckItem:
    """方案里的一项。"""

    name: str
    quantity: int = 1
    resolved: bool = False
    reason: str = ""
    nutrition: NutritionItem | None = None

    @property
    def category(self) -> str:
        return _category_of(self.name)


@dataclass
class PrecheckResult:
    """一份方案的预检结果。"""

    items: list[PrecheckItem] = field(default_factory=list)
    # 缺失原因分类
    zero_value_placeholder: list[str] = field(default_factory=list)
    # 官方未收录（数据滞后）
    not_in_nutrition_table: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def resolved(self) -> list[PrecheckItem]:
        return [i for i in self.items if i.resolved]

    @property
    def unresolved(self) -> list[PrecheckItem]:
        return [i for i in self.items if not i.resolved]

    @property
    def confidence(self) -> str:
        if not self.items:
            return Confidence.UNCOMPUTABLE
        if not self.unresolved:
            return Confidence.FULL
        if not self.resolved:
            return Confidence.UNCOMPUTABLE
        return Confidence.PARTIAL

    def computable_total(self) -> dict[str, float] | None:
        """可计算部分的合计，**按数量加权**。

        任一项缺失时返回 None 而非部分和——部分和会低估热量，
        让用户以为这单更健康。
        """
        if not self.items or self.unresolved:
            return None
        keys = ("energy_kcal", "protein", "fat", "carbohydrate", "sodium", "calcium")
        return {
            k: sum((getattr(i.nutrition, k) or 0.0) * i.quantity for i in self.resolved)
            for k in keys
        }

    def blocking_reason(self) -> str:
        """阻止给出完整结论的原因说明。"""
        if self.confidence is Confidence.FULL:
            return ""
        if not self.items:
            return "方案为空，没有可检查的餐品"
        if self.confidence is Confidence.UNCOMPUTABLE:
            names = "、".join(i.name for i in self.unresolved)
            return f"方案中「{names}」没有营养数据，无法给出结论"
        names = "、".join(i.name for i in self.unresolved)
        return (
            f"方案中「{names}」没有营养数据，只能给出部分餐品的合计值。"
            f"部分和会低估总热量，因此本工具不输出它"
        )


def build_full_index(
    items: list[NutritionItem],
) -> dict[str, NutritionItem]:
    """建立**不筛除**占位记录的完整索引。

    为什么需要单独一个函数：`combo_resolver.build_nutrition_index` 会过滤掉
    `nutrition_complete=False` 的条目（求解时不该看到它们），但预检恰恰需要
    知道它们存在——「纯悦」在表里是占位记录，这与「龙焰鸡腿堡」根本没收录
    是两回事，缺失原因不同，报给用户的话也不一样。

    直接复用求解器的索引会让占位记录被误报成"官方未收录"。
    """
    return {(i.product_name or "").strip(): i for i in items if i.product_name}


def precheck(
    dish_names: list[str],
    nutrition_index: dict[str, NutritionItem],
    quantities: dict[str, int] | None = None,
) -> PrecheckResult:
    """对一份方案做数据可信度预检。

    Args:
        dish_names: 方案里的餐品名。
        nutrition_index: 名称 -> NutritionItem 的索引。
            **必须用 `build_full_index`**，不能用求解器那个会过滤占位记录的版本。
        quantities: 各餐品数量，缺省视为 1。

    Returns:
        预检结果，包含可计算部分与缺失原因分类。
    """
    quantities = quantities or {}
    result = PrecheckResult()

    for name in dish_names:
        name = (name or "").strip()
        if not name:
            continue
        qty = int(quantities.get(name, 1))

        item = nutrition_index.get(name)
        if item is None:
            result.not_in_nutrition_table.append(name)
            result.items.append(
                PrecheckItem(name, qty, False, "官方营养表未收录")
            )
            continue

        if not item.nutrition_complete:
            # 零值且零蛋白 = 官方未收录的占位，不是真实零热量
            result.zero_value_placeholder.append(name)
            result.items.append(
                PrecheckItem(
                    name, qty, False, "营养表为占位记录（热量与蛋白同时为 0）"
                )
            )
            continue

        result.items.append(PrecheckItem(name, qty, True, "", item))

    return result


def check_meal_result(combo) -> PrecheckResult:
    """对求解器给出的组合做预检。

    组合里的餐品都来自营养表（求解器已过滤），但仍需检查
    是否包含未收录项——例如用户手动指定的餐品。
    """
    result = PrecheckResult()
    for item in combo.items:
        if item.nutrition_complete:
            result.items.append(
                PrecheckItem(item.product_name, 1, True, "", item)
            )
        else:
            result.zero_value_placeholder.append(item.product_name)
            result.items.append(
                PrecheckItem(
                    item.product_name,
                    1,
                    False,
                    "营养表为占位记录",
                )
            )
    return result


def render(result: PrecheckResult) -> str:
    """渲染预检结果。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("下单前数据可信度预检")
    add("=" * 58)
    add("")

    flag = {
        Confidence.FULL: "完整可信",
        Confidence.PARTIAL: "部分可信",
        Confidence.UNCOMPUTABLE: "无法计算",
    }[result.confidence]
    add(f"【结论】{flag}")
    add("")

    if result.items:
        add("【逐项检查】")
        for item in result.items:
            mark = "可算" if item.resolved else "缺数据"
            qty = f"×{item.quantity}" if item.quantity > 1 else ""
            add(f"  [{mark}] {item.name}{qty}")
            if item.resolved and item.nutrition is not None:
                add(
                    f"          {item.nutrition.energy_kcal:.0f}kcal ·"
                    f" 蛋白 {item.nutrition.protein:.0f}g ·"
                    f" 钠 {item.nutrition.sodium:.0f}mg"
                )
            elif not item.resolved:
                add(f"          {item.reason}")
        add("")

    if result.confidence is Confidence.FULL:
        totals = result.computable_total()
        if totals:
            add("【可计算的完整合计】")
            add(
                f"  {totals['energy_kcal']:.0f} kcal ·"
                f" 蛋白 {totals['protein']:.0f} g ·"
                f" 脂肪 {totals['fat']:.0f} g ·"
                f" 碳水 {totals['carbohydrate']:.0f} g ·"
                f" 钠 {totals['sodium']:.0f} mg"
            )
            add("")
    else:
        add("【为什么不输出合计】")
        add(f"  {result.blocking_reason()}")
        add("  部分和会低估总热量，让你以为这单更健康。")
        add("")

    if result.zero_value_placeholder:
        add("【数据说明】")
        add("  以下餐品在官方营养表里是占位记录（热量与蛋白质同时为 0）：")
        for name in result.zero_value_placeholder:
            add(f"    · {name}")
        add("  这不代表它们是零热量食物，是官方尚未收录。")
        add("")

    if result.not_in_nutrition_table:
        add("【数据说明】")
        add("  以下餐品官方营养表完全没有收录：")
        for name in result.not_in_nutrition_table:
            add(f"    · {name}")
        add("  常见于活动期间的新品——实测活动新品的收录率为 0%。")
        add("")

    add("=" * 58)
    return "\n".join(lines)