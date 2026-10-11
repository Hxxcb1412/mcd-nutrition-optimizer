"""覆盖率趋势对比测试。

关键验证点：**两种菜单结构都要支持**。
实测发现真实 query-meals 返回的data.meals 是字典，
而早期手工整理的夹具是列表——这是踩过的坑。

运行：python scripts/test_coverage_trend.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from coverage_report import check_menu, extract_menu_meals  # noqa: E402
from coverage_trend import compare, render  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: 期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def test_dict_structure() -> None:
    print("\n[真实 API 结构：meals 是字典]")
    import json

    raw = json.loads(
        (FIXTURES / "menu_live_2026-10-11.json").read_text(encoding="utf-8")
    )
    names, slots = extract_menu_meals(raw)
    check("提取出餐品", len(names) > 0, True)
    check("无重复（按 code 去重）", len(names), len(set(names)))
    check("品类口径更大", slots > len(names), True)


def test_list_structure() -> None:
    print("\n[手工整理结构：meals 是列表]")
    import json

    raw = json.loads((FIXTURES / "menu.json").read_text(encoding="utf-8"))
    names, slots = extract_menu_meals(raw)
    check("提取出餐品", len(names) > 0, True)
    check("列表结构下两个口径相同", slots, len(names))


def test_live_coverage() -> None:
    print("\n[实时数据覆盖率]")
    report, _ = check_menu(
        FIXTURES / "menu_live_2026-10-11.json", FIXTURES / "nutrition.json"
    )
    check("门店口径 117", report.total, 117)
    check("品类口径 128", report.category_slots, 128)
    check("可查 25 个", report.matched, 25)
    check("覆盖率 21.4%", round(report.full_rate, 1), 21.4)


def test_snapshot_compat() -> None:
    print("\n[旧快照仍可用]")
    report, _ = check_menu(
        FIXTURES / "menu.json", FIXTURES / "nutrition.json"
    )
    check("128 餐品", report.total, 128)
    check("27 可查", report.matched, 27)
    check("21.1%", round(report.full_rate, 1), 21.1)


def test_trend() -> None:
    print("\n[趋势对比]")
    r = compare(
        FIXTURES / "menu.json",
        FIXTURES / "menu_live_2026-10-11.json",
        FIXTURES / "nutrition.json",
    )
    check("快照 21.1%", r["old"]["rate"], 21.1)
    check("实时 21.4%", r["new"]["rate"], 21.4)
    check("变化 +0.3pp", r["delta"]["ratePP"], 0.3)
    check("餐品减少 11", r["delta"]["total"], -11)
    check("无新出现的未收录", len(r["newlyMissing"]), 0)
    check("9 个已下架或已收录", len(r["resolved"]), 9)

    text = render(r)
    check("渲染含验证提示", "随时验证当前值" in text, True)


def main() -> int:
    print("=" * 58)
    print("覆盖率趋势测试")
    print("=" * 58)
    test_dict_structure()
    test_list_structure()
    test_live_coverage()
    test_snapshot_compat()
    test_trend()
    print("\n" + "=" * 58)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for n in FAILED:
            print(f"  - {n}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())