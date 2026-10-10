"""生成儿童营养可分享页面。

单文件 HTML，无外部依赖，数据全部来自 tests/fixtures/ 下的实测夹具。
浏览器直接打开即可，不需要 Token 与 MCP 连接。

最小闭环：能生成 → 能打开 → 再补内容。

运行：
    python scripts/generate_child_page.py
    python scripts/generate_child_page.py --age 9
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from child_nutrition import (  # noqa: E402
    AGE_PROFILES,
    detect_gaps,
    get_profile,
    solve_for_child,
)
from nutrition_solver import NutritionItem, _category_of  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "child-nutrition.html"

# 类别对应的视觉标识，让家长一眼看出餐品构成
CATEGORY_ICON = {
    "主食": "◆",
    "蛋白": "●",
    "配菜": "■",
    "饮品": "○",
    "咖啡": "○",
    "奶品": "○",
    "甜品": "◇",
}


def load_items() -> list[NutritionItem]:
    data = json.loads((FIXTURES / "nutrition.json").read_text(encoding="utf-8"))
    return [NutritionItem.from_dict(i) for i in data["items"]]


def _rows(combos) -> str:
    """把求解结果渲染成表格行。"""
    out = []
    for idx, combo in enumerate(combos, start=1):
        names = " + ".join(
            f"{CATEGORY_ICON.get(_category_of(i.product_name), '·')} {escape(i.product_name)}"
            for i in combo.items
        )
        out.append(
            f"""    <tr>
      <td class="rank">{idx}</td>
      <td class="dish">{names}</td>
      <td class="num">{combo.total_kcal:.0f}</td>
      <td class="num">{combo.total_protein:.0f}</td>
      <td class="num">{combo.total_sodium:.0f}</td>
      <td class="num">{combo.total.get('fat', 0):.0f}</td>
    </tr>"""
        )
    return "\n".join(out)


def _gaps(gaps: list[str]) -> str:
    if not gaps:
        return """    <p class="ok">这份菜单在该年龄段的覆盖情况良好。</p>"""
    items = "\n".join(
        f"      <li>{escape(g)}</li>" for g in gaps
    )
    return f"""    <ul class="gaps">
{items}
    </ul>"""


def _bands() -> str:
    """三档阈值的对照表。"""
    out = []
    for band, spec in AGE_PROFILES.items():
        out.append(
            f"""    <tr>
      <td>{escape(spec['label'])}</td>
      <td class="num">{spec['min_kcal']}–{spec['max_kcal']}</td>
      <td class="num">≤ {spec['max_sodium']}</td>
      <td class="num">≤ {spec['max_fat']}</td>
    </tr>"""
        )
    return "\n".join(out)


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>麦麦儿童营养 · 麦当劳实测数据</title>
<style>
:root{{
  --bg:#fdf8f3;--surface:#fff;--ink:#1f1a16;--ink2:#5c5349;--ink3:#8f8579;
  --line:#ece3d8;--accent:#c8451f;--accent2:#e07a3f;--green:#2d7a4f;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  background:var(--bg);color:var(--ink);line-height:1.7;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  padding:0 20px 60px;
}}
.wrap{{max-width:760px;margin:0 auto}}
header{{padding:44px 0 28px;border-bottom:2px solid var(--ink)}}
.eyebrow{{font-size:12px;letter-spacing:.14em;color:var(--accent);font-weight:700}}
h1{{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:10px 0 8px}}
.lede{{font-size:16px;color:var(--ink2)}}
section{{padding:32px 0;border-bottom:1px solid var(--line)}}
h2{{font-size:13px;letter-spacing:.1em;color:var(--ink3);font-weight:700;margin-bottom:14px}}
h3{{font-size:20px;font-weight:650;margin-bottom:6px}}
p{{margin-bottom:12px;color:var(--ink2)}}
.qa{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}}
.qa .q{{font-weight:600;color:var(--ink);margin-bottom:8px}}
.qa .a{{font-size:15px}}
table{{width:100%;border-collapse:collapse;font-size:14px;background:var(--surface);border-radius:10px;overflow:hidden;margin:14px 0}}
th{{background:#f6efe6;text-align:left;padding:10px 12px;font-size:11px;letter-spacing:.06em;color:var(--ink2);font-weight:700}}
td{{padding:10px 12px;border-top:1px solid var(--line)}}
td.num{{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}}
td.rank{{color:var(--accent);font-weight:700;width:28px}}
td.dish{{font-weight:600}}
.gaps{{background:#fff8f0;border-left:3px solid var(--accent2);padding:14px 18px;border-radius:0 8px 8px 0;margin:12px 0}}
.gaps li{{font-size:14px;color:var(--ink2);margin:5px 0 5px 18px}}
.ok{{background:#f0f8f2;border-left:3px solid var(--green);padding:12px 16px;border-radius:0 8px 8px 0;font-size:14px;color:var(--ink2)}}
.src{{background:#f6f2ec;border-radius:10px;padding:16px 18px;font-size:13px;color:var(--ink2);line-height:1.8}}
footer{{padding:28px 0 0;font-size:13px;color:var(--ink3);line-height:1.8}}
.cta{{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;padding:10px 22px;border-radius:8px;font-weight:600;font-size:14px;margin:4px 8px 4px 0}}
.star{{text-align:center;padding:26px;background:var(--surface);border:1px solid var(--line);border-radius:12px;margin:28px 0}}
.star p{{margin-bottom:12px}}
@media(max-width:600px){{
  h1{{font-size:24px}}
  table{{font-size:13px}}
  th,td{{padding:8px 8px}}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">基于麦当劳官方 MCP 实测数据</div>
  <h1>你孩子的午餐，<br>钠超标了吗？</h1>
  <p class="lede">输入年龄，从麦当劳 156 条有营养数据的餐品里，找出真正适合该年龄段的组合。不估算，不填 0。</p>
</header>

<section>
  <h2>实测对话</h2>
  <div class="qa">
    <div class="q">家长：我家 {age} 岁孩子，吃麦当劳要注意什么？</div>
    <div class="a">按{label}的参考标准：热量 {min_kcal}–{max_kcal} kcal、钠 ≤ {max_sodium} mg、脂肪 ≤ {max_fat} g。<br>这是通用人群参考值，不是医疗建议，也不能替代儿科医生的意见。</div>
  </div>
{answer}
</section>

<section>
  <h2>三档年龄阈值</h2>
  <p>营养数值来自麦当劳官方接口，年龄阈值来自通用膳食参考值——两者性质不同，必须分开看。</p>
  <table>
    <thead><tr><th>年龄段</th><th>热量 kcal</th><th>钠 mg</th><th>脂肪 g</th></tr></thead>
    <tbody>
{bands}
    </tbody>
  </table>
</section>

<section>
  <h2>这份菜单满足不了什么</h2>
{gaps}
</section>

<section>
  <h2>数据来源</h2>
  <div class="src">
    <strong>营养数值</strong>：麦当劳 MCP <code>list-nutrition-foods</code> 实测抓取，
    全量 {total_records} 条（{unique_records} 个唯一名称），其中 4 条因官方未收录而无数据。<br>
    <strong>年龄阈值</strong>：通用人群膳食参考值，<strong>非麦当劳官方数据，非医疗建议</strong>。<br>
    <strong>抓取时间</strong>：2026-10-09　|　<strong>验证</strong>：运行 <code>python scripts/test_child_nutrition.py</code>
  </div>
</section>

<div class="star">
  <p>觉得有用的话，点个 ⭐ Star 支持一下</p>
  <a class="cta" href="https://github.com/Hxxcb1412/mcd-nutrition-optimizer" target="_blank" rel="noopener">★ Star on GitHub</a>
  <a class="cta" href="https://github.com/Hxxcb1412/mcd-nutrition-optimizer/issues/19" target="_blank" rel="noopener">参赛报名页</a>
</div>

<footer>
  本项目为麦当劳程序员节创意开发大赛参赛作品，非麦当劳官方产品。<br>
  输出仅供参考，不构成医疗或营养建议。餐品信息与供应状态以麦当劳官方渠道实时结果为准。<br>
  每餐热量高低需结合儿童生长发育与活动量综合判断，本页数值不能替代专业营养指导。
</footer>

</div>
</body>
</html>
"""


def render_page(age: int) -> str:
    """渲染指定年龄的页面。"""
    items = load_items()
    profile, combos, note = solve_for_child(items, age, limit=6)

    data = json.loads((FIXTURES / "nutrition.json").read_text(encoding="utf-8"))

    if profile is None:
        answer = f"""  <div class="qa"><div class="a">{escape(note)}</div></div>"""
        bands = _bands()
        gaps = _gaps([])
    else:
        if combos:
            body = _rows(combos)
            answer = f"""  <h3>{escape(profile.label)}的可行组合</h3>
  <table>
    <thead><tr><th></th><th>餐品组合</th><th>热量</th><th>蛋白</th><th>钠</th><th>脂肪</th></tr></thead>
    <tbody>
{body}
    </tbody>
  </table>"""
        else:
            answer = f"""  <div class="gaps">{escape(note)}</div>"""

        bands = _bands()
        gaps = _gaps(detect_gaps(profile, items))

    return TEMPLATE.format(
        age=age,
        label=profile.label if profile else "该年龄段",
        min_kcal=profile.min_kcal if profile else 0,
        max_kcal=profile.max_kcal if profile else 0,
        max_sodium=profile.max_sodium if profile else 0,
        max_fat=profile.max_fat if profile else 0,
        answer=answer,
        bands=bands,
        gaps=gaps,
        total_records=data["recordCount"],
        unique_records=data["uniqueCount"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="生成儿童营养可分享页面")
    parser.add_argument("--age", type=int, default=7, help="年龄，默认 7 岁")
    args = parser.parse_args()

    if not (3 <= args.age <= 17):
        print(f"年龄需在 3-17 岁之间，收到 {args.age}", file=sys.stderr)
        return 1

    html = render_page(args.age)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")

    print(f"已生成 {OUTPUT}")
    print(f"字节数 {len(html.encode('utf-8'))}")
    print(f"年龄 {args.age} 岁")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())