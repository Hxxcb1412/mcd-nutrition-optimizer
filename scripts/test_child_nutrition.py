"""儿童营养模块测试。

用例基于真实营养表数据，重点验证两类问题：
1. 阈值分段与来源标注是否正确
2. 儿童场景不会出现"纯饮品冒充一餐"这类不当结果

运行：python scripts/test_child_nutrition.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from child_nutrition import (  # noqa: E402
    AGE_PROFILES,
    THRESHOLD_SOURCE,
    detect_gaps,
    get_profile,
    resolve_age_band,
    solve_for_child,
)
from nutrition_solver import NutritionItem, _category_of  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: 期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def load() -> list[NutritionItem]:
    data = json.loads(
        (FIXTURES / "nutrition.json").read_text(encoding="utf-8")
    )
    return [NutritionItem.from_dict(i) for i in data["items"]]


def test_age_band() -> None:
    print("\n[年龄段映射]")
    check("3 岁", resolve_age_band(3), "3-6")
    check("6 岁", resolve_age_band(6), "3-6")
    check("7 岁", resolve_age_band(7), "7-12")
    check("12 岁", resolve_age_band(12), "7-12")
    check("13 岁", resolve_age_band(13), "13-17")
    check("17 岁", resolve_age_band(17), "13-17")
    check("18 岁超出范围", resolve_age_band(18), "")
    check("0 岁非法", resolve_age_band(0), "")


def test_profile_source_labeled() -> None:
    print("\n[来源标注]")
    profile, msg = get_profile(9)
    check("9 岁取到档案", profile is not None, True)
    check("无提示语", msg, "")
    check("标记为仅供参考", profile.reference_only, True)
    check(
        "阈值来源标明非官方",
        "非麦当劳官方" in profile.threshold_source,
        True,
    )
    check(
        "营养来源标明实测",
        "实测" in profile.nutrition_source,
        True,
    )


def test_out_of_range() -> None:
    print("\n[超出年龄范围]")
    profile, msg = get_profile(25)
    check("成年人返回 None", profile is None, True)
    check("提示切换到通用求解", "成人" in msg, True)

    combos_prof, combos, msg2 = solve_for_child(load(), 25)
    check("无解返回空列表", combos, [])
    check("给出原因", "3-17" in msg2 or "成人" in msg2, True)


def test_child_no_beverage_only() -> None:
    print("\n[儿童场景不得出现纯饮品组合]")
    items = load()
    for age in (4, 9, 15):
        profile, combos, _ = solve_for_child(items, age)
        if profile is None or not combos:
            print(f"  SKIP  {age} 岁无解，跳过")
            continue
        for combo in combos:
            categories = [_category_of(i.product_name) for i in combo.items]
            has_staple = any(
                c in ("主食", "蛋白") for c in categories
            )
            drinks = categories.count("饮品")
            check(
                f"{age}岁组合含主食或蛋白 [{combo.items[0].product_name}]",
                has_staple,
                True,
            )
            check(
                f"{age}岁组合饮品≤1 [{combo.items[0].product_name}]",
                drinks <= 1,
                True,
            )


def test_no_spurious_zero_nutrition() -> None:
    print("\n[零值条目不得进入儿童方案]")
    items = load()
    for age in (4, 9, 15):
        _, combos, _ = solve_for_child(items, age)
        names = {i.product_name for c in combos for i in c.items}
        check(f"{age}岁不含无糖可乐", "无糖可口可乐中杯" in names, False)
        check(f"{age}岁不含纯悦", "纯悦" in names, False)


def test_determinism() -> None:
    print("\n[确定性]")
    items = load()
    _, first, _ = solve_for_child(items, 9)
    _, second, _ = solve_for_child(list(reversed(items)), 9)
    check(
        "输入顺序不影响结果",
        [" + ".join(i.product_name for i in c.items) for c in first],
        [" + ".join(i.product_name for i in c.items) for c in second],
    )


def test_gaps_reported() -> None:
    print("\n[菜单缺口如实报告]")
    items = load()
    profile, _ = get_profile(4)
    gaps = detect_gaps(profile, items)
    check("学龄前段有缺口提示", len(gaps) > 0, True)
    check(
        "缺口提示含钠超标事实",
        any("钠" in g for g in gaps),
        True,
    )


def test_all_profiles_have_note() -> None:
    print("\n[阈值档案完整性]")
    for band, spec in AGE_PROFILES.items():
        check(f"{band} 有说明", bool(spec.get("note")), True)
        check(
            f"{band} 钠上限为正",
            spec["max_sodium"] > 0,
            True,
        )
        check(
            f"{band} 热量下限低于上限",
            spec["min_kcal"] < spec["max_kcal"],
            True,
        )


def main() -> int:
    print("=" * 58)
    print("儿童营养模块测试")
    print("=" * 58)
    test_age_band()
    test_profile_source_labeled()
    test_out_of_range()
    test_child_no_beverage_only()
    test_no_spurious_zero_nutrition()
    test_determinism()
    test_gaps_reported()
    test_all_profiles_have_note()
    print("\n" + "=" * 58)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())