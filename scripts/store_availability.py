"""门店可购性判断。

`query-nearby-stores` 返回 `businessStatus: true` 只表示**门店存在**，
不代表当前处于营业时间。实测该门店08:00-22:00，另有门店 06:00-22:00，
若在清晨 7 点询问，前者`businessStatus` 仍为 true 但实际未营业。

因此判断「现在能不能买」必须用businessStartTime / businessEndTime
配合当前时间做区间比较，不能信 businessStatus。

这是本项目实测发现的坑，同类项目若直接用 businessStatus 判断会给出
错误答案——用户在凌晨 2 点看到"营业中"，白跑一趟。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass
class Store:
    """一家门店的可购性信息。"""

    store_code: str
    store_name: str
    address: str
    distance_m: int
    business_status: bool
    business_start: str  # "HH:MM"
    business_end: str
    be_code: str = ""
    supports_reservation: bool = False

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000

    def opening_time(self) -> time | None:
        return _parse_hhmm(self.business_start)

    def closing_time(self) -> time | None:
        return _parse_hhmm(self.business_end)

    def is_open_at(self, now: datetime) -> tuple[bool, str]:
        """判断指定时刻是否在营业时段内。

        Returns:
            (是否营业, 说明)。营业时段跨零点时按分段处理。
        """
        start = self.opening_time()
        end = self.closing_time()
        if start is None or end is None:
            return False, "营业时段信息缺失，无法判断"

        current = now.time()
        if start <= end:
            is_open = start <= current <= end
            window = f"{self.business_start}-{self.business_end}"
        else:
            # 跨零点营业，如 22:00-02:00
            is_open = current >= start or current <= end
            window = f"{self.business_start}-{self.business_end}（次日）"

        if is_open:
            return True, f"营业中（{window}）"
        return False, f"当前不在营业时段（{window}）"

    def distance_label(self) -> str:
        if self.distance_m < 1000:
            return f"{self.distance_m} 米"
        return f"{self.distance_km:.1f} 公里"


def _parse_hhmm(value: str) -> time | None:
    """解析 "HH:MM"。解析失败返回 None 而不是抛异常——
    营业时段缺失时应该保守地判为无法判断，而不是让整个查询崩掉。"""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def find_nearest_open(
    stores: list[Store],
    now: datetime,
    max_distance_m: int | None = None,
) -> tuple[Store | None, list[dict]]:
    """找出最近且当前营业的门店。

    Args:
        stores: 候选门店。
        now: 当前时间。
        max_distance_m: 可选的距离上限，超出的门店不考虑。

    Returns:
        (最近的可购门店, 每家门店的判定明细)。
        没有可用门店时第一个元素为 None，明细仍完整返回以便说明原因。
    """
    checked: list[dict] = []
    candidates: list[Store] = []

    for store in stores:
        is_open, reason = store.is_open_at(now)

        # 营业状态判断优先于距离——一家 3 公里外开着的店，
        # 比 100 米外已打烊的店更有用。
        row = {
            "storeCode": store.store_code,
            "storeName": store.store_name,
            "distance": store.distance_label(),
            "businessStatus": store.business_status,
            "openNow": is_open,
            "reason": reason,
            "withinRange": (
                max_distance_m is None or store.distance_m <= max_distance_m
            ),
        }
        checked.append(row)

        if not is_open:
            continue
        if not row["withinRange"]:
            continue
        if not store.business_status:
            continue
        candidates.append(store)

    if not candidates:
        return None, checked

    candidates.sort(key=lambda s: s.distance_m)
    return candidates[0], checked


def render_selection(
    nearest: Store | None,
    checked: list[dict],
    now: datetime,
) -> str:
    """渲染可购性判断结果。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("门店可购性判断")
    add("=" * 58)
    add(f"判断时刻：{now.strftime('%Y-%m-%d %H:%M')}")
    add("")
    add("【逐店判定】")
    for row in sorted(checked, key=lambda r: r["distance"]):
        flag = "营业中" if row["openNow"] else "未营业"
        add(f"  {row['distance']:>8}　{row['storeName']}")
        add(f"            {flag}　{row['reason']}")

    add("")
    add("【结论】")
    if nearest is None:
        add("  当前距离范围内没有营业中的门店。")
        add("  注意：接口返回的 businessStatus=true 只表示门店存在，")
        add("  不代表此刻在营业——本判断用的是营业时段时间比较。")
    else:
        add(f"  推荐：{nearest.store_name}（{nearest.distance_label()}）")
        add(f"  地址：{nearest.address}")
        _, reason = nearest.is_open_at(now)
        add(f"  状态：{reason}")
        add(f"  storeCode：{nearest.store_code}")
        if nearest.be_code:
            add(f"  beCode：{nearest.be_code}")
    add("")
    add("=" * 58)
    return "\n".join(lines)