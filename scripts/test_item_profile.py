"""菜品画像模块测试。

这个模块本身没有复杂逻辑，但它承载了一条被实测踩出来的规则：
类别判定的关键词表顺序即优先级。之前的 bug 是「纯牛奶」含"牛"、
「热浓浓抹茶牛奶」含"蛋"（浓**蛋**绿）先命中"蛋白"类，
于是「可乐大杯 + 纯牛奶」通过了儿童场景「必须含主食或蛋白」的校验。

所以这里不只测"能不能判对"，还要测**顺序约束本身不被破坏**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from item_profile import (  # noqa: E402
    CATEGORY_RULES,
    MEAL_CATEGORIES,
    category_of,
    categories_of,
    has_meal_component,
    icon_for,
    is_meal_item,
)

FIXTURES = ROOT / "tests" / "fixtures"

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


def test_every_record_classified() -> None:
    """全部营养记录都有类别。

    未归类不一定是错，但会让组合过滤器把它当"不属于任何类别"，
    实测历史上因此放过不合理的组合。
    """
    print("\n[全部营养记录已归类]")
    data = json.loads((FIXTURES / "nutrition.json").read_text(encoding="utf-8"))
    names = [i["productName"] for i in data["items"]]
    unclassified = [n for n in names if not category_of(n)]
    check(f"{len(names)} 条全部归类", len(unclassified), 0)
    if unclassified:
        for n in unclassified[:10]:
            print(f"      未归类: {n}")


def test_priority_order_is_stable() -> None:
    """关键词表顺序即优先级，奶品/饮品必须排在蛋白之前。

    这是实测踩过的坑：若蛋白优先，纯牛奶会因含"牛"被判成蛋白类。
    """
    print("\n[优先级：奶品与饮品必须先于蛋白]")
    order = [c for c, _ in CATEGORY_RULES]
    check("蛋白不在奶品之前", order.index("蛋白") > order.index("奶品"), True)
    check("蛋白不在饮品之前", order.index("蛋白") > order.index("饮品"), True)

    # 具体反例
    check("纯牛奶判为奶品", category_of("纯牛奶"), "奶品")
    check("纯牛奶不是蛋白", category_of("纯牛奶") == "蛋白", False)
    check("抹茶牛奶判为奶品", category_of("热浓浓抹茶牛奶大杯"), "奶品")
    check("抹茶牛奶不是蛋白", category_of("热浓浓抹茶牛奶大杯") == "蛋白", False)


def test_known_items() -> None:
    """实测数据里各档代表餐品的类别。"""
    print("\n[已知餐品类别]")
    cases = [
        ("巨无霸", "主食"),
        ("麦满分", "主食"),
        ("纯牛奶（盒装）", "奶品"),
        ("优品豆浆大杯", "奶品"),
        ("可乐大杯", "饮品"),
        ("大杯怡泉+C", "饮品"),
        ("冰美式小杯", "咖啡"),
        ("热奶铁中杯", "咖啡"),
        ("麦乐鸡4块", "蛋白"),
        ("儿童鱼排堡", "主食"),
        ("中薯条", "配菜"),
        ("草莓新地", "甜品"),
    ]
    for name, expected in cases:
        check(f"{name} → {expected}", category_of(name), expected)


def test_meal_component() -> None:
    """正餐主体判定。"""
    print("\n[正餐主体判定]")
    check("汉堡是正餐主体", is_meal_item("芝士安格斯厚牛堡"), True)
    check("鸡块是正餐主体", is_meal_item("麦乐鸡4块"), True)
    check("可乐不是正餐主体", is_meal_item("可乐大杯"), False)
    check("薯条不是正餐主体", is_meal_item("中薯条"), False)
    check("牛奶不是正餐主体", is_meal_item("纯牛奶（盒装）"), False)

    check("汉堡+可乐算一餐", has_meal_component(["芝士安格斯厚牛堡", "可乐大杯"]), True)
    check("可乐+薯条不算一餐", has_meal_component(["可乐大杯", "中薯条"]), False)
    check("三杯饮料不算一餐",
          has_meal_component(["可乐大杯", "冰美式小杯", "纯牛奶（盒装）"]), False)


def test_edge_cases() -> None:
    """空输入与未收录项。

    注意：类别判定只看名称关键词，与营养表是否收录该餐品无关。
    「龙焰鸡腿堡」虽未收录，但名称含"堡"，仍会被判成主食类。
    """
    print("\n[边界输入]")
    check("空串返回空类别", category_of(""), "")
    check("None 安全处理", category_of(None), "")
    check("空列表不构成一餐", has_meal_component([]), False)
    check("无任何关键词的串返回空类别", category_of("XYZ"), "")
    # 未收录新品仍按名称判类别——这正是「菜单能查到、营养表算不出」的情形
    check("未收录新品按名称仍判类别", category_of("龙焰鸡腿堡"), "主食")


def test_helpers() -> None:
    """辅助函数。"""
    print("\n[辅助函数]")
    check("批量取类别保持顺序",
          categories_of(["巨无霸", "可乐大杯", "麦乐鸡4块"]),
          ["主食", "饮品", "蛋白"])
    check("主食图标", icon_for("巨无霸"), "◆")
    check("蛋白图标", icon_for("麦乐鸡4块"), "●")
    check("未识别用中点", icon_for("XYZ"), "·")
    check("MEAL_CATEGORIES 内容", sorted(MEAL_CATEGORIES), ["主食", "蛋白"])


def test_determinism() -> None:
    """同样输入永远同样输出，不依赖字典遍历顺序。"""
    print("\n[确定性]")
    names = ["巨无霸", "可乐大杯", "麦乐鸡4块", "纯牛奶（盒装）", "中薯条"]
    first = [category_of(n) for n in names]
    for _ in range(20):
        if [category_of(n) for n in names] != first:
            check("多次调用结果一致", False, True)
            return
    check("20 次调用结果一致", True, True)


def main() -> int:
    print("=" * 58)
    print("菜品画像模块测试")
    print("=" * 58)
    test_every_record_classified()
    test_priority_order_is_stable()
    test_known_items()
    test_meal_component()
    test_edge_cases()
    test_helpers()
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