"""套餐拆解：从 menu 的套餐编码还原出它的选配项及其营养。

为什么必须走 meal-detail 而不是 menu
------------------------------------
实测 code=4810 在两个工具里名称不同：

- ``query-meals`` 里叫「薯条」—— 匹配营养表**失败**（表里只有中薯条）
- ``query-meal-detail`` 里叫「中薯条」—— 匹配**成功**

菜单把同一餐品按"商品"聚合（薯条一个 code），营养表却按"规格"展开
（中薯条/大薯条/小薯条三条）。因此套餐拆解必须用
``query-meal-detail`` 的 ``rounds[].choices[].name``，用菜单名会漏。

实测覆盖率：三个真实套餐的默认子项 8/9 命中，未命中的「可乐麦炫酷」
是整个麦炫酷系列未收录进官方营养表，属数据缺失，不做估算。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nutrition_solver import NutritionItem


class MatchStatus:
    """匹配状态。区分"命中"与"无数据"，后者绝不能当0 用。"""

    EXACT = "精确命中"
    NORMALIZED = "归一化命中"
    MISSING = "营养表无此条目"


def normalize(name: str) -> str:
    """名称归一化。

    只做对称的无损变换：全角括号转半角、去掉【】和书名号类装饰、
    去掉 · 和空白。不能剥离杯型后缀——「可乐」会同时匹配中杯、
    大杯、小杯三条，而三者钠含量不同，合并会给出错误建议。
    """
    if not name:
        return ""
    out = name.replace("（", "(").replace("）", ")")
    for ch in ("【", "】", "·", '"', "'", " ", "\u3000"):
        out = out.replace(ch, "")
    return out.strip()


def build_nutrition_index(
    items: list[NutritionItem],
) -> tuple[dict[str, NutritionItem], dict[str, NutritionItem]]:
    """建立名称索引。

    Returns:
        (精确索引, 归一化索引)。两者分开是因为归一化匹配只是兜底，
        置信度低于精确匹配，输出时需要分别标注。
    """
    exact: dict[str, NutritionItem] = {}
    for item in items:
        if not item.nutrition_complete:
            continue
        exact.setdefault(item.product_name, item)

    normalized: dict[str, NutritionItem] = {}
    for item in exact.values():
        normalized.setdefault(normalize(item.product_name), item)
    return exact, normalized


@dataclass
class ChoiceNutrition:
    """套餐里一个选配项的营养解析结果。"""

    code: str
    name: str
    is_default: bool
    diff_price: str
    status: str
    nutrition: NutritionItem | None = None

    @property
    def resolved(self) -> bool:
        return self.nutrition is not None


@dataclass
class ComboNutrition:
    """一个套餐默认搭配的合计营养。"""

    combo_code: str
    combo_name: str
    choices: list[ChoiceNutrition] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """默认搭配是否全部命中。"""
        defaults = [c for c in self.choices if c.is_default]
        return bool(defaults) and all(c.resolved for c in defaults)

    @property
    def missing_names(self) -> list[str]:
        return [
            c.name
            for c in self.choices
            if c.is_default and not c.resolved
        ]

    def totals(self) -> dict[str, float | None]:
        """合计各项。任一默认项缺失则返回 None，不做部分求和。

        部分求和会低估热量或钠，给出偏乐观的结论，比不给数字更糟。
        """
        defaults = [c for c in self.choices if c.is_default]
        if not defaults or any(not c.resolved for c in defaults):
            return {}
        keys = ("energy_kcal", "protein", "fat", "carbohydrate", "sodium", "calcium")
        return {
            k: sum(getattr(c.nutrition, k) or 0.0 for c in defaults)
            for k in keys
        }


def resolve_choices(
    rounds: list[dict],
    exact_index: dict[str, NutritionItem],
    normalized_index: dict[str, NutritionItem],
) -> list[ChoiceNutrition]:
    """解析套餐各轮次的选配项营养。

    ``isDefault`` 的判断不能只依赖字段——实测存在 ``isDefault`` 缺失
    但该轮次只有一项的情况，此时该项就是默认项。
    """
    resolved: list[ChoiceNutrition] = []
    for round_data in rounds:
        choices = round_data.get("choices") or []
        if not choices:
            continue
        single = len(choices) == 1
        for choice in choices:
            is_default = bool(choice.get("isDefault")) or single
            resolved.append(
                _resolve_one(
                    choice,
                    is_default,
                    exact_index,
                    normalized_index,
                )
            )
    return resolved


def _resolve_one(
    choice: dict,
    is_default: bool,
    exact_index: dict[str, NutritionItem],
    normalized_index: dict[str, NutritionItem],
) -> ChoiceNutrition:
    name = (choice.get("name") or "").strip()
    code = str(choice.get("code") or "")
    diff = str(choice.get("diffPrice") or "")

    hit = exact_index.get(name)
    if hit is not None:
        return ChoiceNutrition(code, name, is_default, diff, MatchStatus.EXACT, hit)

    norm_hit = normalized_index.get(normalize(name))
    if norm_hit is not None:
        return ChoiceNutrition(
            code, name, is_default, diff, MatchStatus.NORMALIZED, norm_hit
        )

    return ChoiceNutrition(code, name, is_default, diff, MatchStatus.MISSING, None)


def summarize_combo(
    detail: dict,
    exact_index: dict[str, NutritionItem],
    normalized_index: dict[str, NutritionItem],
) -> ComboNutrition:
    """把 ``query-meal-detail`` 的返回整理成套餐营养摘要。"""
    return ComboNutrition(
        combo_code=str(detail.get("code") or ""),
        combo_name=(detail.get("name") or "").strip(),
        choices=resolve_choices(
            detail.get("rounds") or [],
            exact_index,
            normalized_index,
        ),
    )


def list_options(combo: ComboNutrition) -> list[ChoiceNutrition]:
    """列出可替换的选配项，供用户询问"换成哪个更清淡"。"""
    return [c for c in combo.choices if c.resolved]


# 供 CLI 输出参考：可选价格差里的差价符号
_DIFF_RE = re.compile(r"[+-]\s*¥?\s*([\d.]+)")


def parse_diff_price(diff: str) -> float | None:
    """把 "+ ¥1.5" / "- ¥1.5" 解析成带符号浮点数，无法解析返回 None。"""
    if not diff or diff in ("+ ¥0", "¥0"):
        return 0.0
    m = _DIFF_RE.search(diff)
    if not m:
        return None
    value = float(m.group(1))
    return -value if "-" in diff else value