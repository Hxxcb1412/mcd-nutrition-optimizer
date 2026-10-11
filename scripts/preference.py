"""口语偏好到数值约束的翻译。

用户说不出钠的具体毫克数，但能说"清淡"。这个模块把这类模糊表达
落到可计算的区间，让求解器拿到确定的约束。

**这些档位是本项目的产品决策，不是营养学标准。** 它们的作用是把
常见说法映射到一组可讨论的数字，随后必须向用户确认。数值本身
不构成医疗或营养建议。

原先这些档位只写在 SKILL.md 的 Markdown 表格里，代码中没有对应定义——
改档位要手动同步两处，且没有任何机制保证一致。现在它们在这里定义，
文档表格由 `render_translation_table()` 生成，见 SKILL.md 的引用说明。

数值参考《中国居民膳食指南》成人一般性建议，非麦当劳官方数据。
"""

from __future__ import annotations

from dataclasses import dataclass

# 钠：WHO 建议成人每日 < 2000mg，此处 1500 作为"清淡"档位。
# 蛋白质：健身人群常用 1.2-1.6 g/kg，25g 对应约 20kg 体重的一餐。
# 脂肪：占总热量 20-30%，600kcal 餐食下约 13-20g。


@dataclass(frozen=True)
class Preference:
    """一条口语表达对应的约束档位。"""

    key: str
    phrases: tuple[str, ...]
    summary: str
    max_sodium: float | None = None
    max_kcal: float | None = None
    target_protein: float | None = None
    strict_protein: bool = False
    max_fat: float | None = None
    level: str = "默认档位"

    def describe(self) -> str:
        """人类可读描述，用于向用户复述。"""
        parts = []
        if self.max_sodium is not None:
            parts.append(f"钠 ≤ {self.max_sodium:.0f}mg")
        if self.max_kcal is not None:
            parts.append(f"热量 ≤ {self.max_kcal:.0f}kcal")
        if self.target_protein is not None:
            kind = "硬目标" if self.strict_protein else "软目标"
            parts.append(f"蛋白质{kind} ≥ {self.target_protein:.0f}g")
        if self.max_fat is not None:
            parts.append(f"脂肪 ≤ {self.max_fat:.0f}g")
        return "、".join(parts)


# 档位表。顺序即匹配优先级：更具体的表达排在前面，
# "很清淡" 必须先于 "清淡" 被匹配，否则严格档永远命中不了。
PREFERENCES: tuple[Preference, ...] = (
    Preference(
        key="very_light",
        phrases=("很清淡", "特别清淡", "控钠", "低钠", "钠要低", "严格控钠"),
        summary="严格控钠",
        max_sodium=300.0,
        level="严格档位",
    ),
    Preference(
        key="light",
        phrases=("清淡", "别太咸", "少盐", "口味轻", "清淡点"),
        summary="默认控钠",
        max_sodium=500.0,
        level="默认档位",
    ),
    Preference(
        key="low_kcal",
        phrases=("控体重", "控制体重", "控制热量", "热量别高", "别太撑",
                 "低卡", "减肥餐"),
        summary="控制热量",
        max_kcal=500.0,
        level="默认档位",
    ),
    Preference(
        key="high_protein",
        phrases=("高蛋白", "健身", "增肌", "蛋白质"),
        summary="高蛋白软目标",
        max_kcal=600.0,
        target_protein=25.0,
        level="软目标",
    ),
    Preference(
        key="low_fat",
        phrases=("低脂", "少油", "脂肪别高"),
        summary="脂肪硬约束",
        max_kcal=600.0,
        max_fat=15.0,
        level="硬约束",
    ),
)


def match(text: str) -> Preference | None:
    """从用户原话里识别偏好档位。

    未命中返回 None——不要硬套默认值，让用户把话说具体。

    Args:
        text: 用户的自然语言输入，如"想吃得清淡点"。

    Returns:
        命中的档位；没识别出来时返回 None。
    """
    if not text:
        return None
    for pref in PREFERENCES:
        if any(p in text for p in pref.phrases):
            return pref
    return None


def to_constraint(pref: Preference):
    """把档位转成求解器的 Constraint。

    Args:
        pref: match() 返回的档位。

    Returns:
        nutrition_solver.Constraint 实例。
    """
    from nutrition_solver import Constraint

    return Constraint(
        max_sodium=pref.max_sodium,
        max_kcal=pref.max_kcal,
        target_protein=pref.target_protein,
        strict_protein=pref.strict_protein,
        max_fat=pref.max_fat,
    )


def render_translation_table() -> str:
    """生成文档用的档位对照表。

    SKILL.md 里的翻译表应当与此保持一致，改档位只需改这里。
    """
    lines = ["| 用户说 | 翻译为 | 依据 |", "|---|---|---|"]
    for pref in PREFERENCES:
        lines.append(f"| {pref.phrases[0]} 等 | {pref.describe()} | {pref.level} |")
    return "\n".join(lines)


def render_confirmation(pref: Preference) -> str:
    """生成向用户复述的确认话术。

    翻译后必须让用户确认，不要静默套用默认值。
    """
    return (
        f'我理解为「{pref.describe()}」，这样安排可以吗？\n'
        f"（{pref.level}，可按你的实际情况调整）"
    )