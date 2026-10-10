"""生成「活动新品 vs 营养表」缺口报告页。

这是本项目最独特的数据资产：实测发现活动日历推的新品，
在官方营养表里的收录率为 0%。做成可分享页面，让别人引用我们的数据。

单文件 HTML，无外部依赖。

运行：
    python scripts/generate_gap_page.py
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from campaign_gap import analyze, is_food_campaign  # noqa: E402
from combo_resolver import build_nutrition_index  # noqa: E402
from coverage_report import check_menu  # noqa: E402
from nutrition_solver import NutritionItem  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "data-gap-report.html"


def load():
    nutrition = json.loads((FIXTURES / "nutrition.json").read_text(encoding="utf-8"))
    menu = json.loads((FIXTURES / "menu.json").read_text(encoding="utf-8"))
    campaigns = json.loads((FIXTURES / "campaigns.json").read_text(encoding="utf-8"))
    return nutrition, menu, campaigns


def _campaign_rows(analyses) -> str:
    """活动明细表。"""
    out = []
    for a in analyses:
        if not a.is_food_campaign or not a.items:
            continue
        names = "、".join(escape(i.name) for i in a.uncovered)
        if not names:
            names = "—"
        out.append(
            f"""    <tr>
      <td>{escape(a.title)}</td>
      <td class="num">{len(a.items)}</td>
      <td class="miss">{names}</td>
    </tr>"""
        )
    return "\n".join(out)


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>麦当劳数据缺口报告 · 实测</title>
<style>
:root{{--bg:#f7f6f3;--surface:#fff;--ink:#1a1a1a;--ink2:#555;--ink3:#8a8a8a;
--line:#e5e3df;--red:#c0392b;--amber:#b8860b;--blue:#2c5f8a}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);line-height:1.7;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:0 20px 60px}}
.wrap{{max-width:820px;margin:0 auto}}
header{{padding:44px 0 26px;border-bottom:2px solid var(--ink)}}
.eyebrow{{font-size:12px;letter-spacing:.14em;color:var(--red);font-weight:700}}
h1{{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:10px 0 8px}}
.lede{{font-size:16px;color:var(--ink2)}}
section{{padding:30px 0;border-bottom:1px solid var(--line)}}
h2{{font-size:13px;letter-spacing:.1em;color:var(--ink3);font-weight:700;margin-bottom:12px}}
h3{{font-size:19px;font-weight:650;margin-bottom:8px}}
p{{margin-bottom:12px;color:var(--ink2)}}
.big{{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}}
.stat{{flex:1;min-width:150px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px}}
.stat .n{{font-size:40px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1;letter-spacing:-.03em}}
.stat .n.red{{color:var(--red)}}
.stat .n.blue{{color:var(--blue)}}
.stat .l{{font-size:12px;color:var(--ink3);margin-top:6px}}
.stat .d{{font-size:13px;color:var(--ink2);margin-top:6px;line-height:1.5}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--surface);border-radius:10px;overflow:hidden;margin:12px 0}}
th{{background:#f2f1ee;text-align:left;padding:10px 12px;font-size:11px;letter-spacing:.06em;font-weight:700}}
td{{padding:10px 12px;border-top:1px solid var(--line);vertical-align:top}}
td.num{{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}}
td.miss{{color:var(--red);font-size:12.5px}}
.bar{{height:26px;background:#eeece8;border-radius:6px;overflow:hidden;margin:5px 0}}
.bar i{{display:block;height:100%;border-radius:6px}}
.layers{{margin:18px 0}}
.layer{{display:flex;align-items:center;gap:12px;margin:8px 0}}
.layer .lb{{width:130px;font-size:13px;color:var(--ink2);flex-shrink:0}}
.layer .tr{{flex:1;height:24px;background:#eeece8;border-radius:5px;overflow:hidden}}
.layer .tr i{{display:block;height:100%}}
.layer .lv{{width:112px;font-family:ui-monospace,monospace;font-size:12.5px;font-weight:600;text-align:right;flex-shrink:0}}
.finding{{background:#fdf3f1;border-left:3px solid var(--red);padding:16px 20px;border-radius:0 8px 8px 0;margin:16px 0}}
.finding h4{{font-size:15px;color:var(--red);margin-bottom:8px}}
.finding p{{margin-bottom:0;font-size:14px}}
.note{{background:#f5f3ef;border-radius:10px;padding:16px 18px;font-size:13px;color:var(--ink2);line-height:1.8}}
.star{{text-align:center;padding:26px;background:var(--surface);border:1px solid var(--line);border-radius:12px;margin:28px 0}}
.star p{{margin-bottom:12px}}
.cta{{display:inline-block;background:var(--red);color:#fff;text-decoration:none;padding:10px 22px;border-radius:8px;font-weight:600;font-size:14px;margin:4px 6px}}
footer{{padding:26px 0 0;font-size:13px;color:var(--ink3);line-height:1.8}}
code{{background:#eeece8;padding:2px 6px;border-radius:4px;font-size:12.5px;font-family:ui-monospace,monospace}}
@media(max-width:600px){{h1{{font-size:24px}}.layer .lb{{width:90px;font-size:12px}}.layer .lv{{width:88px;font-size:11.5px}}}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">基于麦当劳官方 MCP 实测 · 2026-10-09</div>
  <h1>麦当劳的数据缺口报告</h1>
  <p class="lede">活动日历每天在推的新品，恰好是营养表覆盖不到的那批。这份报告用实测数据说明这件事，以及它对点餐决策的实际影响。</p>
</header>

<section>
  <h2>三个实测数字</h2>
  <div class="big">
    <div class="stat">
      <div class="n red">{gap_pct}%</div>
      <div class="l">活动新品营养收录率</div>
      <div class="d">{gap_uncovered} 种活动餐品，营养表收录 {gap_covered} 种</div>
    </div>
    <div class="stat">
      <div class="n">{cover_pct}%</div>
      <div class="l">门店菜单覆盖率</div>
      <div class="d">{cover_matched}/{cover_total} 餐品能查到营养数据</div>
    </div>
    <div class="stat">
      <div class="n blue">8/9</div>
      <div class="l">套餐默认子项命中</div>
      <div class="d">唯一缺失是麦炫酷整个系列</div>
    </div>
  </div>
  <div class="finding">
    <h4>核心发现</h4>
    <p>官方营养表是季度更新的静态快照，门店菜单是实时数据。当活动日历推送「龙焰鸡腿堡三件套」「马苏里拉拉丝芝芝条」这类新品时，营养表里往往还没有它们。<strong>用户看到活动推荐，很可能算不出它的营养值。</strong>这是数据源的时间差，任何工具都补不上——除了如实告诉用户。</p>
  </div>
</section>

<section>
  <h2>菜单覆盖率分层</h2>
  <p>逐级放宽匹配条件，看能救回多少条目。</p>
  <div class="layers">
    <div class="layer"><div class="lb">精确同名</div><div class="tr"><i style="width:{c_exact}%;background:#c0392b"></i></div><div class="lv">{cover_exact} · {c_exact}%</div></div>
    <div class="layer"><div class="lb">+ 剥规格后缀</div><div class="tr"><i style="width:{c_spec}%;background:#b8860b"></i></div><div class="lv">{cover_spec} · {c_spec}%</div></div>
    <div class="layer"><div class="lb">+ 括号归一化</div><div class="tr"><i style="width:{c_full}%;background:#2c5f8a"></i></div><div class="lv">{cover_matched} · {c_full}%</div></div>
    <div class="layer"><div class="lb">完全无数据</div><div class="tr"><i style="width:{c_miss}%;background:#8a8a8a"></i></div><div class="lv">{cover_miss} · {c_miss}%</div></div>
  </div>
  <div class="note">
    <strong>为什么不剥离括号内容</strong>：「100% 苹果汁(盒装)」与「100%苹果汁」只差"(盒装)"这个包装描述，但包装差异可能对应不同配方。静默合并会给出错误营养值——宁可少命中一个，也不把不确定的映射说成确定的事实。
  </div>
</section>

<section>
  <h2>活动与营养表交叉明细</h2>
  <p>从活动文案中定位到的餐品，逐个核对营养表收录情况。</p>
  <table>
    <thead><tr><th>活动</th><th>涉及餐品</th><th>营养表未收录</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</section>

<section>
  <h2>方法与局限</h2>
  <div class="note">
    <strong>数据获取</strong>：通过 MCP 调用 <code>list-nutrition-foods</code>、<code>query-meals</code>、<code>query-meal-detail</code>、<code>query-nearby-stores</code>、<code>campaign-calendar</code> 实测抓取，测试门店为北京王府井新东安二号餐厅（<code>1950526</code>，128 个餐品）。<br><br>
    <strong>识别方法的局限</strong>：活动文案用精确子串匹配定位餐品，可能漏掉表述特殊的新品，也可能把酱料名误判为餐品。因此这份清单是<strong>下界</strong>，真实缺口可能更大。周边/卡类活动已排除。<br><br>
    <strong>这不是麦当劳的缺陷</strong>：营养表作为公开数据源有其更新节奏。本报告的目的只是说明数据边界，让使用者知道自己能算什么、不能算什么。
  </div>
</section>

<div class="star">
  <p>这份数据花了我们大量实测时间。如果对你有用，点个 ⭐ Star 支持一下</p>
  <a class="cta" href="https://github.com/Hxxcb1412/mcd-nutrition-optimizer" target="_blank" rel="noopener">★ Star on GitHub</a>
  <a class="cta" href="https://github.com/Hxxcb1412/mcd-nutrition-optimizer/blob/main/docs/child-nutrition.html" target="_blank" rel="noopener">儿童营养页</a>
</div>

<footer>
  本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。<br>
  报告数据为 2026-10-09 实测快照，官方接口数据可能已发生变化，可用仓库中的脚本重新抓取验证。<br>
  输出仅供参考，不构成医疗或营养建议。
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    nutrition, menu, campaigns = load()

    items = [NutritionItem.from_dict(i) for i in nutrition["items"]]
    index, _ = build_nutrition_index(items)

    analyses = [
        analyze(c["title"], c["body"], index) for c in campaigns["campaigns"]
    ]

    all_names: dict[str, bool] = {}
    for a in analyses:
        if not a.is_food_campaign:
            continue
        for item in a.items:
            all_names[item.name] = item.found_in_nutrition
    gap_covered = sum(1 for ok in all_names.values() if ok)
    gap_uncovered = len(all_names) - gap_covered
    gap_pct = round(gap_covered / len(all_names) * 100) if all_names else 0

    report, _ = check_menu(
        FIXTURES / "menu.json", FIXTURES / "nutrition.json"
    )

    html = TEMPLATE.format(
        gap_pct=gap_pct,
        gap_covered=gap_covered,
        gap_uncovered=gap_uncovered,
        # 统一保留一位小数。直接用 report.full_rate 会渲染成
        # 21.09375%，与 README 里写的 21.1% 不一致。
        cover_pct=round(report.full_rate, 1),
        cover_matched=report.matched,
        cover_total=report.total,
        c_exact=round(report.exact_rate, 1),
        c_spec=round(report.spec_rate, 1),
        c_full=round(report.full_rate, 1),
        c_miss=round(100 - report.full_rate, 1),
        cover_exact=len(report.exact_hits),
        cover_spec=len(report.spec_hits),
        cover_miss=len(report.misses),
        rows=_campaign_rows(analyses),
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"已生成 {OUTPUT}")
    print(f"字节数 {len(html.encode('utf-8'))}")
    print(f"活动餐品 {len(all_names)} 种，营养表收录 {gap_covered} 种（{gap_pct}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())