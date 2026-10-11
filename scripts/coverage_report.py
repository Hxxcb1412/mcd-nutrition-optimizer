"""门店营养覆盖率体检。

麦当劳官方营养表是静态快照，门店菜单是实时数据，两者的重合度有限。
本脚本对指定门店做一次覆盖率体检，回答三个问题：

1. 这个门店有多少餐品能找到营养数据？
2. 找不到的那些，为什么找不到？
3. 套餐拆解后能不能凑出完整营养账本？

这不是查菜单比价，而是**数据质量检查**。用途是让用户在使用前就知道
哪些餐品能算、哪些不能算，避免把 0 当成零热量来决策。

实测参考值（2026-10-09，门店 1950526）：
- 精确同名 21/128 = 16.4%
- 剥规格后缀后 26/128 = 20.3%
- 再叠加括号归一化 27/128 = 21.1%

运行：
    python scripts/coverage_report.py
    python scripts/coverage_report.py --menu path/to/menu.json
    python scripts/coverage_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from combo_resolver import (  # noqa: E402
    build_nutrition_index,
    normalize,
    summarize_combo,
)
from nutrition_solver import NutritionItem  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# 规格后缀：菜单按商品聚合（"可乐"），营养表按规格展开（"可乐中杯"）。
# 剥掉后缀能提升匹配率，但会丢失杯型信息——同一个"可乐"对应中/大/小杯
# 三条记录，钠含量不同，因此命中多候选时必须显式报告候选数而非取第一条。
#
# 只认真正的杯型词。不能把任意单字都当规格剥离：早期版本用 ("中","大","小")
# 结尾匹配，会把「纯牛奶(盒装)」的"装"剥成「纯牛奶(盒」，导致归一化能命中的
# 条目被误判成规格歧义。
SPEC_SUFFIXES = ("中大杯", "中杯", "大杯", "小杯", "超大杯", "中", "大", "小")


def strip_spec(name: str) -> str:
    """剥掉规格后缀用于匹配尝试。"""
    if not name:
        return ""
    out = normalize(name)
    for suffix in SPEC_SUFFIXES:
        if out.endswith(suffix) and len(out) > len(suffix):
            out = out[: -len(suffix)]
            break
    return out


class CoverageReport:
    """覆盖率体检结果。"""

    def __init__(self) -> None:
        self.total = 0
        self.exact_hits: list[str] = []
        self.spec_hits: dict[str, list[str]] = {}
        self.normalized_hits: dict[str, str] = {}
        self.misses: list[str] = []
        # 品类口径的出现次数。同一套餐挂在多个分类下会重复计数，
        # 这个数字与 total（门店口径）不同是正常的，不是数据错误。
        self.category_slots = 0

    @property
    def matched(self) -> int:
        return len(self.exact_hits) + len(self.spec_hits) + len(self.normalized_hits)

    @property
    def exact_rate(self) -> float:
        return self._rate(len(self.exact_hits))

    @property
    def spec_rate(self) -> float:
        return self._rate(len(self.exact_hits) + len(self.spec_hits))

    @property
    def full_rate(self) -> float:
        return self._rate(self.matched)

    def _rate(self, hits: int) -> float:
        return (hits / self.total * 100) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "totalMeals": self.total,
            "matched": self.matched,
            "exactHits": len(self.exact_hits),
            "specHits": len(self.spec_hits),
            "normalizedHits": len(self.normalized_hits),
            "exactRatePct": round(self.exact_rate, 1),
            "specRatePct": round(self.spec_rate, 1),
            "fullRatePct": round(self.full_rate, 1),
            "missingCount": len(self.misses),
            "categorySlots": self.category_slots,
            "missingItems": sorted(self.misses),
            "ambiguousItems": {
                k: sorted(v) for k, v in sorted(self.spec_hits.items())
            },
        }


def extract_menu_meals(menu: dict) -> tuple[list[str], int]:
    """从菜单数据里取出餐品名列表。

    支持两种结构——这是实测踩到的坑：

    **真实 query-meals 返回**：`data.meals` 是 `code -> 详情` 的**字典**，
    且同一个 code 会出现在多个 `categories[]` 里（套餐会同时挂在
    「巨无霸牛鱼肉堡」和「精选单人餐」下）。

    **早期手工整理的夹具**：`meals` 是**列表**，每项自带 categories 字段。

    返回 (去重后的餐品名, 品类口径的出现次数)。两个口径不同不是数据错误，
    是菜单的组织方式：用户关心"能不能买到并算出营养"，所以覆盖率用去重口径。

    实测 2026-10-11 同一门店：去重 117 个，品类口径 128 个次。
    """
    data = menu.get("data", menu)
    meals = data.get("meals")

    if isinstance(meals, dict):
        # 真实 API 结构：字典，按 code 去重
        names = [
            detail["name"]
            for detail in meals.values()
            if isinstance(detail, dict) and detail.get("name")
        ]
        slots = sum(
            len(cat.get("meals") or [])
            for cat in (data.get("categories") or [])
            if isinstance(cat, dict)
        )
        return names, slots

    # 手工整理的夹具结构：列表
    names = [
        (m.get("name") or "").strip()
        for m in (meals or [])
        if isinstance(m, dict)
    ]
    slots = len(names)
    return names, slots


def check_menu(
    menu_path: Path,
    nutrition_path: Path,
) -> tuple[CoverageReport, dict]:
    """对一份菜单做覆盖率体检。

    Returns:
        (覆盖率报告, 套餐拆解摘要)
    """
    nutrition = json.loads(nutrition_path.read_text(encoding="utf-8"))
    menu = json.loads(menu_path.read_text(encoding="utf-8"))

    items = [NutritionItem.from_dict(i) for i in nutrition["items"]]
    exact_index, normalized_index = build_nutrition_index(items)

    # 规格归并索引：剥后缀后的小写名 -> 命中的营养表条目列表
    spec_index: dict[str, list[NutritionItem]] = {}
    for item in exact_index.values():
        key = strip_spec(item.product_name).lower()
        spec_index.setdefault(key, []).append(item)

    report = CoverageReport()
    names, slots = extract_menu_meals(menu)
    report.category_slots = slots

    for raw_name in names:
        name = (raw_name or "").strip()
        if not name:
            continue
        report.total += 1

        if name in exact_index:
            report.exact_hits.append(name)
            continue

        # 归一化优先于规格剥离。「纯牛奶(盒装)」的归一化键与规格键相同，
        # 若先查规格索引会被误归成"规格歧义"，而它其实只是全角括号差异。
        norm_hit = normalized_index.get(normalize(name))
        if norm_hit is not None:
            report.normalized_hits[name] = norm_hit.product_name
            continue

        spec_key = strip_spec(name).lower()
        candidates = spec_index.get(spec_key, [])
        if candidates:
            report.spec_hits[name] = [c.product_name for c in candidates]
            continue

        report.misses.append(name)

    combo_summary = _check_combos(menu, nutrition_path, exact_index, normalized_index)
    return report, combo_summary


def _check_combos(
    menu: dict,
    nutrition_path: Path,
    exact_index: dict[str, NutritionItem],
    normalized_index: dict[str, NutritionItem],
) -> dict:
    """检查套餐类餐品能否拆出完整营养账本。

    套餐本身不是营养条目，必须靠 meal_details.json 提供的 rounds 展开。
    没抓过该套餐详情时如实说明，不做估算。
    """
    detail_path = nutrition_path.parent / "meal_details.json"
    result = {
        "comboCount": 0,
        "detailsAvailable": detail_path.exists(),
        "resolved": 0,
        "incomplete": 0,
        "missingComponents": {},
    }
    if not detail_path.exists():
        return result

    details = json.loads(detail_path.read_text(encoding="utf-8"))
    for detail in details.get("details", []):
        result["comboCount"] += 1
        combo = summarize_combo(detail, exact_index, normalized_index)
        if combo.complete:
            result["resolved"] += 1
        else:
            result["incomplete"] += 1
            for name in combo.missing_names:
                result["missingComponents"][name] = (
                    result["missingComponents"].get(name, 0) + 1
                )

    menu_combos = sum(
        1
        for m in menu.get("meals", [])
        if str(m.get("code") or "").startswith("99")
    )
    result["menuComboCount"] = menu_combos
    return result


def render(
    report: CoverageReport,
    combo: dict,
    menu_path: Path,
    label: str = "",
) -> str:
    """渲染成可读报告。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("门店营养覆盖率体检")
    add("=" * 58)
    add(f"菜单来源：{label or menu_path.name}")
    add("")
    add(f"门店餐品总数：{report.total}")
    if report.category_slots and report.category_slots != report.total:
        add(
            f"（菜单品类口径 {report.category_slots} 个位置——"
            f"套餐会挂在多个分类下，这是正常的）"
        )
    add("")
    add("【匹配层级】")
    add(f"  精确同名        {len(report.exact_hits):>4} 个  {report.exact_rate:>5.1f}%")
    add(f"  + 剥规格后缀    {len(report.spec_hits):>4} 个  {report.spec_rate:>5.1f}%")
    add(
        f"  + 括号归一化    {len(report.normalized_hits):>4} 个  {report.full_rate:>5.1f}%"
    )
    add("")
    add(f"完全无营养数据  {len(report.misses):>4} 个")
    add("")
    add("【结论】")
    if report.full_rate < 50:
        add(f"  覆盖率偏低。菜单里约 {100 - report.full_rate:.0f}% 的餐品无法计算营养，")
        add("  原因是官方营养表滞后于菜单上架。这些餐品不会出现在推荐里，")
        add("  求解器也不会用 0 代替——那会给出偏乐观的错误结论。")
    else:
        add(f"  覆盖率 {report.full_rate:.1f}%，大部分餐品可计算营养。")
    add("")

    if report.spec_hits:
        add("【规格歧义：这些餐品对应多个营养表条目】")
        for menu_name, candidates in sorted(report.spec_hits.items()):
            add(f"  {menu_name}")
            add(f"    -> {', '.join(candidates)}")
        add("  以上需按实际杯型选取，钠含量随规格不同。")
        add("")

    add("【套餐拆解】")
    if not combo.get("detailsAvailable"):
        add("  未找到 meal_details.json，无法检查套餐拆解。")
    else:
        add(f"  已检查 {combo['comboCount']} 个套餐样例")
        add(f"  完整   {combo['resolved']}")
        add(f"  不完整 {combo['incomplete']}")
        if combo.get("missingComponents"):
            add("  缺失子项：")
            for name, count in combo["missingComponents"].items():
                add(f"    {name}（出现在 {count} 个套餐中）")
    add("")
    add("=" * 58)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="门店营养覆盖率体检"
    )
    parser.add_argument(
        "--menu",
        type=Path,
        default=FIXTURES / "menu.json",
        help="menu.json 路径",
    )
    parser.add_argument(
        "--nutrition",
        type=Path,
        default=FIXTURES / "nutrition.json",
        help="nutrition.json 路径",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出，便于程序消费",
    )
    parser.add_argument(
        "--label",
        default="",
        help="报告中显示的数据来源说明，如抓取日期与门店编码",
    )
    args = parser.parse_args()

    for path in (args.menu, args.nutrition):
        if not path.exists():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 1

    report, combo = check_menu(args.menu, args.nutrition)

    if args.json:
        payload = report.to_dict()
        payload["comboAnalysis"] = combo
        payload["source"] = args.label or args.menu.name
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(report, combo, args.menu, args.label))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())