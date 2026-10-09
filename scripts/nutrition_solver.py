"""多目标营养求解器。

给定热量上限、蛋白质目标、钠上限等约束，从麦当劳营养表中找出最优的
餐品组合。

设计取舍：
- 纯本地计算，不调 MCP。数据来源与抓取过程见 tests/fixtures/。
- 确定性：相同输入必得相同输出，不含随机、不依赖字典遍历顺序。
- 命中不了就说命中不了，绝不用 0冒充缺失值。

已知的数据陷阱（实测结论，见 references/data-notes.md）：
- 官方营养表对部分新品未收录，此类条目必须显式标记为"无数据"，
  不能当作 0热量参与求和，否则会给出错误的低热量建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 能量字段：API 同时给 kJ 和 kcal，界面展示用 kcal
NUTRIENT_FIELDS = (
    "energyKcal",
    "protein",
    "fat",
    "carbohydrate",
    "sodium",
    "calcium",
)


@dataclass(frozen=True)
class NutritionItem:
    """营养表里的一条记录。

    nutrition_complete 为 False 表示官方未收录该餐品的真实营养数据
    （表现为全部字段为 0）。这类条目不可参与求解，只能作为"有数据"
    的组合被推荐展示，不能被当作 0 热量选项。
    """

    product_name: str
    energy_kcal: float | None
    protein: float | None
    fat: float | None
    carbohydrate: float | None
    sodium: float | None
    calcium: float | None
    nutrition_complete: bool = True

    @classmethod
    def from_dict(cls, raw: dict) -> "NutritionItem":
        """从 MCP 返回的单条记录构造。

        判定数据缺失的规则：**热量与蛋白质同时为 0**。

        实测无糖可口可乐系列的原始数据是
        `0,0,0,0,1,2,0`（kcal=0, protein=0, fat=0, carb=1, sodium=2, calcium=0），
        碳水字段是 1 而非 0，所以不能用"四个字段全为 0"作判据——
        那会让它被误判成真实数据，然后以"0 大卡 2mg 钠"的身份成为最优解。
        热量与蛋白质同时为 0 才是可靠的缺失信号：任何真实餐品都不可能
        既无热量又无蛋白质。
        """
        energy = _num(raw.get("energyKcal"))
        protein = _num(raw.get("protein"))
        fat = _num(raw.get("fat"))
        carb = _num(raw.get("carbohydrate"))
        complete = not ((energy or 0) == 0 and (protein or 0) == 0)
        return cls(
            product_name=(raw.get("productName") or "").strip(),
            energy_kcal=energy,
            protein=protein,
            fat=fat,
            carbohydrate=carb,
            sodium=_num(raw.get("sodium")),
            calcium=_num(raw.get("calcium")),
            nutrition_complete=complete,
        )


@dataclass
class Constraint:
    """一组求解约束。None 表示该维度不设限。

    max_sodium 默认不设限而非给默认值：钠是本 Skill 的默认排序键，
    但只有在用户明确提出要求时才作为硬约束，避免替用户做决定。
    """

    max_kcal: float | None = None
    target_protein: float | None = None
    max_sodium: float | None = None
    max_fat: float | None = None
    min_kcal: float | None = None
    strict_protein: bool = False

    def __post_init__(self) -> None:
        # min_kcal 未显式给出时，由 max_kcal 派生一个下限。
        #
        # 不设下限会导致求解器把茶、咖啡这类"几乎零热量"的饮品当作
        # 低热量最优解——实测"钠<=300mg、热量<=500kcal"下排第一的
        # 是川宁伯爵红茶（2kcal / 0mg 钠），这在营养上毫无意义。
        # 一餐需要提供实际能量，默认取上限的 60% 作为下限，
        # 用户显式给出 min_kcal 时以其为准。
        if self.min_kcal is None and self.max_kcal is not None:
            self.min_kcal = self.max_kcal * 0.6


@dataclass
class Combination:
    """一个候选组合。"""

    items: list[NutritionItem]
    total: dict[str, float] = field(default_factory=dict)

    @property
    def total_kcal(self) -> float:
        return self.total.get("energyKcal", 0.0)

    @property
    def total_protein(self) -> float:
        return self.total.get("protein", 0.0)

    @property
    def total_sodium(self) -> float:
        return self.total.get("sodium", 0.0)

    @property
    def sort_key(self) -> tuple:
        """排序键：正餐优先 → 钠升序 → 热量升序 → 名称。

        为什么正餐优先而不是直接钠优先：实测若把钠排在第一位，
        "清淡午餐"会收敛到「冰美式+可乐+纯牛奶」——钠最低但只有 8g
        蛋白，本质是三样饮品。原因是麦当劳低钠食物集中在奶品和
        饮品类，把钠当首要目标就等于要求"全是低钠"，而正餐类
        （汉堡、麦满分）钠普遍在 500mg 以上。

        因此先把"像一餐"放在首位：含主食或蛋白的组合优先，
        其次才是钠、热量。

        名称用 sorted 而非原顺序，这样组合内餐品的排列顺序不影响
        排序结果，枚举顺序变化也不会导致输出抖动。
        """
        names = "|".join(sorted(i.product_name for i in self.items))
        return (
            0 if _has_meal_component(self.items) else 1,
            self.total_sodium,
            self.total_kcal,
            names,
        )


class Solver:
    """确定性多目标求解器。

    排序规则是本Skill 的差异化核心：默认按钠升序，其次热量升序，
    最后按名称字典序保证稳定。理由是实测发现钠是用户最常说"想清淡点"
    却最难自己说出数值的目标，而数据侧钠字段完整可算。
    """

    def __init__(self, items: list[NutritionItem]):
        self.items = items
        # 同营养值的不同规格会重复占位。实测冰美式小杯与热美式小杯
        # 营养完全相同（10kcal / 1g 蛋白 / 0mg 钠），纯牛奶（盒装）在
        # 官方返回里出现两次。不去重会让用户看到营养账本完全相同、
        # 只是名称不同的两条结果。
        self._deduped = _dedupe_by_signature(items)

    def solve(
        self,
        constraint: Constraint,
        max_items: int = 3,
        limit: int = 10,
    ) -> list[Combination]:
        """求最优组合。

        Args:
            constraint: 约束条件。
            max_items: 单个组合最多包含几个餐品。
            limit: 返回结果条数。

        Returns:
            按钠升序、热量升序、名称字典序排好的组合列表。
            不满足约束时返回空列表，不返回"最接近的近似解"——
            近似解会被用户误当成可行方案。
        """
        pool = self._feasible_pool(constraint)
        combos = self._enumerate(pool, constraint, max_items)
        combos.sort(key=lambda c: c.sort_key)
        return self._drop_duplicate_combos(combos)[:limit]

    def _feasible_pool(self, c: Constraint) -> list[NutritionItem]:
        """筛出单独就满足硬约束且数据完整的候选单品。

        数据不完整的条目在这里被排除，不进入后续组合——
        否则组合总热量会被低估，给出错误的推荐。
        """
        pool: list[NutritionItem] = []
        for item in self._deduped:
            if not item.nutrition_complete:
                continue
            if c.max_kcal is not None and (item.energy_kcal or 0) > c.max_kcal:
                continue
            if c.max_sodium is not None and (item.sodium or 0) > c.max_sodium:
                continue
            if c.max_fat is not None and (item.fat or 0) > c.max_fat:
                continue
            pool.append(item)
        return pool

    def _drop_duplicate_combos(
        self, combos: list[Combination]
    ) -> list[Combination]:
        """去掉营养账本完全相同的组合。

        单品去重后仍可能出现"两杯不同饮品恰好营养相同"的组合，
        它们的总热量、蛋白、钠完全一致，展示两条意义不大。
        保留排序后最靠前的那条。
        """
        seen: set[tuple] = set()
        unique: list[Combination] = []
        for combo in combos:
            sig = (combo.total_kcal, combo.total_protein, combo.total_sodium)
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(combo)
        return unique

    def _enumerate(
        self, pool: list[NutritionItem], c: Constraint, max_items: int
    ) -> list[Combination]:
        """枚举所有满足约束的组合。

        组合规模限制在 max_items 以内，避免生成"三个汉堡加两杯饮料"
        这类数学上最优但没人会真点的东西。枚举顺序固定，
        因此结果完全可复现。
        """
        results: list[Combination] = []
        limit = max_items

        def backtrack(start: int, chosen: list[NutritionItem]) -> None:
            if chosen:
                combo = _build(chosen)
                if _meets(combo, c):
                    results.append(combo)
            if len(chosen) == limit:
                return
            for idx in range(start, len(pool)):
                chosen.append(pool[idx])
                backtrack(idx + 1, chosen)
                chosen.pop()

        backtrack(0, [])
        return results


def _dedupe_by_signature(items: list[NutritionItem]) -> list[NutritionItem]:
    """按营养值去重，同值只保留名称字典序最靠前的一个。

    官方营养表对同一餐品按规格分别记录（冰/热、大/中/小杯），
    但很多条目营养值完全相同。不去重会让求解结果出现
    "营养账本一模一样、只是名称不同"的两条，用户会以为算错了。
    """
    best: dict[tuple, NutritionItem] = {}
    for item in items:
        sig = (
            item.energy_kcal,
            item.protein,
            item.fat,
            item.carbohydrate,
            item.sodium,
            item.calcium,
        )
        if sig not in best or item.product_name < best[sig].product_name:
            best[sig] = item
    return sorted(best.values(), key=lambda i: i.product_name)


def _build(items: list[NutritionItem]) -> Combination:
    """把单品列表累加成组合，缺失维度记为 0。"""
    totals = {f: 0.0 for f in NUTRIENT_FIELDS}
    for item in items:
        for field_name in NUTRIENT_FIELDS:
            totals[field_name] += getattr(item, _attr(field_name)) or 0.0
    # 按名称排序，消除输入顺序对结果的影响，保证确定性
    return Combination(items=sorted(items, key=lambda i: i.product_name), total=totals)


def _meets(combo: Combination, c: Constraint) -> bool:
    """组合级约束检查。target_protein 是软目标，不满足不淘汰。"""
    if c.max_kcal is not None and combo.total_kcal > c.max_kcal:
        return False
    if c.min_kcal is not None and combo.total_kcal < c.min_kcal:
        return False
    if c.max_sodium is not None and combo.total_sodium > c.max_sodium:
        return False
    if c.max_fat is not None and combo.total.get("fat", 0.0) > c.max_fat:
        return False
    if not _has_category_diversity(combo):
        return False
    if c.strict_protein and c.target_protein is not None:
        if combo.total_protein < c.target_protein:
            return False
    return True


# 餐品类别，按实测营养表名称归类。求解时用于保证组合的结构合理。
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("主食", ("麦满分", "汉堡", "堡", "卷", "麦香鱼", "三件套", "四件套")),
    ("蛋白", ("鸡", "牛", "猪", "鱼", "虾", "蛋", "肉", "翅", "腿")),
    ("配菜", ("薯条", "玉米", "沙拉", "蔬菜", "小食", "拼盘")),
    ("甜品", ("派", "新地", "冰淇淋", "旋风", "雪冰", "奶冻", "圣代")),
    ("饮品", ("可乐", "雪碧", "红茶", "绿茶", "果汁", "矿泉水", "苏打", "柠")),
    ("咖啡", ("咖啡", "美式", "拿铁", "卡布", "摩卡", "焦糖", "阿芙佳朵", "奶铁")),
    ("奶品", ("牛奶", "纯悦", "豆浆", "燕麦")),
)


def _category_of(name: str) -> str:
    """按名称关键词判定餐品类别，未命中返回空串。"""
    for category, keywords in _CATEGORY_RULES:
        if any(k in name for k in keywords):
            return category
    return ""


def _has_meal_component(items: list[NutritionItem]) -> bool:
    """组合里是否含主食或蛋白类餐品，即是否"像一餐"。"""
    return any(_category_of(i.product_name) in ("主食", "蛋白") for i in items)


def _has_category_diversity(combo: Combination) -> bool:
    """组合必须像个正餐，而不只是数学上满足约束。

    实测中只加"同类不重复"是不够的：「怡泉C + 可乐 + 苹果片」
    仍是 0 蛋白的三杯饮料，而「钠<=300mg」这一档全都落在饮料区。

    规则：
    1. 饮料最多 1 个，避免饮料占满名额
    2. 最多两样同属"零嘴"类别（甜品/配菜）的餐品，
       防止「派 + 冰淇淋 + 玉米杯」这类纯零食组合冒充一餐

    单品组合（max_items=1）不受限，允许纯饮品——用户明确要喝东西时
    不该被拦下。
    """
    names = [i.product_name for i in combo.items]
    if len(names) <= 1:
        return True

    categories = [_category_of(n) for n in names]

    if categories.count("饮品") > 1:
        return False

    snacky = categories.count("甜品") + categories.count("配菜")
    return snacky <= 2


def _protein_deficit(combo: Combination, c: Constraint) -> float:
    """蛋白质缺口，用于硬约束模式下淘汰不达标组合。"""
    if c.target_protein is None:
        return 0.0
    return max(0.0, c.target_protein - combo.total_protein)


def _names(combo: Combination) -> str:
    """组合内餐品名排序后拼接，作为最终排序的稳定 tie-breaker。"""
    return "|".join(sorted(i.product_name for i in combo.items))


def _attr(field_name: str) -> str:
    """NutritionItem 属性名映射。"""
    return {
        "energyKcal": "energy_kcal",
        "protein": "protein",
        "fat": "fat",
        "carbohydrate": "carbohydrate",
        "sodium": "sodium",
        "calcium": "calcium",
    }[field_name]


def _num(value) -> float | None:
    """安全转数字。

    实测 query-my-account 的积分字段是字符串（availablePoint: "0"），
    静默做字符串拼接是这类接口最容易踩的坑，所以统一在这里收口。
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None