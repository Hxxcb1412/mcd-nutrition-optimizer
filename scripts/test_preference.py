"""口语翻译档位测试。

这个模块的价值在于「用户说不出数字时怎么落到可计算的区间」，
所以测试重点不是数值本身对不对，而是：

  - 每种常见说法都能命中某个档位
  - **没有两个档位抢同一个词**——否则命中哪个取决于列表顺序，
    改顺序就改行为，这类隐式依赖很容易在后续维护中变成 bug
  - 未命中的表达返回 None，不硬套默认值
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from preference import (  # noqa: E402
    PREFERENCES,
    Preference,
    match,
    render_confirmation,
    render_translation_table,
    to_constraint,
)

PASSED = 0
FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    global PASSED
    if actual == expected:
        PASSED += 1
        print(f"  PASS {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}: {actual!r} != {expected!r}")


def test_known_phrases() -> None:
    """实测会用到的说法。"""
    print("\n[常见说法]")
    cases = [
        ("想吃得清淡点", "light"),
        ("清淡", "light"),
        ("别太咸", "light"),
        ("少盐", "light"),
        ("很清淡", "very_light"),
        ("严格控钠", "very_light"),
        ("低钠", "very_light"),
        ("控制体重", "low_kcal"),
        ("热量别高", "low_kcal"),
        ("别太撑", "low_kcal"),
        ("低卡", "low_kcal"),
        ("高蛋白", "high_protein"),
        ("健身", "high_protein"),
        ("增肌", "high_protein"),
        ("低脂", "low_fat"),
        ("少油", "low_fat"),
    ]
    for text, expected in cases:
        got = match(text)
        check(f"{text} → {expected}", got.key if got else None, expected)


def test_no_phrase_duplication() -> None:
    """档位之间不能共用关键词。

    这条是本模块最容易踩的坑：若两个档位都含"别太咸"，
    命中哪个完全取决于 PREFERENCES 的顺序，改顺序就改行为——
    而表面上看起来两句话都说得通。
    """
    print("\n[关键词不重复]")
    seen: dict[str, str] = {}
    clashes = []
    for pref in PREFERENCES:
        for phrase in pref.phrases:
            if phrase in seen and seen[phrase] != pref.key:
                clashes.append(f"{phrase!r}: {seen[phrase]} vs {pref.key}")
            seen[phrase] = pref.key
    check("无跨档位重复词", clashes, [])
    if clashes:
        for c in clashes:
            print(f"      冲突: {c}")

    # 档位 key 本身也不能重复
    keys = [p.key for p in PREFERENCES]
    check("档位 key 唯一", len(keys), len(set(keys)))


def test_unmatched_returns_none() -> None:
    """未命中返回 None——不要硬套默认值。"""
    print("\n[未命中不硬套]")
    for text in ("随便来点吃的", "", "我喜欢麦当劳", "今天天气不错"):
        check(f"{text!r} 返回 None", match(text), None)


def test_empty_input_safe() -> None:
    """空输入不崩。"""
    print("\n[边界]")
    check("空串安全", match(""), None)
    check("None 安全", match(None), None)
    check("纯空格不命中", match("   "), None)


def test_constraint_conversion() -> None:
    """档位转约束。"""
    print("\n[转约束]")
    light = match("清淡")
    c = to_constraint(light)
    check("默认档钠上限", c.max_sodium, 500.0)
    check("默认档不限制热量", c.max_kcal, None)

    strict = match("很清淡")
    check("严格档钠上限", to_constraint(strict).max_sodium, 300.0)

    kcal = match("控制体重")
    c2 = to_constraint(kcal)
    check("控热量档热量上限", c2.max_kcal, 500.0)

    protein = match("高蛋白")
    c3 = to_constraint(protein)
    check("高蛋白目标", c3.target_protein, 25.0)
    check("高蛋白是软目标", c3.strict_protein, False)

    fat = match("低脂")
    c4 = to_constraint(fat)
    check("低脂脂肪上限", c4.max_fat, 15.0)
    check("低脂是硬约束", c4.strict_protein, False)


def test_describe_is_readable() -> None:
    """描述要能直接给用户看。"""
    print("\n[描述可读性]")
    for pref in PREFERENCES:
        text = pref.describe()
        check(f"{pref.key} 描述非空", bool(text), True)
        check(f"{pref.key} 含数字", any(ch.isdigit() for ch in text), True)
        check(f"{pref.key} 带单位", "mg" in text or "kcal" in text or "g" in text, True)


def test_confirmation_asks_user() -> None:
    """确认话术必须体现「可调整」，不能让用户以为已定。"""
    print("\n[确认话术]")
    pref = match("清淡")
    text = render_confirmation(pref)
    check("含具体数值", "500" in text, True)
    check("含确认语气", "可以吗" in text, True)
    check("说明可调整", "调整" in text, True)


def test_table_rendering() -> None:
    """文档表格生成。"""
    print("\n[文档表格]")
    table = render_translation_table()
    lines = table.split("\n")
    check("含表头", lines[0].startswith("| 用户说"), True)
    check("含分隔行", set(lines[1].replace("|", "").strip()) <= {"-"}, True)
    check("每个档位一行", len(lines), len(PREFERENCES) + 2)
    for pref in PREFERENCES:
        check(f"{pref.key} 在表中", pref.describe() in table, True)


def test_determinism() -> None:
    """同样输入永远同样输出。"""
    print("\n[确定性]")
    texts = ["清淡", "很清淡", "高蛋白", "低脂", "随便"]
    first = [match(t).key if match(t) else None for t in texts]
    for _ in range(20):
        again = [match(t).key if match(t) else None for t in texts]
        if again != first:
            check("20 次一致", False, True)
            return
    check("20 次一致", True, True)


def main() -> int:
    print("=" * 58)
    print("口语翻译档位测试")
    print("=" * 58)
    test_known_phrases()
    test_no_phrase_duplication()
    test_unmatched_returns_none()
    test_empty_input_safe()
    test_constraint_conversion()
    test_describe_is_readable()
    test_confirmation_asks_user()
    test_table_rendering()
    test_determinism()

    print("\n" + "=" * 58)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSED} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())