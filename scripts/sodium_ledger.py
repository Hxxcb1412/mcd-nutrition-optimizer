"""钠的累计账本。

定位说明
--------
这是**附带能力**，不是独立功能。用户不主动报告就不启用，
不要求每餐手动记录——那个交互成本高到没人会坚持用。

与 `precheck.py` 的关系
---------------------
`precheck` 负责判断"这份方案哪些算得出"，
本模块负责"把已经算得出的部分累计起来"。

数据边界（必须说清楚）
---------------------
**MCP 没有任何个人健康数据源。** 没有体重、没有步数、没有体检报告。
`order-list`（历史订单）不返回营养字段，而营养表没有编码字段，
两者无法可靠关联——所以本模块**完全依赖用户主动报告**。

参考上限从哪来
--------------
成人每日钠参考上限 2000mg 来自通用膳食参考值，**非麦当劳官方数据，
非医疗建议**。用户可以覆盖这个值（比如医生给了不同建议）。

不给出的结论
------------
本模块**不判断**"你今天该不该再吃麦当劳"。
它只做算术：摄入累计是多少，距离参考上限还有多少。
消费建议不属于数据计算能得出的结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nutrition_solver import NutritionItem

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# 通用膳食参考值，非麦当劳官方
DEFAULT_SODIUM_LIMIT_MG = 2000.0
THRESHOLD_NOTE = "通用膳食参考值，非麦当劳官方数据，非医疗建议"


@dataclass
class IntakeEntry:
    """一次摄入记录。"""

    label: str
    sodium_mg: float
    kcal: float = 0.0
    source: str = "用户报告"

    @property
    def detail(self) -> str:
        if self.kcal:
            return f"{self.sodium_mg:.0f}mg 钠 · {self.kcal:.0f} kcal"
        return f"{self.sodium_mg:.0f}mg 钠"


@dataclass
class SodiumLedger:
    """钠摄入账本。

    设计成会话级：用户说"今天吃了 X"就加一条，问"还剩多少"就给结论。
    不做跨会话持久化——那需要额外存储且会让用户失去对数据的掌控感。
    """

    limit_mg: float = DEFAULT_SODIUM_LIMIT_MG
    entries: list[IntakeEntry] = field(default_factory=list)

    @property
    def total_sodium(self) -> float:
        return sum(e.sodium_mg for e in self.entries)

    @property
    def total_kcal(self) -> float:
        return sum(e.kcal for e in self.entries)

    @property
    def remaining(self) -> float:
        return self.limit_mg - self.total_sodium

    @property
    def usage_pct(self) -> float:
        # 上限为 0 或负数时返回 0 而不是崩溃或返回 inf。
        # 但此时 status() 会明确提示"上限设置有问题"，不掩盖异常。
        if self.limit_mg <= 0:
            return 0.0
        return self.total_sodium / self.limit_mg * 100

    def add(
        self,
        label: str,
        sodium_mg: float,
        kcal: float = 0.0,
        source: str = "用户报告",
    ) -> None:
        """记一笔。

        Args:
            label: 餐品或组合名。
            sodium_mg: 钠含量，必须来自本项目其他模块的实测计算，
                不接受用户口述的估值。
            kcal: 热量，同上。
            source: 数据来源标注。

        Raises:
            ValueError: 钠或热量为负。这两个值来自营养表，
                负数意味着上游数据有问题，静默接受会让账本失真。
        """
        if sodium_mg < 0 or kcal < 0:
            raise ValueError(
                f"「{label}」的钠({sodium_mg})与热量({kcal})不能为负，"
                f"这说明上游数据异常，请先检查"
            )
        self.entries.append(IntakeEntry(label, float(sodium_mg), float(kcal), source))

    def add_from_items(
        self,
        label: str,
        items: list[NutritionItem],
        source: str = "本项目实测计算",
    ) -> None:
        """从已算出营养的餐品列表记一笔。"""
        self.add(
            label,
            sum(i.sodium or 0.0 for i in items),
            sum(i.energy_kcal or 0.0 for i in items),
            source,
        )

    def status(self) -> str:
        """当前状态的客观描述。"""
        if self.limit_mg <= 0:
            return f"参考上限设置异常（{self.limit_mg:.0f}mg），无法判断"
        pct = self.usage_pct
        if pct >= 100:
            return f"已超过参考上限（{pct:.0f}%）"
        if pct >= 80:
            return f"接近参考上限（{pct:.0f}%）"
        return f"距参考上限还有 {self.remaining:.0f}mg"

    def reset(self) -> None:
        """清空（用户说"重置"或换一天时）。"""
        self.entries.clear()


def render(ledger: SodiumLedger) -> str:
    """渲染账本。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("钠摄入账本")
    add("=" * 58)
    add("")

    if not ledger.entries:
        add("还没有记录。")
        add("")
        add("用法：告诉我你吃了什么，比如「刚吃了巨无霸三件套」，")
        add("我会用本项目的实测数据算出钠含量并累计。")
        add("")
        add("说明：MCP 接口没有个人健康数据，这完全依赖你主动报告。")
        add("")
        add("=" * 58)
        return "\n".join(lines)

    add("【已记录】")
    for entry in ledger.entries:
        add(f"  · {entry.label:<20} {entry.detail}")
        add(f"    {'':<20} （{entry.source}）")
    add("")

    add("【累计】")
    add(f"  钠　　{ledger.total_sodium:.0f} mg")
    add(f"  热量　{ledger.total_kcal:.0f} kcal")
    add(f"  参考上限　{ledger.limit_mg:.0f} mg")
    add(f"  状态　{ledger.status()}")
    add("")

    bar_width = min(30, int(ledger.usage_pct / 5))
    filled = "█" * bar_width
    empty = "░" * (30 - bar_width)
    add(f"  [{filled}{empty}] {ledger.usage_pct:.0f}%")
    add("")

    add("【说明】")
    add(f"  参考上限 {ledger.limit_mg:.0f}mg 来自{THRESHOLD_NOTE}。")
    add("  如果你有医生给出的不同建议，告诉我具体数值即可替换。")
    add("")
    add("  本模块只做累计，不判断'今天该不该再吃'——")
    add("  那不是数据计算能得出的结论。")
    add("")
    add("=" * 58)
    return "\n".join(lines)

def main() -> int:
    """命令行入口。

    用实测营养数据演示钠账本：把一个真实套餐拆成几笔记进去，
    看累计值与参考上限的关系。参考上限是通用膳食值，非麦当劳官方。
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="钠累计账本")
    parser.add_argument(
        "--nutrition",
        type=Path,
        default=FIXTURES / "nutrition.json",
        help="营养表数据",
    )
    parser.add_argument(
        "--limit",
        type=float,
        default=DEFAULT_SODIUM_LIMIT_MG,
        help=f"每日参考上限（mg），默认 {DEFAULT_SODIUM_LIMIT_MG:.0f}",
    )
    parser.add_argument(
        "--items",
        nargs="+",
        default=["巨无霸", "中薯条", "可乐中杯"],
        help="依次记入的餐品名，默认巨无霸三件套的三项",
    )
    args = parser.parse_args()

    if not args.nutrition.exists():
        print(f"找不到文件：{args.nutrition}")
        return 1

    data = json.loads(args.nutrition.read_text(encoding="utf-8"))
    index = {i["productName"]: NutritionItem.from_dict(i) for i in data["items"]}

    ledger = SodiumLedger(limit_mg=args.limit)
    missing: list[str] = []
    for name in args.items:
        item = index.get(name)
        if item is None or not item.nutrition_complete:
            missing.append(name)
            continue
        ledger.add_from_items(name, [item])
    print(render(ledger))

    if missing:
        print()
        print("以下餐品无法计入（营养表未收录或为占位记录）：")
        for name in missing:
            print(f"  {name}")
        print("这不是工具故障，是数据现状——如实列出而不估算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
