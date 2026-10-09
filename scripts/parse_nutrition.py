"""TOON 格式解析器。

麦当劳 MCP 的 list-nutrition-foods 不返回标准 JSON，而返回 TOON
（Token-Oriented Object Notation）紧凑格式以节省 LLM token：

    [160]{productName,nutritionDescription,energyKj,energyKcal,protein,
           fat,carbohydrate,sodium,calcium}:
     猪柳麦满分,null,1288,308,16,16,24,781,213
     ...

本模块只负责把这坨文本变成 dict 列表，不做任何业务判断。
"""

from __future__ import annotations

import re

# 表头形如 [160]{a,b,c}:  —— 记录数在方括号里，字段名在花括号里
_HEADER = re.compile(r"^\s*\[(?P<count>\d+)\]\s*\{(?P<fields>[^}]*)\}\s*:")

# 记录形如  名称,null,1288,308,16,16,24,781,213
# 名称本身不含逗号（MCP 侧保证了这一点），故按逗号切分是安全的
_NULL_TOKENS = {"null", "NULL", "None", ""}


class NutritionParseError(ValueError):
    """TOON 结构不符合预期时抛出，不静默返回半成品。"""


def parse_toon(text: str) -> list[dict]:
    """把 list-nutrition-foods 的 TOON 文本解析成 dict 列表。

    Args:
        text: MCP 工具返回的 data 字段原始字符串。

    Returns:
        每条记录一个 dict，字段名与表头一致。数值字段转 int/float，
        空值转 None，重复的 productName 原样保留（去重是业务决策，不在解析层做）。

    Raises:
        NutritionParseError: 表头缺失、记录数与实际行数不符、或字段数不匹配。
    """
    if not text or not text.strip():
        raise NutritionParseError("TOON 文本为空")

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise NutritionParseError("TOON 文本无有效行")

    header = _HEADER.match(lines[0])
    if not header:
        raise NutritionParseError(f"表头格式不符：{lines[0][:80]!r}")

    declared = int(header.group("count"))
    fields = [f.strip() for f in header.group("fields").split(",")]
    rows = lines[1:]

    if len(rows) != declared:
        # 声明数与实际行数不符说明接口返回被截断或改版，必须显式失败，
        # 不能让调用方在残缺数据上算出错误的热量。
        raise NutritionParseError(
            f"声明 {declared} 条，实际解析到 {len(rows)} 条，数据可能被截断"
        )

    items: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        values = [v.strip() for v in row.split(",")]
        if len(values) != len(fields):
            raise NutritionParseError(
                f"第 {idx} 条字段数不符：期望 {len(fields)}，实际 {len(values)}"
            )
        items.append(
            {name: _coerce(val) for name, val in zip(fields, values)}
        )
    return items


def _coerce(raw: str):
    """把 TOON 里的单个字段值转成合适的 Python 类型。

    整数字段（能量/蛋白/脂肪/碳水/钠/钙）转 int，浮点转 float，
    null 与空串统一转 None。productName 含中文和括号，保持字符串原样。
    """
    if raw in _NULL_TOKENS:
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw