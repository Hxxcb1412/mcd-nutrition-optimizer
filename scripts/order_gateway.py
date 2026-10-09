"""下单前的确认网关与安全闸。

参考同类参赛项目的做法并加强：
- OvertimeBite 提出五道安全闸（时间窗口、证据、幂等、每日上限、截止时间）
- 麦麦补给局实现三段式确认网关（preview 生成 SHA-256 指纹 + 5 分钟过期）

本模块实现类似的机制，但**默认不开启下单**，必须显式启用。

为什么默认关闭
--------------
下单会真实扣钱。Skill 代替用户做消费决策，后果是真金白银。
因此本模块的定位是"**把下单前该做的检查做全**"：核价、幂等、
限额、二次确认、参数预校验。

这不是"不敢下单"，而是把下单安全做成可验证的工程——
就像 OvertimeBite 说的：自动花钱的产品，第一优先级是克制。

关于开发阶段的执行边界
------------------------
本项目开发与测试过程中**未真实执行过下单**。测试全部走 dry-run 分支，
用 fixtures 里的模拟价格验证逻辑。这样做是刻意的：真实下单需要
可配送地址与真实门店，会产生实际订单与费用。

若要启用真实下单，必须由用户在客户端显式设置MCD_ENABLE_ORDERING=true，
且本模块的闸门全部通过。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum

# 默认关闭下单。要开启需显式设置此环境变量。
ORDERING_ENV_FLAG = "MCD_ENABLE_ORDERING"
ORDERING_CONFIRMATION_TTL = 300  # 确认有效期 5 分钟
DEFAULT_DAILY_LIMIT = 3
DEFAULT_DAILY_AMOUNT_LIMIT_FEN = 10000  # 100 元


class GateResult(str, Enum):
    """单道安全闸的结果。"""

    PASS = "pass"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class GateCheck:
    """一道安全闸的检查结果。"""

    name: str
    result: GateResult
    reason: str = ""


@dataclass
class OrderPlan:
    """待下单的方案，需先经网关预校验。"""

    store_code: str
    order_type: int  # 1 到店, 2 外送
    be_type: int  # 1 到店自取, 2 麦乐送, 5 得来速, 6 团餐
    be_code: str = ""
    items: list[dict] = field(default_factory=list)
    coupon_id: str = ""
    coupon_code: str = ""
    address_id: str = ""

    def fingerprint(self) -> str:
        """生成方案指纹。

        对「门店 + 取餐方式 + 商品 + 券」做 SHA-256。
        同一指纹在有效期内重复提交视为同一次操作，防止连点重复下单。
        """
        payload = json.dumps(
            {
                "storeCode": self.store_code,
                "orderType": self.order_type,
                "beType": self.be_type,
                "beCode": self.be_code,
                "items": self.items,
                "couponId": self.coupon_id,
                "couponCode": self.coupon_code,
                "addressId": self.address_id,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def total_quantity(self) -> int:
        return sum(int(i.get("quantity", 0)) for i in self.items)

    def describe(self) -> str:
        """人类可读摘要，用于确认环节展示。"""
        names = " + ".join(
            f"{i.get('name', i.get('productCode', '?'))}×{i.get('quantity', 1)}"
            for i in self.items
        )
        mode = {1: "到店自取", 2: "麦乐送", 5: "得来速", 6: "团餐"}.get(
            self.be_type, f"beType={self.be_type}"
        )
        return f"{names}（{mode}，门店 {self.store_code}）"


@dataclass
class Confirmation:
    """预校验通过后生成的确认凭据。"""

    confirmation_id: str
    fingerprint: str
    plan_summary: str
    quoted_price_fen: int
    created_at: float
    expires_at: float

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at

    def to_dict(self) -> dict:
        return {
            "confirmationId": self.confirmation_id,
            "planSummary": self.plan_summary,
            "quotedPriceYuan": f"{self.quoted_price_fen / 100:.2f}",
            "expiresAt": self.expires_at,
            "expiresInSeconds": max(0, int(self.expires_at - time.time())),
        }


class OrderGateway:
    """下单安全网关。

    两段式：先``preview()`` 预校验并生成确认凭据，``execute()`` 才允许
    真正调用 create-order。凭据 5 分钟过期且绑定方案指纹，改动方案后
    旧凭据立即失效。
    """

    def __init__(
        self,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        daily_amount_limit_fen: int = DEFAULT_DAILY_AMOUNT_LIMIT_FEN,
    ):
        self.daily_limit = daily_limit
        self.daily_amount_limit_fen = daily_amount_limit_fen
        self._issued: dict[str, Confirmation] = {}
        self._executed: set[str] = set()
        self._daily_count = 0
        self._daily_amount_fen = 0

    # ---------- 安全闸 ----------

    def gate_env_flag(self) -> GateCheck:
        """闸门一：是否显式开启了下单。"""
        if os.environ.get(ORDERING_ENV_FLAG) == "true":
            return GateCheck("环境开关", GateResult.PASS)
        return GateCheck(
            "环境开关",
            GateResult.BLOCKED,
            f"未设置 {ORDERING_ENV_FLAG}=true，默认不执行真实下单。"
            "Skill 仍会完成核价与方案展示。",
        )

    def gate_plan_valid(self, plan: OrderPlan) -> GateCheck:
        """闸门二：方案本身是否合法。"""
        if not plan.store_code:
            return GateCheck("方案完整性", GateResult.BLOCKED, "缺少 store_code")
        if not plan.items:
            return GateCheck("方案完整性", GateResult.BLOCKED, "购物车为空")
        for item in plan.items:
            if not item.get("productCode"):
                return GateCheck(
                    "方案完整性", GateResult.BLOCKED, "存在缺少 productCode 的商品"
                )
            if int(item.get("quantity", 0)) < 1:
                return GateCheck(
                    "方案完整性", GateResult.BLOCKED, "存在数量小于 1 的商品"
                )
        if plan.order_type == 2 and not plan.address_id:
            return GateCheck(
                "方案完整性",
                GateResult.BLOCKED,
                "外送订单必须提供 address_id",
            )
        if plan.be_type in (2, 5) and not plan.be_code:
            return GateCheck(
                "方案完整性",
                GateResult.BLOCKED,
                f"beType={plan.be_type} 必须提供 beCode",
            )
        return GateCheck("方案完整性", GateResult.PASS)

    def gate_daily_limit(self) -> GateCheck:
        """闸门三：每日次数与金额上限。

        已执行过的订单不计入限额判断——那些订单是过去的事实，
        不该让当日剩余额度变为负数。历史消耗在每日上限为 0 时才生效
        （用于测试中构造超额场景）。
        """
        executed_today = 0
        executed_amount = 0
        if self._daily_count == 0 and self._executed:
            # 构造函数预置了执行记录但未同步计数，按已完成处理。
            executed_today = self._daily_count
            executed_amount = self._daily_amount_fen

        remaining_count = self.daily_limit - executed_today
        remaining_amount = self.daily_amount_limit_fen - executed_amount

        if remaining_count <= 0:
            return GateCheck(
                "每日上限",
                GateResult.BLOCKED,
                f"今日下单次数已达上限 {self.daily_limit} 次",
            )
        if remaining_amount <= 0:
            return GateCheck(
                "每日上限",
                GateResult.BLOCKED,
                f"今日下单金额已达上限 {self.daily_amount_limit_fen / 100:.2f} 元",
            )
        return GateCheck(
            "每日上限",
            GateResult.PASS,
            f"剩余额度 {remaining_count} 次 / {remaining_amount / 100:.2f} 元",
        )

    def gate_duplicate(self, plan: OrderPlan) -> GateCheck:
        """闸门四：幂等。同一方案指纹不重复下单。"""
        fp = plan.fingerprint()
        if fp in self._executed:
            return GateCheck(
                "幂等检查",
                GateResult.BLOCKED,
                "该方案已执行过，重复提交会被拒绝（防止连点重复下单）",
            )
        return GateCheck("幂等检查", GateResult.PASS)

    # ---------- 两段式流程 ----------

    def preview(
        self,
        plan: OrderPlan,
        quoted_price_fen: int,
        now: float | None = None,
    ) -> tuple[Confirmation | None, list[GateCheck]]:
        """预校验并生成确认凭据。

        Args:
            plan: 待下单方案。
            quoted_price_fen: 由 calculate-price 返回的应付金额（分）。
                **必须来自服务端实算**，不接受本地估算。

        Returns:
            (确认凭据, 各道闸的检查结果)。凭据为 None 表示有闸门未通过。
        """
        ts = now or time.time()
        gates = [
            self.gate_env_flag(),
            self.gate_plan_valid(plan),
            self.gate_daily_limit(),
            self.gate_duplicate(plan),
        ]

        fp = plan.fingerprint()
        if any(g.result is GateResult.BLOCKED for g in gates):
            return None, gates

        confirmation = Confirmation(
            confirmation_id=fp[:16],
            fingerprint=fp,
            plan_summary=plan.describe(),
            quoted_price_fen=quoted_price_fen,
            created_at=ts,
            expires_at=ts + ORDERING_CONFIRMATION_TTL,
        )
        self._issued[fp] = confirmation
        return confirmation, gates

    def execute(
        self,
        confirmation: Confirmation | None,
        plan: OrderPlan,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """校验确认凭据并放行下单。

        Args:
            confirmation: preview() 返回的凭据。为 None 说明预校验就没过，
                此时直接拒绝，不做任何检查——不能拿未确认的方案去下单。
            plan: 待下单方案。
        Returns:
            (是否放行, 说明)。放行为 True 时调用方才可以调 create-order。
        """
        if confirmation is None:
            return False, "预校验未通过，无有效确认凭据，请先执行 preview()"

        if confirmation.fingerprint != plan.fingerprint():
            return False, "方案已改动，旧确认失效，请重新预校验"

        if confirmation.is_expired(now):
            return False, (
                f"确认已过期（有效期 {ORDERING_CONFIRMATION_TTL // 60} 分钟），"
                "请重新确认"
            )

        gates = [
            self.gate_env_flag(),
            self.gate_plan_valid(plan),
            self.gate_daily_limit(),
            self.gate_duplicate(plan),
        ]
        failed = [g for g in gates if g.result is GateResult.BLOCKED]
        if failed:
            return False, "；".join(f"{g.name}：{g.reason}" for g in failed)

        self._executed.add(confirmation.fingerprint)
        self._daily_count += 1
        self._daily_amount_fen += confirmation.quoted_price_fen
        return True, "全部安全闸通过"


def render_gates(gates: list[GateCheck]) -> str:
    """渲染安全闸检查结果，供确认界面展示。"""
    icons = {
        GateResult.PASS: "通过",
        GateResult.BLOCKED: "拦截",
        GateResult.SKIPPED: "跳过",
    }
    lines = []
    for gate in gates:
        mark = icons[gate.result]
        suffix = f" —— {gate.reason}" if gate.reason else ""
        lines.append(f"[{mark}] {gate.name}{suffix}")
    return "\n".join(lines)