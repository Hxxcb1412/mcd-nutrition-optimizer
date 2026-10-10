"""预检与钠账本模块测试。

全部基于真实实测夹具，不使用构造数据。
运行：python scripts/test_precheck.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from combo_resolver import build_nutrition_index  # noqa: E402,F401
from nutrition_solver import NutritionItem  # noqa: E402
from precheck import (  # noqa: E402
    Confidence,
    build_full_index,
    precheck,
    render,
)
from sodium_ledger import (  # noqa: E402
    DEFAULT_SODIUM_LIMIT_MG,
    SodiumLedger,
    render as render_ledger,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: 期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def _index() -> dict[str, NutritionItem]:
    """完整索引，保留占位记录——预检需要区分两种缺失原因。"""
    data = json.loads(
        (FIXTURES / "nutrition.json").read_text(encoding="utf-8")
    )
    return build_full_index(
        [NutritionItem.from_dict(i) for i in data["items"]]
    )


# ---------- 预检 ----------


def test_all_resolvable() -> None:
    print("\n[全部可算]")
    index = _index()
    r = precheck(["巨无霸", "中薯条", "可乐中杯"], index)
    check("结论为完整可信", r.confidence, Confidence.FULL)
    check("无未解析项", len(r.unresolved), 0)
    totals = r.computable_total()
    check("可算合计非空", totals is not None, True)
    # 巨无霸 513 + 中薯条 289 + 可乐 147 = 949（与套餐合计一致）
    check("合计热量", round(totals["energy_kcal"]), 949)
    check("合计钠", round(totals["sodium"]), 1126)


def test_partial_blocks_sum() -> None:
    print("\n[部分缺失时拒绝输出合计]")
    index = _index()
    # 活动新品，营养表未收录
    r = precheck(["龙焰鸡腿堡三件套", "中薯条", "可乐中杯"], index)
    check("结论为部分可信", r.confidence, Confidence.PARTIAL)
    check("合计为 None", r.computable_total(), None)
    check("给出拦截原因", "低估总热量" in r.blocking_reason(), True)


def test_all_unresolvable() -> None:
    print("\n[全部不可算]")
    index = _index()
    r = precheck(["龙焰鸡腿堡", "马苏里拉拉丝芝芝条"], index)
    check("结论为无法计算", r.confidence, Confidence.UNCOMPUTABLE)
    check("可解析项为空", len(r.resolved), 0)
    check("合计为 None", r.computable_total(), None)
    check("未收录分类", len(r.not_in_nutrition_table), 2)


def test_zero_value_placeholder_classified() -> None:
    print("\n[零值占位单独归类]")
    index = _index()
    # 纯悦与无糖可乐在营养表里是占位记录（热量与蛋白同时为 0）
    r = precheck(["纯悦", "巨无霸"], index)
    check("占位项被识别", len(r.zero_value_placeholder), 1)
    check("占位项不可算", r.zero_value_placeholder[0] in [i.name for i in r.unresolved], True)
    check("巨无霸仍可算", "巨无霸" in [i.name for i in r.resolved], True)


def test_quantities() -> None:
    print("\n[数量处理]")
    index = _index()
    r = precheck(["中薯条"], index, quantities={"中薯条": 2})
    check("数量记录正确", r.items[0].quantity, 2)
    # 单品时按数量累加
    check("合计按数量", round(r.computable_total()["energy_kcal"]), 578)


def test_empty_input() -> None:
    print("\n[空输入]")
    index = _index()
    r = precheck([], index)
    check("空输入判为无法计算", r.confidence, Confidence.UNCOMPUTABLE)
    check("合计为 None", r.computable_total(), None)
    check("拦截原因明确", r.blocking_reason(), "方案为空，没有可检查的餐品")


def test_render_no_placeholder_leak() -> None:
    print("\n[渲染不泄漏内部值]")
    index = _index()
    text = render(precheck(["巨无霸", "中薯条"], index))
    check("含完整可信", "完整可信" in text, True)
    check("含 kcal", "kcal" in text, True)

    text2 = render(precheck(["龙焰鸡腿堡三件套"], index))
    check("含无法计算", "无法计算" in text2, True)
    check("说明不输出部分和", "不输出" in text2, True)


# ---------- 钠账本 ----------


def test_ledger_accumulate() -> None:
    print("\n[账本累计]")
    L = SodiumLedger()
    L.add("巨无霸三件套", 1126, 949)
    L.add("麦乐鸡4块", 337, 170)
    check("累计钠", round(L.total_sodium), 1463)
    check("累计热量", round(L.total_kcal), 1119)
    check("剩余", round(L.remaining), 537)
    check("使用率", round(L.usage_pct), 73)
    check("状态", "距参考上限还有 537mg" in L.status(), True)


def test_ledger_over_limit() -> None:
    print("\n[超上限状态]")
    L = SodiumLedger()
    L.add("大餐", 2500, 2000)
    check("剩余为负", L.remaining < 0, True)
    check("状态提示超限", "已超过参考上限" in L.status(), True)


def test_ledger_custom_limit() -> None:
    print("\n[自定义上限]")
    L = SodiumLedger(limit_mg=1500.0)
    L.add("大餐", 1600, 1200)
    check("按自定义上限判定", "已超过" in L.status(), True)
    check("默认值不受影响", DEFAULT_SODIUM_LIMIT_MG, 2000.0)


def test_ledger_reset() -> None:
    print("\n[重置]")
    L = SodiumLedger()
    L.add("x", 100)
    L.reset()
    check("清空后无记录", len(L.entries), 0)
    check("清空后累计为 0", L.total_sodium, 0)


def test_ledger_empty_render() -> None:
    print("\n[空账本渲染]")
    text = render_ledger(SodiumLedger())
    check("提示无记录", "还没有记录" in text, True)
    check("说明依赖用户报告", "主动报告" in text, True)


def test_ledger_source_labelled() -> None:
    print("\n[数据来源标注]")
    index = _index()
    L = SodiumLedger()
    L.add_from_items("巨无霸三件套", [index["巨无霸"], index["中薯条"], index["可乐中杯"]])
    check("标注实测来源", L.entries[0].source, "本项目实测计算")
    check("按实测数据累计", round(L.total_sodium), 1126)


def main() -> int:
    print("=" * 58)
    print("预检与钠账本测试")
    print("=" * 58)
    test_all_resolvable()
    test_partial_blocks_sum()
    test_all_unresolvable()
    test_zero_value_placeholder_classified()
    test_quantities()
    test_empty_input()
    test_render_no_placeholder_leak()
    test_ledger_accumulate()
    test_ledger_over_limit()
    test_ledger_custom_limit()
    test_ledger_reset()
    test_ledger_empty_render()
    test_ledger_source_labelled()
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