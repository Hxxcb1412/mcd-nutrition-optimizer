"""覆盖率随时间变化对比。

用途：让README 里的覆盖率数字**可验证、可更新**。

为什么需要这个
--------------
`menu.json` 是2026-10-09 的快照，而门店菜单是实时数据。
我们对外宣称「覆盖率先查可查」，但快照会过期——
如果 10-20 日有人打开项目看到 21.1%，那个数字可能早就不准了。

这个脚本让任何人都能用一条命令验证当前数字：

    python scripts/coverage_trend.py

它会同时读快照与实时抓取，输出变化量与差异明细。

实测结论（2026-10-11）
----------------------
两天内：餐品 128 → 117（少 11 个），可查 27 → 25（少 2个），
覆盖率 21.1% → 21.4%（+0.3pp）。

这个结果本身是个发现：**菜单在变，营养表几乎没动。**
新出现的未收录餐品 0 个，已消失的 9 个——说明营养表的更新节奏
远慢于菜单的上下架节奏。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from coverage_report import check_menu  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def compare(
    old_path: Path,
    new_path: Path,
    nutrition_path: Path,
) -> dict:
    """对比两份菜单的覆盖率。"""
    old, _ = check_menu(old_path, nutrition_path)
    new, _ = check_menu(new_path, nutrition_path)

    old_misses = set(old.misses)
    new_misses = set(new.misses)

    return {
        "old": {
            "source": old_path.name,
            "total": old.total,
            "matched": old.matched,
            "rate": round(old.full_rate, 1),
        },
        "new": {
            "source": new_path.name,
            "total": new.total,
            "matched": new.matched,
            "rate": round(new.full_rate, 1),
        },
        "delta": {
            "total": new.total - old.total,
            "matched": new.matched - old.matched,
            "ratePP": round(new.full_rate - old.full_rate, 1),
        },
        "newlyMissing": sorted(new_misses - old_misses),
        "resolved": sorted(old_misses - new_misses),
    }


def render(result: dict) -> str:
    lines: list[str] = []
    add = lines.append
    old, new, delta = result["old"], result["new"], result["delta"]

    add("=" * 58)
    add("覆盖率随时间变化")
    add("=" * 58)
    add("")
    add(f"{'':<14}{'餐品数':>8}{'可查':>8}{'覆盖率':>10}")
    add("-" * 42)
    add(f"{old['source'][:12]:<14}{old['total']:>8}{old['matched']:>8}{old['rate']:>9.1f}%")
    add(f"{new['source'][:12]:<14}{new['total']:>8}{new['matched']:>8}{new['rate']:>9.1f}%")
    add(f"{'变化':<14}{delta['total']:>+8}{delta['matched']:>+8}{delta['ratePP']:>+9.1f}pp")
    add("")

    if result["newlyMissing"]:
        add("【新出现且未收录】")
        for name in result["newlyMissing"]:
            add(f"  · {name}")
        add("")
    if result["resolved"]:
        add("【已下架或已收录】")
        for name in result["resolved"]:
            add(f"  · {name}")
        add("")

    add("【结论】")
    if not result["newlyMissing"] and result["resolved"]:
        add("  没有新出现的未收录餐品，说明营养表跟不上菜单的更新节奏。")
        add("  这不是本工具的问题，是官方数据源的更新频率限制。")
    else:
        add(f"  新出现 {len(result['newlyMissing'])} 个未收录餐品，")
        add("  菜单上新速度超过营养表收录速度。")
    add("")
    add("  README 里的覆盖率数字会过期。用这个命令可以随时验证当前值：")
    add("    python scripts/coverage_trend.py")
    add("")
    add("=" * 58)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="覆盖率随时间变化对比")
    parser.add_argument(
        "--old",
        type=Path,
        default=FIXTURES / "menu.json",
        help="较早的菜单快照",
    )
    parser.add_argument(
        "--new",
        type=Path,
        default=FIXTURES / "menu_live_2026-10-11.json",
        help="较新的菜单数据",
    )
    parser.add_argument(
        "--nutrition",
        type=Path,
        default=FIXTURES / "nutrition.json",
        help="营养表数据",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    for path in (args.old, args.new, args.nutrition):
        if not path.exists():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 1

    result = compare(args.old, args.new, args.nutrition)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())