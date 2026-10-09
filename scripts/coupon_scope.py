"""券适用性与营养可算性检查。

用 `query-store-coupons` 拿到的券自带 `products[].productCode`，
本模块反向检查：**这张券适用的餐品，哪些能在官方营养表里查到数据。**

为什么是这个方向
----------------
最初设想是「用券后重算营养」，但实测发现：
- `available-coupons` 返回的是 Markdown 图文列表，**只有券名**，
  没有 couponId、面额、有效期、适用商品，无法参与计算
- `query-store-coupons` 结构完整（含 products[].productCode），
  但测试账号在测试门店返回空数组

在拿不到面额与适用商品的情况下，"券后重算"只能靠猜，会给出错误的
价格与营养结论。所以改做**券适用性检查**——这个方向只需要
productCode，是工具真实返回的结构，不依赖任何猜测。

它回答一个实际存在的问题：**你有一张券，但券适用的餐品营养表没收录，
这单点了算不清楚。**

另外，本模块会把活动日历提到的新品与营养表比对——
实测发现两者高度重合，详见 `campaign_gap.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nutrition_solver import NutritionItem


@dataclass
class CouponScope:
    """一张券的适用范围。"""

    coupon_id: str
    coupon_code: str
    title: str
    valid_until: str = ""
    product_codes: list[str] = field(default_factory=list)
    product_names: list[str] = field(default_factory=list)


@dataclass
class CouponCoverage:
    """券适用范围与营养表的交集分析。"""

    coupon: CouponScope
    matched: list[tuple[str, str]] = field(default_factory=list)
    # (productCode, productName) 有营养数据
    unmatched: list[tuple[str, str]] = field(default_factory=list)
    # (productCode, productName) 无营养数据

    @property
    def total_products(self) -> int:
        """券声明的限定商品总数。"""
        return len(self.coupon.product_codes)

    @property
    def is_fully_covered(self) -> bool:
        """券的适用范围是否完全能被营养表覆盖。"""
        return self.total_products > 0 and not self.unmatched

    @property
    def has_any_coverage(self) -> bool:
        return bool(self.matched)

    def summary(self) -> str:
        total = self.total_products
        if total == 0:
            return "该券未声明限定商品"
        if self.is_fully_covered:
            return f"{total} 个限定商品全部可算营养"
        if self.has_any_coverage:
            return (
                f"{len(self.matched)}/{total} 个可算，"
                f"{len(self.unmatched)} 个营养表无数据"
            )
        return f"{total} 个限定商品全部无法计算营养"


def check_coupon(
    raw: dict,
    nutrition_index: dict[str, NutritionItem],
) -> CouponCoverage:
    """检查单张券的适用范围能否被营养表覆盖。

    Args:
        raw: query-store-coupons 返回的单条记录。
        nutrition_index: 名称 -> NutritionItem 的索引。
    """
    products = raw.get("products") or []
    codes: list[str] = []
    names: list[str] = []
    for p in products:
        code = str(p.get("productCode") or "")
        name = (p.get("productName") or "").strip()
        if code:
            codes.append(code)
        if name:
            names.append(name)

    coupon = CouponScope(
        coupon_id=str(raw.get("couponId") or ""),
        coupon_code=str(raw.get("couponCode") or ""),
        title=(raw.get("title") or "").strip(),
        valid_until=str(raw.get("tradeDateTime") or ""),
        product_codes=codes,
        product_names=names,
    )

    coverage = CouponCoverage(coupon=coupon)
    for code, name in zip(codes, names):
        item = nutrition_index.get(name)
        if item is not None and item.nutrition_complete:
            coverage.matched.append((code, name))
        else:
            coverage.unmatched.append((code, name))

    return coverage


def check_all(
    coupons_raw: list[dict],
    nutrition_index: dict[str, NutritionItem],
) -> list[CouponCoverage]:
    """检查一批券，返回覆盖情况列表。

    门店无券时返回空列表——这本身就是一个有效结论，
    调用方应如实告知用户该门店当前无可用券，而不是报错。
    """
    return [check_coupon(raw, nutrition_index) for raw in coupons_raw]


def render(covs: list[CouponCoverage]) -> str:
    """渲染券适用性检查结果。"""
    lines: list[str] = []
    add = lines.append

    add("=" * 58)
    add("券适用性检查")
    add("=" * 58)
    add("")

    if not covs:
        add("该门店当前没有可用的优惠券。")
        add("")
        add("这是接口返回的真实状态（data 为空数组），不是查询失败。")
        add("无券时求解结果不依赖优惠逻辑，可直接展示营养方案。")
        add("")
        add("=" * 58)
        return "\n".join(lines)

    for cov in covs:
        flag = "完整可算" if cov.is_fully_covered else "存在缺口"
        add(f"【{cov.coupon.title}】{flag}")
        if cov.coupon.valid_until:
            add(f"  有效期：{cov.coupon.valid_until}")
        add(f"  {cov.summary()}")
        for code, name in cov.matched:
            add(f"    [可算] {name}（{code}）")
        for code, name in cov.unmatched:
            add(f"    [缺数据] {name}（{code}）")
        add("")

    add("【说明】")
    add("  「缺数据」表示该券限定的餐品在官方营养表里没有收录，")
    add("  用券下单后无法计算其营养值。本项目不会用估算值代替，")
    add("  遇到这类餐品会明确说明而非给出可能错误的数字。")
    add("")
    add("=" * 58)
    return "\n".join(lines)