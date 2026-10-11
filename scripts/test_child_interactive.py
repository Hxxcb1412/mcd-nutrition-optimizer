"""交互页渲染逻辑测试。

用 Node 实跑页面里的 render() 函数，验证 15 个年龄档都能正确渲染。
不靠肉眼——HTML 结构对但 JS 逻辑错，肉眼看不出来。

运行：
    python scripts/test_child_interactive.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "child-interactive.html"
NODE = Path("C:/Users/ASUS/.workbuddy/binaries/node/versions/22.12.0/node.exe")

FAILED: list[str] = []


def check(label: str, actual, expected) -> None:
    if str(actual) == str(expected):
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: 期望 {expected!r}，实际 {actual!r}")
        FAILED.append(label)


def extract() -> tuple[dict, str]:
    """从页面里抽出 DATA 与 render/bar 函数。"""
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.*?\});", html, re.S)
    if not m:
        raise SystemExit("页面里找不到 DATA")
    data = json.loads(m.group(1))
    body = html[html.index("function bar("):html.index("slider.addEventListener")]
    return data, body


def main() -> int:
    if not PAGE.exists():
        print("请先生成页面：python scripts/generate_child_interactive.py")
        return 1

    data, body = extract()

    # 构造一个自带 DOM stub 的测试脚本。
    # 页面里 render() 直接引用 elAge/elBand/elTh/elSol/elGaps 这几个变量，
    # 测试环境必须把它们映射到 stub 上，否则 ReferenceError。
    script = (
        "const els={};\n"
        "function mk(){return {textContent:'',innerHTML:'',addEventListener:function(){}};"
        "}\n"
        "['age','band','thresholds','solutions','gaps','slider']"
        ".forEach(function(k){els[k]=mk();});\n"
        "const slider=els.slider;\n"
        "const elAge=els.age, elBand=els.band, elTh=els.thresholds;\n"
        "const elSol=els.solutions, elGaps=els.gaps;\n"
        "const CAT_ICON={'主食':'◆','蛋白':'●','配菜':'■','饮品':'○',"
        "'咖啡':'○','奶品':'○','甜品':'◇'};\n"
        "const DATA=" + json.dumps(data, ensure_ascii=False) + ";\n"
        + body
        + "\nmodule.exports={render:render,els:els,getData:function(){return DATA;}};\n"
    )
    tmp = ROOT / ".child_interactive_test.js"
    tmp.write_text(script, encoding="utf-8")

    try:
        out = subprocess.run(
            ["node", "-e",
             "const m=require('./.child_interactive_test.js');"
             "let fail=0;"
             "const ages=Object.keys(m.getData().ages);"
             # 用 data 属性计数，不能用 class="sol" —— 它会同时匹配
             # class="sol" 和 class="sol top"，导致计数翻倍。
             "const count=(s)=>(s.match(/class=\"sol[ \"]/g)||[]).length;"
             "for(const age of ages){"
             "  m.render(Number(age));"
             "  const e=m.els, d=m.getData().ages[age];"
             # elAge.textContent = age 赋的是数字。真实 DOM 会转字符串，
             # 但 stub 不会，比较时必须 String() 归一，否则数字 vs 字符串恒不等。
             "  if(String(e.age.textContent)!==String(age)) fail++;"
             "  if(e.band.textContent!==m.getData().profiles[d.band].label) fail++;"
             "  if(count(e.solutions.innerHTML)!==d.combos.length) fail++;"
             "  if(d.combos.length>0){"
             "    if(!e.solutions.innerHTML.includes('钠升序最优')) fail++;"
             "    if(!e.solutions.innerHTML.includes('蛋白')) fail++;"
             "  }"
             "}"
             "const r={ages:ages.length,fail:fail};"
             "m.render(3);r.band3=m.els.band.textContent;"
             "m.render(17);r.band17=m.els.band.textContent;"
             "m.render(7);r.sol7=count(m.els.solutions.innerHTML);"
             "r.combos7=m.getData().ages['7'].combos.length;"
             "r.names7=m.getData().ages['7'].combos[0].names.join('+');"
             "r.gap=m.els.gaps.innerHTML.includes('21.1%');"
             "r.th7=(m.els.thresholds.innerHTML.match(/class=\"th\"/g)||[]).length;"
             "console.log(JSON.stringify(r));"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        if out.returncode != 0:
            print(out.stderr.strip()[:400])
            return 1
        r = json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        tmp.unlink(missing_ok=True)

    print("\n[数据完整性]")
    check("覆盖 3-17 共 15 档", r["ages"], 15)

    print("\n[渲染逻辑：15 档全部通过]")
    check("15 档渲染零错误", r["fail"], 0)

    print("\n[边界档位]")
    check("3 岁 → 学龄前", r["band3"], "学龄前（3-6 岁）")
    check("17 岁 → 青少年", r["band17"], "青少年（13-17 岁）")

    print("\n[默认档 7 岁]")
    check("方案数与数据一致", r["sol7"], r["combos7"])
    print(f"        首解：{r['names7']}")

    print("\n[缺口说明]")
    check("显示 21.1% 覆盖率", r["gap"], True)

    print("\n" + "=" * 58)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for n in FAILED:
            print(f"  - {n}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())