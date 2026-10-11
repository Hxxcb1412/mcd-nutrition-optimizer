"""下单安全网关测试。

这个模块是全项目唯一会触及真实下单的代码，四道安全闸任一失效都可能
真的扣钱。它此前**没有任何测试覆盖**——之前的验证是在交互式脚本里手工
跑的，从未进入测试套件，意味着后续任何改动都不会被自动验证。

测试原则：**不调用 create-order，不发任何网络请求**。所有验证都在
`preview()` / `execute()` 的本地判定逻辑内完成，`execute()` 返回 True
只代表"允许调用方下单"，不代表真的下过单。

环境开关的处理：`gate_env_flag` 读`MCD_ENABLE_ORDERING` 环境变量。
测试用显式设置/恢复的方式覆盖两种状态，不依赖测试机的环境。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from order_gateway import (  # noqa: E402
    ORDERING_CONFIRMATION_TTL,
    ORDERING_ENV_FLAG,
    Confirmation,
    GateResult,
    OrderGateway,
    OrderPlan,
    render_gates,
)

PASSED = 0
FAILED: list[str] = []

STORE = "1950526"
ITEM = {"productCode": "9900005466", "quantity": 1, "name": "巨无霸三件套"}


def check(label: str, actual, expected) -> None:
    global PASSED
    if actual == expected:
        PASSED += 1
        print(f"  PASS {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}: {actual!r} != {expected!r}")


def with_ordering(enabled: bool):
    """构造一个下单开关处于指定状态的网关。"""
    if enabled:
        os.environ[ORDERING_ENV_FLAG] = "true"
    else:
        os.environ.pop(ORDERING_ENV_FLAG, None)
    return OrderGateway(daily_limit=5, daily_amount_limit_fen=100_000)


def plan(**kw) -> OrderPlan:
    """构造一份合法方案，可覆盖任意字段。"""
    args = {
        "store_code": STORE,
        "order_type": 1,
        "be_type": 1,
        "items": [dict(ITEM)],
    }
    args.update(kw)
    return OrderPlan(**args)


def blocked_reasons(gates) -> str:
    return " ".join(g.reason for g in gates if g.result is GateResult.BLOCKED)


# ---------- 闸门一：环境开关 ----------

def test_env_flag_blocks_by_default() -> None:
    """默认状态必须拦截——这是最重要的一条。"""
    print("\n[闸门一：环境开关]")
    os.environ.pop(ORDERING_ENV_FLAG, None)
    gw = OrderGateway()
    gate = gw.gate_env_flag()
    check("未设置环境变量时拦截", gate.result, GateResult.BLOCKED)
    check("拦截理由点名环境变量", ORDERING_ENV_FLAG in gate.reason, True)

    # 任何非 "true" 的取值都必须拦截，不能是"真值即通过"
    for bad in ("false", "TRUE", "1", "yes", "True "):
        os.environ[ORDERING_ENV_FLAG] = bad
        g = OrderGateway().gate_env_flag()
        check(f"取值 {bad!r} 被拦截", g.result, GateResult.BLOCKED)

    os.environ[ORDERING_ENV_FLAG] = "true"
    check("严格等于 'true' 才放行",
          OrderGateway().gate_env_flag().result, GateResult.PASS)
    os.environ.pop(ORDERING_ENV_FLAG, None)


# ---------- 闸门二：方案完整性 ----------

def test_plan_validation() -> None:
    """方案本身的合法性检查。"""
    print("\n[闸门二：方案完整性]")
    gw = with_ordering(True)

    cases = [
        ("缺少 store_code", plan(store_code=""), "store_code"),
        ("购物车为空", plan(items=[]), "购物车"),
        ("商品缺 productCode",
         plan(items=[{"quantity": 1, "name": "无编码"}]), "productCode"),
        ("数量为 0",
         plan(items=[{**ITEM, "quantity": 0}]), "数量小于 1"),
        ("数量为负",
         plan(items=[{**ITEM, "quantity": -1}]), "数量小于 1"),
        ("外送缺 address_id",
         plan(order_type=2, address_id=""), "address_id"),
        ("得来速缺 beCode",
         plan(be_type=2, be_code=""), "beCode"),
        ("麦咖啡缺 beCode",
         plan(be_type=5, be_code=""), "beCode"),
    ]
    for label, p, keyword in cases:
        gate = gw.gate_plan_valid(p)
        check(f"{label}被拦截", gate.result, GateResult.BLOCKED)
        check(f"{label}的理由含「{keyword}」", keyword in gate.reason, True)

    # 合法方案必须放行，且内送不要求 address_id
    check("合法方案放行", gw.gate_plan_valid(plan()).result, GateResult.PASS)
    check("堂食不需要 address_id",
          gw.gate_plan_valid(plan(order_type=1)).result, GateResult.PASS)


# ---------- 闸门三：每日限额 ----------

def test_daily_limits() -> None:
    """次数与金额双上限。"""
    print("\n[闸门三：每日限额]")

    gw = OrderGateway(daily_limit=2, daily_amount_limit_fen=100_000)
    for i in range(2):
        p = plan(items=[{**ITEM, "quantity": i + 1}])
        c, _ = gw.preview(p, 1000)
        ok, _ = gw.execute(c, p)
        check(f"第 {i + 1} 单放行", ok, True)

    p = plan(items=[{**ITEM, "quantity": 3}])
    c, gates = gw.preview(p, 1000)
    check("超出次数上限时凭据为 None", c is None, True)
    check("拦截理由是次数", "次数" in blocked_reasons(gates), True)

    # 金额上限：单笔就击穿上限必须被拦
    gw2 = OrderGateway(daily_limit=10, daily_amount_limit_fen=500)
    p2 = plan(items=[{**ITEM, "quantity": 9}])
    c2, gates2 = gw2.preview(p2, 800)
    check("单笔超每日金额上限被拦截", c2 is None, True)
    check("拦截理由是金额", "上限" in blocked_reasons(gates2), True)
    check("理由含本单金额", "8.00" in blocked_reasons(gates2), True)

    # 累计：两单各 300 分，第二单时累计 600 > 500 应被拦
    gw3 = OrderGateway(daily_limit=10, daily_amount_limit_fen=500)
    pa = plan(items=[{**ITEM, "quantity": 1}])
    ca, _ = gw3.preview(pa, 300)
    check("第一单 300 分放行", gw3.execute(ca, pa)[0], True)
    pb = plan(items=[{**ITEM, "quantity": 2}])
    cb, gb = gw3.preview(pb, 300)
    check("累计超限被拦截", cb is None, True)
    check("累计拦截理由含已花金额", "3.00" in blocked_reasons(gb), True)

    # 恰好用满额度应放行（边界）
    gw4 = OrderGateway(daily_limit=10, daily_amount_limit_fen=500)
    pc = plan(items=[{**ITEM, "quantity": 6}])
    cc, _ = gw4.preview(pc, 500)
    check("恰好用满额度放行", cc is not None, True)


# ---------- 闸门四：幂等 ----------

def test_idempotency() -> None:
    """同一方案指纹不重复下单。"""
    print("\n[闸门四：幂等]")
    gw = with_ordering(True)

    p = plan(items=[{**ITEM, "quantity": 7}])
    c, _ = gw.preview(p, 3000)
    ok, _ = gw.execute(c, p)
    check("首次执行放行", ok, True)

    p2 = plan(items=[{**ITEM, "quantity": 7}])
    check("同内容方案指纹相同", p2.fingerprint(), p.fingerprint())
    c2, gates2 = gw.preview(p2, 3000)
    check("重复预校验被拦截", c2 is None, True)
    check("拦截理由是幂等", "重复" in blocked_reasons(gates2), True)

    p3 = plan(items=[{**ITEM, "quantity": 8}])
    check("不同数量指纹不同", p3.fingerprint() != p.fingerprint(), True)
    c3, _ = gw.preview(p3, 3000)
    check("不同方案仍可预校验", c3 is not None, True)


# ---------- 两段式流程 ----------

def test_fingerprint_binding() -> None:
    """凭据与方案绑定，改动方案后旧凭据立即失效。"""
    print("\n[两段式：凭据绑定]")
    gw = with_ordering(True)

    p = plan(items=[{**ITEM, "quantity": 1}])
    c, _ = gw.preview(p, 5000)
    check("预校验生成凭据", c is not None, True)

    ok, msg = gw.execute(c, p)
    check("凭据有效时放行", ok, True)

    # 改动方案内容
    p2 = plan(items=[{**ITEM, "quantity": 2}])
    ok2, msg2 = gw.execute(c, p2)
    check("方案改动后旧凭据失效", ok2, False)
    check("失效理由说明改动", "改动" in msg2, True)


def test_confirmation_expiry() -> None:
    """凭据 5 分钟过期。"""
    print("\n[两段式：凭据过期]")
    gw = with_ordering(True)
    now = 1_000_000.0

    p = plan(items=[{**ITEM, "quantity": 4}])
    c, _ = gw.preview(p, 1000, now=now)
    check("有效期为 5 分钟", c.expires_at - c.created_at, float(ORDERING_CONFIRMATION_TTL))
    check("TTL 常量是 300 秒", ORDERING_CONFIRMATION_TTL, 300)

    ok, msg = gw.execute(c, p, now=now + ORDERING_CONFIRMATION_TTL - 10)
    check("TTL 内仍有效", ok, True)

    p2 = plan(items=[{**ITEM, "quantity": 5}])
    c2, _ = gw.preview(p2, 1000, now=now)
    ok2, msg2 = gw.execute(c2, p2, now=now + ORDERING_CONFIRMATION_TTL + 1)
    check("过期后拒绝执行", ok2, False)
    check("过期理由可读", "过期" in msg2, True)


def test_execute_rejects_none() -> None:
    """execute 收到 None 必须拒绝而不是崩溃。"""
    print("\n[两段式：凭据为 None]")
    gw = with_ordering(True)
    ok, msg = gw.execute(None, plan())
    check("None 凭据被拒绝", ok, False)
    check("理由指向 preview", "preview" in msg, True)


def test_env_flag_rechecked_at_execute() -> None:
    """execute 时必须重新检查环境开关，不能只在 preview 检查一次。

    这条容易被忽略：如果用户在 preview 后关掉开关，execute 不该放行。
    """
    print("\n[闸门复查：execute 时重检]")
    os.environ[ORDERING_ENV_FLAG] = "true"
    gw = OrderGateway(daily_limit=5, daily_amount_limit_fen=100_000)
    p = plan(items=[{**ITEM, "quantity": 2}])
    c, _ = gw.preview(p, 2000)
    check("开启状态下预校验通过", c is not None, True)

    os.environ.pop(ORDERING_ENV_FLAG, None)
    ok, msg = gw.execute(c, p)
    check("关闭开关后 execute 拒绝", ok, False)
    check("拒绝理由含环境开关", "环境开关" in msg, True)
    os.environ.pop(ORDERING_ENV_FLAG, None)


def test_preview_blocks_all_when_env_off() -> None:
    """默认状态下 preview 必须整体拦截，四道闸都要给出结果。"""
    print("\n[默认状态整体拦截]")
    os.environ.pop(ORDERING_ENV_FLAG, None)
    gw = OrderGateway()
    c, gates = gw.preview(plan(), 1000)
    check("凭据为 None", c is None, True)
    check("四道闸都给了结果", len(gates), 4)
    names = [g.name for g in gates]
    check("闸门名称完整",
          names == ["环境开关", "方案完整性", "每日上限", "幂等检查"], True)
    check("环境开关拦截", gates[0].result, GateResult.BLOCKED)
    # 合法方案下其余三闸应通过
    for g in gates[1:]:
        check(f"{g.name} 不被环境开关连带影响", g.result, GateResult.PASS)


# ---------- 方案与凭据的数据正确性 ----------

def test_plan_representation() -> None:
    """方案摘要与指纹。"""
    print("\n[方案表示]")
    p = plan(items=[{**ITEM, "quantity": 2}])
    check("总数量正确", p.total_quantity(), 2)
    desc = p.describe()
    # 摘要展示商品名而非编码——编码是给用户看的噪音
    check("摘要含商品名", ITEM["name"] in desc, True)
    check("摘要含数量", "×2" in desc, True)
    check("摘要含门店", STORE in desc, True)
    check("堂食摘要可读", "到店自取" in desc, True)
    check("外送摘要可读", "麦乐送" in plan(be_type=2, be_code="X").describe(), True)
    # 未提供 name 时回退到编码
    fallback = plan(items=[{"productCode": "12345", "quantity": 1}]).describe()
    check("无商品名时回退到编码", "12345" in fallback, True)

    # 指纹必须对内容敏感
    base = plan(items=[{**ITEM, "quantity": 1}]).fingerprint()
    check("数量变化指纹变化",
          plan(items=[{**ITEM, "quantity": 5}]).fingerprint() != base, True)
    check("门店变化指纹变化",
          plan(items=[dict(ITEM)], store_code="9999999").fingerprint() != base, True)
    check("相同内容指纹稳定", plan(items=[{**ITEM, "quantity": 1}]).fingerprint(), base)
    check("指纹是 64 位十六进制", len(base), 64)


def test_confirmation_dict() -> None:
    """凭据序列化的字段完整性——这是给用户看的确认信息。

    注意 `to_dict()` 用驼峰命名，且**刻意不暴露 fingerprint**：
    确认信息会展示给用户，凭据里带上方案指纹等于把幂等判定依据
    暴露出去，构造重复请求时缺少这层保护。
    """
    print("\n[凭据序列化]")
    gw = with_ordering(True)
    p = plan(items=[{**ITEM, "quantity": 3}])
    c, _ = gw.preview(p, 12_345)
    d = c.to_dict()
    for key in ("confirmationId", "planSummary", "quotedPriceYuan",
                "expiresAt", "expiresInSeconds"):
        check(f"含字段 {key}", key in d, True)
    check("对外不暴露 fingerprint", "fingerprint" in d, False)
    check("对外不暴露原始分值", "quoted_price_fen" in d, False)
    # 金额转为元并保留两位——直接展示给人读
    check("金额转元", d["quotedPriceYuan"], "123.45")
    check("未过期判定正确", c.is_expired(), False)
    check("过期判定正确", c.is_expired(time.time() + ORDERING_CONFIRMATION_TTL + 10), True)


def test_render_gates() -> None:
    """闸门结果渲染。"""
    print("\n[渲染]")
    gw = with_ordering(True)
    _, gates = gw.preview(plan(), 100)
    text = render_gates(gates)
    check("含通过标记", "通过" in text, True)
    check("含闸门名称", "环境开关" in text, True)
    for name in ("方案完整性", "每日上限", "幂等检查"):
        check(f"含「{name}」", name in text, True)


def test_no_network_calls() -> None:
    """确认网关本身不含任何网络调用。

    网关的职责是"判定是否允许下单"，不是"执行下单"。真正的
    `create-order` 由调用方在 `execute()` 返回 True 之后自己调。
    若将来有人在此模块内引入 HTTP 调用，这个测试会失败。
    """
    print("\n[无网络调用]")
    src = (ROOT / "scripts" / "order_gateway.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import urllib", "httpx", "urlopen",
                      "socket."):
        check(f"不含 {forbidden}", forbidden in src, False)
    # 没有任何 MCP 调用痕迹：网关只做判定，不发起请求
    for forbidden in ("mcp__", "call_tool", "invoke_tool", "subprocess"):
        check(f"不含 {forbidden}", forbidden in src, False)
    # 文档必须写清"放行不等于已下单"
    check("文档说明需调用方自行下单", "调用 create-order" in src, True)


def main() -> int:
    print("=" * 58)
    print("下单安全网关测试（全程 dry-run，不发任何请求）")
    print("=" * 58)
    try:
        test_env_flag_blocks_by_default()
        test_plan_validation()
        test_daily_limits()
        test_idempotency()
        test_fingerprint_binding()
        test_confirmation_expiry()
        test_execute_rejects_none()
        test_env_flag_rechecked_at_execute()
        test_preview_blocks_all_when_env_off()
        test_plan_representation()
        test_confirmation_dict()
        test_render_gates()
        test_no_network_calls()
    finally:
        os.environ.pop(ORDERING_ENV_FLAG, None)

    print("\n" + "=" * 58)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSED} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())