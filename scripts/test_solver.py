"""单元测试：TOON 解析与求解器行为。

这些用例全部基于实测抓取的真实数据形态，不使用构造的假数据。
运行：python scripts/test_solver.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from nutrition_solver import (  # noqa: E402
    Constraint,
    NutritionItem,
    Solver,
)
from parse_nutrition import NutritionParseError, parse_toon  # noqa: E402

# 实测 TOON 片段：猪柳麦满分 308kcal/16g 蛋白/781mg 钠，纯牛奶（盒装）129kcal
REAL_TOON_SAMPLE = """[4]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  纯牛奶（盒装）,null,541,129,7,7,10,105,230
  无糖可口可乐中杯,null,0,0,0,0,1,2,0
  板烧鸡腿堡,null,1638,391,24,15,44,1010,60
"""

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}:期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def test_toon_parse() -> None:
    print("\n[TOON 解析]")
    items = parse_toon(REAL_TOON_SAMPLE)
    check("记录数", len(items), 4)
    check("字段数", len(items[0]), 9)
    check(
        "首个餐品名",
        items[0]["productName"],
        "猪柳麦满分",
    )
    check(
        "能量转 int",
        items[0]["energyKcal"],
        308,
    )
    check(
        "钠值",
        items[0]["sodium"],
        781,
    )
    check(
        "null 转 None",
        items[0]["nutritionDescription"],
        None,
    )


def test_toon_errors() -> None:
    print("\n[TOON 异常处理]")
    try:
        parse_toon("")
        check("空文本应报错", "no raise", "NutritionParseError")
    except NutritionParseError:
        check("空文本应报错", "NutritionParseError", "NutritionParseError")

    truncated = "".join(REAL_TOON_SAMPLE.splitlines(keepends=True)[:3])
    try:
        parse_toon(truncated)
        check("数量不符应报错", "no raise", "NutritionParseError")
    except NutritionParseError as exc:
        check("数量不符应报错", "声明 4 条" in str(exc), True)


def test_zero_energy_is_missing_not_zero() -> None:
    print("\n[零值必须是缺失不是零]")
    items = parse_toon(REAL_TOON_SAMPLE)
    by_name = {i["productName"]: NutritionItem.from_dict(i) for i in items}

    cola = by_name["无糖可口可乐中杯"]
    check("零卡可乐标记为数据缺失", cola.nutrition_complete, False)
    milk = by_name["纯牛奶（盒装）"]
    check("纯牛奶是正常数据", milk.nutrition_complete, True)
    burger = by_name["板烧鸡腿堡"]
    check("汉堡是正常数据", burger.nutrition_complete, True)


def test_solver_excludes_incomplete() -> None:
    print("\n[求解器排除数据缺失条目]")
    items = [NutritionItem.from_dict(i) for i in parse_toon(REAL_TOON_SAMPLE)]
    solver = Solver(items)
    combos = solver.solve(Constraint(max_kcal=600), max_items=2, limit=20)

    for combo in combos:
        for item in combo.items:
            check(
                f"不应含 {item.product_name}",
                item.nutrition_complete,
                True,
            )


def test_solver_sodium_priority() -> None:
    print("\n[钠优先排序]")
    items = [NutritionItem.from_dict(i) for i in parse_toon(REAL_TOON_SAMPLE)]
    solver = Solver(items)
    combos = solver.solve(Constraint(max_kcal=600), max_items=1, limit=10)

    if len(combos) >= 2:
        check("第一条钠更低", combos[0].total_sodium <= combos[1].total_sodium, True)
        check(
            "第一条是纯牛奶（可乐缺数据已被排除）",
            combos[0].items[0].product_name,
            "纯牛奶（盒装）",
        )
        check(
            "无糖可乐不出现在结果里",
            any("无糖" in i.product_name for c in combos for i in c.items),
            False,
        )
    else:
        print("  SKIP  可用单品不足 2 条，跳过排序断言")


def test_solver_determinism() -> None:
    print("\n[确定性]")
    items = [NutritionItem.from_dict(i) for i in parse_toon(REAL_TOON_SAMPLE)]
    solver = Solver(items)
    constraint = Constraint(max_kcal=800, target_protein=20)
    first = solver.solve(constraint, max_items=3, limit=5)
    second = Solver(list(reversed(items))).solve(constraint, max_items=3, limit=5)
    check(
        "输入顺序不同结果一致",
        [_names(c) for c in first],
        [_names(c) for c in second],
    )
    check(
        "组合内餐品按名称排序",
        all(
            [i.product_name for i in c.items]
            == sorted(i.product_name for i in c.items)
            for c in first
        ),
        True,
    )


def test_infeasible_returns_empty() -> None:
    print("\n[不可行约束返回空]")
    items = [NutritionItem.from_dict(i) for i in parse_toon(REAL_TOON_SAMPLE)]
    solver = Solver(items)
    combos = solver.solve(Constraint(max_kcal=1), max_items=1)
    check("热量上限 1 大卡应无解", combos, [])


def _names(combo) -> list[str]:
    return [i.product_name for i in combo.items]


def main() -> int:
    print("=" * 56)
    print("mcd-nutrition-optimizer 单元测试")
    print("=" * 56)
    test_toon_parse()
    test_toon_errors()
    test_zero_energy_is_missing_not_zero()
    test_solver_excludes_incomplete()
    test_solver_sodium_priority()
    test_solver_determinism()
    test_infeasible_returns_empty()
    print("\n" + "=" * 56)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())