"""Smoke test：对实测夹具跑基线，验证 README 里的每个数字可复现。

本脚本不需要 MCP 连接，直接读 tests/fixtures/ 下的真实抓取数据。
若麦当劳官方更新了营养数据，本脚本会失败——那时应重新抓取夹具
并更新基线，而不是修改断言让它重新通过。

运行：python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from combo_resolver import build_nutrition_index, summarize_combo  # noqa: E402
from nutrition_solver import (  # noqa: E402
    Constraint,
    NutritionItem,
    Solver,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# README 里引用的基线数字。改动算法时这些断言会失败——
# 这是预期的：README 的数字必须跟着算法一起变。
BASELINE = {
    "combo_9900005466": {
        "name": "巨无霸三件套",
        "kcal": 949,
        "protein": 31,
        "sodium": 1126,
        "complete": True,
    },
    "combo_9900000884": {
        "name": "酥酥多笋卷四件套",
        "kcal": 948,
        "protein": 28,
        "sodium": 1546,
        "complete": True,
    },
    "combo_9900013304": {
        "name": "人气经典随心配",
        "complete": False,
        "missing": "可乐麦炫酷",
    },
}

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: 期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def _load_nutrition() -> list[NutritionItem]:
    data = json.loads(
        (FIXTURES / "nutrition.json").read_text(encoding="utf-8")
    )
    return [NutritionItem.from_dict(i) for i in data["items"]]


def test_nutrition_baseline() -> None:
    print("\n[营养表基线]")
    data = json.loads(
        (FIXTURES / "nutrition.json").read_text(encoding="utf-8")
    )
    check("记录数", data["recordCount"], 160)
    check("唯一名称数", data["uniqueCount"], 158)
    check(
        "零值条目数",
        len(data["zeroEnergyItems"]),
        4,
    )

    items = _load_nutrition()
    complete = [i for i in items if i.nutrition_complete]
    check("完整数据条目数", len(complete), 156)

    excluded = {i.product_name for i in items if not i.nutrition_complete}
    check(
        "被排除的4 条",
        sorted(excluded),
        sorted(data["zeroEnergyItems"]),
    )


def test_combo_baseline() -> None:
    print("\n[套餐拆解基线]")
    details = json.loads(
        (FIXTURES / "meal_details.json").read_text(encoding="utf-8")
    )
    exact, normalized = build_nutrition_index(_load_nutrition())

    seen_codes = set()
    for detail in details["details"]:
        code = f"combo_{detail['code']}"
        if code not in BASELINE:
            continue
        seen_codes.add(code)
        expected = BASELINE[code]
        combo = summarize_combo(detail, exact, normalized)

        check(f"{expected['name']} 完整性", combo.complete, expected["complete"])

        if expected["complete"]:
            totals = combo.totals()
            check(
                f"{expected['name']} 热量",
                round(totals["energy_kcal"]),
                expected["kcal"],
            )
            check(
                f"{expected['name']} 蛋白",
                round(totals["protein"]),
                expected["protein"],
            )
            check(
                f"{expected['name']} 钠",
                round(totals["sodium"]),
                expected["sodium"],
            )
        else:
            check(
                f"{expected['name']} 缺失项",
                combo.missing_names,
                [expected["missing"]],
            )
            check(
                f"{expected['name']} 不输出部分和",
                combo.totals(),
                {},
            )

    check("覆盖全部基线套餐", seen_codes, set(BASELINE))


def test_solver_baseline() -> None:
    print("\n[求解器基线]")
    solver = Solver(_load_nutrition())

    # README：热量 ≤ 600、高蛋白 ≥ 25g
    result = solver.solve(
        Constraint(max_kcal=600, target_protein=25, strict_protein=True),
        max_items=3,
        limit=1,
    )
    if result:
        combo = result[0]
        check(
            "高蛋白场景首解热量",
            round(combo.total_kcal),
            513,
        )
        check(
            "高蛋白场景首解蛋白",
            round(combo.total_protein),
            25,
        )
        check(
            "高蛋白场景首解钠",
            round(combo.total_sodium),
            173,
        )
    else:
        check("高蛋白场景有解", "no result", "1 combination")


def test_solver_stability() -> None:
    print("\n[确定性复现]")
    items = _load_nutrition()
    constraint = Constraint(max_sodium=500, max_kcal=600)

    first = Solver(items).solve(constraint, max_items=3, limit=5)
    second = Solver(list(reversed(items))).solve(constraint, max_items=3, limit=5)
    check(
        "输入顺序不影响结果",
        [_sig(c) for c in first],
        [_sig(c) for c in second],
    )


def _sig(combo) -> tuple:
    return (
        tuple(sorted(i.product_name for i in combo.items)),
        round(combo.total_kcal),
        round(combo.total_sodium),
    )


def test_no_fake_zero() -> None:
    print("\n[零值保护]")
    solver = Solver(_load_nutrition())
    results = solver.solve(Constraint(max_kcal=200), max_items=3, limit=50)
    names = {i.product_name for c in results for i in c.items}
    check("零热量条目未混入", "无糖可口可乐中杯" in names, False)
    check("纯悦未混入", "纯悦" in names, False)


def main() -> int:
    print("=" * 60)
    print("mcd-nutrition-optimizer smoke test")
    print(f"夹具目录：{FIXTURES}")
    print("=" * 60)
    test_nutrition_baseline()
    test_combo_baseline()
    test_solver_baseline()
    test_solver_stability()
    test_no_fake_zero()
    print("\n" + "=" * 60)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        print("\n提示：若官方营养数据更新导致基线变化，")
        print("应重新抓取 tests/fixtures/ 并更新断言，")
        print("不要修改断言让它重新通过。")
        return 1
    print("全部通过，README 中的数字均可复现")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())