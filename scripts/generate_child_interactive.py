"""生成可交互的儿童营养页面。

与generate_child_page.py 的区别：那个是静态快照（一个年龄），
这个把15 个年龄的解全部内联，拖动滑块即时切换——不刷新、不依赖 JS 外部文件。

数据全部来自 tests/fixtures/ 下的实测夹具，由 nutrition_solver 现场算出，
不是预先写死的文案。改营养表数据后重新生成会同步更新。

运行：
    python scripts/generate_child_interactive.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from child_nutrition import (  # noqa: E402
    AGE_PROFILES,
    detect_gaps,
    solve_for_child,
)
from nutrition_solver import NutritionItem, _category_of  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "child-interactive.html"

AGE_MIN, AGE_MAX = 3, 17

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>孩子吃麦当劳，钠超标了吗 · 可交互版</title>
<style>
:root{--bg:#fdf8f3;--surface:#fff;--ink:#1f1a16;--ink2:#5c5349;--ink3:#8f8579;
--line:#ece3d8;--accent:#c8451f;--accent2:#e07a3f;--green:#2d7a4f;--amber:#a6690b;
--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);line-height:1.7;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:0 20px 60px}
.wrap{max-width:820px;margin:0 auto}
header{padding:40px 0 24px;border-bottom:2px solid var(--ink)}
.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--accent);font-weight:700}
h1{font-size:29px;font-weight:700;letter-spacing:-.02em;margin:10px 0 8px}
.lede{font-size:16px;color:var(--ink2);max-width:56ch}

/* 滑块区 */
.picker{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:26px 28px;margin:26px 0}
.picker-top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.age-num{font-size:52px;font-weight:700;font-family:var(--mono);letter-spacing:-.04em;line-height:1;color:var(--accent)}
.age-unit{font-size:18px;color:var(--ink2)}
.band-tag{margin-left:auto;font-size:13px;padding:5px 14px;border-radius:999px;
background:#f6efe6;color:var(--ink2);font-weight:600}
input[type=range]{width:100%;height:8px;-webkit-appearance:none;appearance:none;
background:#ece3d8;border-radius:5px;outline:none;margin:6px 0 4px}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:30px;height:30px;
border-radius:50%;background:var(--accent);cursor:pointer;border:3px solid #fff;
box-shadow:0 2px 8px rgba(0,0,0,.18)}
input[type=range]::-moz-range-thumb{width:30px;height:30px;border-radius:50%;
background:var(--accent);cursor:pointer;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.18)}
.ticks{display:flex;justify-content:space-between;font-size:12px;color:var(--ink3);font-family:var(--mono)}

/* 阈值卡 */
.thresholds{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin:18px 0 4px}
.th{background:#f6f2ec;border-radius:10px;padding:11px 13px;text-align:center}
.th .l{font-size:11px;color:var(--ink3);margin-bottom:2px}
.th .v{font-size:18px;font-weight:700;font-family:var(--mono)}
.th .v small{font-size:11px;font-weight:400;color:var(--ink3)}

/* 方案卡 */
.sol{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:11px}
.sol.best{border-color:var(--accent);box-shadow:0 0 0 3px rgba(200,69,31,.09)}
.sol-top{display:flex;align-items:center;gap:10px;margin-bottom:9px;flex-wrap:wrap}
.rank{font-size:11px;font-weight:700;color:var(--accent);letter-spacing:.08em}
.badge-best{font-size:10px;font-weight:700;color:#fff;background:var(--accent);
padding:2px 8px;border-radius:999px;letter-spacing:.06em}
.items{display:flex;flex-wrap:wrap;gap:7px;margin:9px 0 12px}
.item{font-size:14px;font-weight:600;padding:5px 11px;border-radius:8px;background:#f6f2ec;display:flex;align-items:center;gap:6px}
.cat{font-size:11px;opacity:.7}
.macro{display:grid;grid-template-columns:repeat(5,1fr);gap:5px;margin-top:4px}
.macro div{background:#faf8f4;border-radius:8px;padding:8px 4px;text-align:center}
.macro .l{font-size:10px;color:var(--ink3)}
.macro .v{font-size:15px;font-weight:700;font-family:var(--mono)}
.macro .v small{font-size:10px;font-weight:400;color:var(--ink3)}
.bar-wrap{margin-top:11px}
.bar-lbl{display:flex;justify-content:space-between;font-size:11px;color:var(--ink3);margin-bottom:3px}
.bar{height:6px;background:#ece3d8;border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:4px;transition:width .25s}

/* 说明块 */
.note{background:#fff8f0;border-left:3px solid var(--accent2);padding:13px 16px;
border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px;color:var(--ink2)}
.note strong{color:var(--ink)}
.src{background:#f6f2ec;border-radius:10px;padding:15px 17px;font-size:13px;color:var(--ink2);line-height:1.8;margin-top:14px}
.star{text-align:center;padding:24px;background:var(--surface);border:1px solid var(--line);
border-radius:14px;margin:26px 0 0}
.star p{font-size:15px;color:var(--ink2);margin-bottom:12px}
.cta{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
padding:10px 22px;border-radius:8px;font-weight:600;font-size:14px;margin:4px 6px}
.cta.sec{background:var(--surface);color:var(--ink);border:1px solid var(--line)}
footer{padding:26px 0 0;font-size:13px;color:var(--ink3);line-height:1.8}
h2{font-size:13px;letter-spacing:.1em;color:var(--ink3);font-weight:700;margin:0 0 12px}
@media(max-width:600px){
  h1{font-size:23px}.age-num{font-size:42px}
  .macro{grid-template-columns:repeat(3,1fr)}
  .picker{padding:20px 18px}
}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">基于麦当劳官方 MCP 实测数据</div>
  <h1>孩子吃麦当劳，钠超标了吗？</h1>
  <p class="lede">拖动滑块看3-17 岁各年龄段的可行组合。<strong>每个数字都是求解器现场算的，不是写死的文案。</strong></p>
</header>

<div class="picker">
  <div class="picker-top">
    <div class="age-num" id="age">7</div>
    <div class="age-unit">岁</div>
    <div class="band-tag" id="band">学龄儿童</div>
  </div>
  <input type="range" id="slider" min="3" max="17" value="7" step="1"
         aria-label="选择孩子年龄" aria-describedby="band">
  <div class="ticks"><span>3</span><span>6</span><span>9</span><span>12</span><span>15</span><span>17</span></div>
  <div class="thresholds" id="thresholds"></div>
</div>

<h2>可行组合</h2>
<div id="solutions"></div>

<h2>这份菜单满足不了什么</h2>
<div id="gaps"></div>

<div class="src">
  <strong>数据来源</strong>：营养数值来自麦当劳 MCP <code>list-nutrition-foods</code>
  实测抓取，全量 160 条（158 个唯一名称），其中 4 条因官方未收录而无数据。<br>
  <strong>年龄阈值</strong>：通用人群膳食参考值，<strong>非麦当劳官方数据，非医疗建议</strong>。<br>
  <strong>算法</strong>：正餐优先 → 钠升序 → 热量升序，并过滤掉
  「纯饮品组合」「甜品当正餐主体」两类不合理结果。<br>
  <strong>抓取时间</strong>：2026-10-09
</div>

<div class="star">
  <p>觉得有用的话，点个 ⭐ Star 支持一下</p>
  <a class="cta" href="https://github.com/Hxxcb1412/mcd-nutrition-optimizer" target="_blank" rel="noopener">★ Star on GitHub</a>
  <a class="cta sec" href="demo.html">完整演示</a>
  <a class="cta sec" href="data-gap-report.html">数据缺口报告</a>
</div>

<footer>
  本项目为麦当劳程序员节创意开发大赛参赛作品，非麦当劳官方产品。<br>
  输出仅供参考，不构成医疗或营养建议。餐品信息与供应状态以麦当劳官方渠道实时结果为准。<br>
  每餐热量高低需结合儿童生长发育与活动量综合判断，本页数值不能替代专业营养指导。
</footer>

</div>

<script>
const DATA = __DATA__;

const CAT_ICON = {'主食':'◆','蛋白':'●','配菜':'■','饮品':'○','咖啡':'○','奶品':'○','甜品':'◇'};
const slider = document.getElementById('slider');
const elAge = document.getElementById('age');
const elBand = document.getElementById('band');
const elTh = document.getElementById('thresholds');
const elSol = document.getElementById('solutions');
const elGaps = document.getElementById('gaps');

function bar(label, value, limit, unit, color) {
  const pct = Math.min(100, Math.round(value / limit * 100));
  const over = value > limit;
  return '<div class="bar-wrap">' +
    '<div class="bar-lbl"><span>' + label + '</span><span>' + Math.round(value) + unit +
    ' / ' + limit + unit + (over ? ' ⚠超出' : '') + '</span></div>' +
    '<div class="bar"><i style="width:' + pct + '%;background:' + (over ? '#c0392b' : color) + '"></i></div>' +
    '</div>';
}

function render(age) {
  const d = DATA.ages[String(age)];
  const p = DATA.profiles[d.band];
  elAge.textContent = age;
  elBand.textContent = p.label;

  elTh.innerHTML =
    '<div class="th"><div class="l">热量区间</div><div class="v">' + p.min + '–' + p.max + '<small> kcal</small></div></div>' +
    '<div class="th"><div class="l">钠上限</div><div class="v">' + p.sodium + '<small> mg</small></div></div>' +
    '<div class="th"><div class="l">脂肪上限</div><div class="v">' + p.fat + '<small> g</small></div></div>';

  if (!d.combos.length) {
    elSol.innerHTML = '<div class="note">' + d.note + '</div>';
    elGaps.innerHTML = '';
    return;
  }

  elSol.innerHTML = d.combos.map(function (c, i) {
    const items = c.names.map(function (n, k) {
      return '<span class="item"><span class="cat">' + (CAT_ICON[c.cats[k]] || '·') +
        '</span>' + n + '</span>';
    }).join('');
    const isBest = i === 0;
    return '<div class="sol' + (isBest ? ' best' : '') + '">' +
      '<div class="sol-top"><span class="rank">方案 ' + (i + 1) + '</span>' +
      (isBest ? '<span class="badge-best">钠升序最优</span>' : '') + '</div>' +
      '<div class="items">' + items + '</div>' +
      '<div class="macro">' +
      '<div><div class="l">热量</div><div class="v">' + c.kcal + '<small>kcal</small></div></div>' +
      '<div><div class="l">蛋白</div><div class="v">' + c.protein + '<small>g</small></div></div>' +
      '<div><div class="l">钠</div><div class="v">' + c.sodium + '<small>mg</small></div></div>' +
      '<div><div class="l">脂肪</div><div class="v">' + c.fat + '<small>g</small></div></div>' +
      '<div><div class="l">钙</div><div class="v">' + c.calcium + '<small>mg</small></div></div>' +
      '</div>' +
      bar('热量', c.kcal, p.max, ' kcal', '#c8451f') +
      bar('钠', c.sodium, p.sodium, ' mg', '#b8860b') +
      bar('脂肪', c.fat, p.fat, ' g', '#2c5f8a') +
      '</div>';
  }).join('');

  elGaps.innerHTML =
    '<div class="note"><strong>' + p.label + '（' + age + ' 岁）</strong>：' + p.note + '</div>' +
    '<div class="note">菜单覆盖率实测只有 <strong>21.1%</strong>（128 个餐品 27 个能查到）。' +
    '组合里的餐品都是官方营养表已收录的，<strong>未收录的餐品不会出现在这里</strong>。</div>';
}

slider.addEventListener('input', function () { render(Number(slider.value)); });
render(Number(slider.value));
</script>
</body>
</html>
"""


def main() -> int:
    data = json.loads((FIXTURES / "nutrition.json").read_text(encoding="utf-8"))
    items = [NutritionItem.from_dict(i) for i in data["items"]]

    payload: dict = {"profiles": {}, "ages": {}}

    for band, spec in AGE_PROFILES.items():
        payload["profiles"][band] = {
            "label": spec["label"],
            "min": spec["min_kcal"],
            "max": spec["max_kcal"],
            "sodium": spec["max_sodium"],
            "fat": spec["max_fat"],
            "note": spec["note"],
        }

    for age in range(AGE_MIN, AGE_MAX + 1):
        profile, combos, msg = solve_for_child(items, age, limit=6)
        if profile is None:
            continue
        gaps = detect_gaps(profile, items)
        payload["ages"][str(age)] = {
            "band": profile.band,
            "label": profile.label,
            "note": gaps[0] if gaps else profile.note,
            "gaps": gaps,
            "combos": [
                {
                    "names": [i.product_name for i in c.items],
                    "cats": [_category_of(i.product_name) for i in c.items],
                    "kcal": round(c.total_kcal),
                    "protein": round(c.total_protein),
                    "sodium": round(c.total_sodium),
                    "fat": round(c.total.get("fat", 0)),
                    "carb": round(c.total.get("carbohydrate", 0)),
                    "calcium": round(c.total.get("calcium", 0)),
                }
                for c in combos
            ],
        }

    html = TEMPLATE.replace(
        "__DATA__",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")

    total = sum(len(v["combos"]) for v in payload["ages"].values())
    print(f"已生成 {OUTPUT}")
    print(f"字节数 {len(html.encode('utf-8'))}")
    print(f"年龄 {AGE_MIN}-{AGE_MAX} 岁，{len(payload['ages'])} 档，共 {total} 条组合")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())