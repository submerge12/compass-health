"""
Central food library for the fat-loss meal-planning rule engine.

Every food carries:

  * Display names (zh / en).
  * Macros per 100 g edible portion (kcal, protein, carbs, fat, fiber).
  * Micronutrient amounts per 100 g (from the Chinese Food Composition Database,
    CDR 6th ed. 2018; USDA FDC used for foods absent from CDR).
    Units: mg for Ca/Fe/Zn; mcg for I/Se/A/D/K/B12/Folate; g for omega-3/fiber.
  * max_practical_serving_g — realistic daily upper limit for this food. Used by
    the sufficiency checker to judge whether a carrier can actually cover its RDA
    share at normal intake volumes.
  * primary_macro, exchange_g — exchange-matrix mechanics.
  * validation_buckets / execution_buckets — closed-loop and planning buckets.
  * micronutrient_roles — which tracked roles this food meaningfully carries.
  * weekly_floor — minimum appearances per week if sole carrier of a role.
"""

from __future__ import annotations

from typing import Iterable, Optional


# ── Exchange-unit yardsticks ─────────────────────────────────────────────────
CARB_EXCHANGE_G    = 28.0
PROTEIN_EXCHANGE_G = 22.0
FAT_EXCHANGE_G     = 5.0


# ── 8 validation buckets ─────────────────────────────────────────────────────
VALIDATION_BUCKETS: tuple[str, ...] = (
    "staple",
    "lean_protein",
    "red_meat_shellfish",
    "calcium",
    "iodine",
    "vitamin_d",
    "dark_green_cruciferous",
    "vitamin_e_healthy_fat",
)

VALIDATION_BUCKET_LABELS: dict[str, dict[str, str]] = {
    "staple":                 {"zh": "主食 / 碳水化合物",  "en": "Staples / carbohydrates"},
    "lean_protein":           {"zh": "低脂蛋白",           "en": "Lean protein"},
    "red_meat_shellfish":     {"zh": "红肉 / 贝类",        "en": "Red meat / shellfish"},
    "calcium":                {"zh": "钙源",               "en": "Calcium source"},
    "iodine":                 {"zh": "碘源",               "en": "Iodine source"},
    "vitamin_d":              {"zh": "维生素 D 源",         "en": "Vitamin D source"},
    "dark_green_cruciferous": {"zh": "深绿 / 十字花科蔬菜", "en": "Dark-green / cruciferous"},
    "vitamin_e_healthy_fat":  {"zh": "维生素 E / 健康脂肪", "en": "Vitamin E / healthy fat"},
}


# ── 12 execution buckets ─────────────────────────────────────────────────────
EXECUTION_BUCKETS: tuple[str, ...] = (
    "slow_carb_staple",
    "fast_carb_staple",
    "lean_white_meat",
    "red_meat",
    "shellfish",
    "deep_sea_fish",
    "egg",
    "dairy",
    "soy_product",
    "dark_leafy_green",
    "cruciferous_fungi_algae",
    "nut_seed_functional",
)

EXECUTION_BUCKET_LABELS: dict[str, dict[str, str]] = {
    "slow_carb_staple":        {"zh": "慢碳主食",     "en": "Slow-carb staples"},
    "fast_carb_staple":        {"zh": "快碳主食",     "en": "Fast-carb staples"},
    "lean_white_meat":         {"zh": "低脂白肉",     "en": "Lean white meat"},
    "red_meat":                {"zh": "红肉",         "en": "Red meat"},
    "shellfish":               {"zh": "贝类 / 高锌",  "en": "Shellfish / high-zinc"},
    "deep_sea_fish":           {"zh": "深海鱼",       "en": "Deep-sea fish"},
    "egg":                     {"zh": "蛋类",         "en": "Eggs"},
    "dairy":                   {"zh": "乳制品",       "en": "Dairy"},
    "soy_product":             {"zh": "豆制品",       "en": "Soy products"},
    "dark_leafy_green":        {"zh": "深色叶菜",     "en": "Dark leafy greens"},
    "cruciferous_fungi_algae": {"zh": "十字花/菌/藻", "en": "Cruciferous / fungi / algae"},
    "nut_seed_functional":     {"zh": "坚果 / 种子",  "en": "Nuts / seeds / functional"},
}


# ── Micronutrient roles with RDA targets ─────────────────────────────────────
# rda_women / rda_men: Chinese DRI 2023 edition values for adults 18-50.
# unit: "mg" | "mcg" | "g"
# ideal_sources: desired number of distinct carriers in the user's library.
MICRONUTRIENT_ROLES: dict[str, dict] = {
    "calcium":   {"zh": "钙",         "en": "Calcium",       "ideal_sources": 2,
                  "rda_women": 800,  "rda_men": 800,  "unit": "mg"},
    "iron":      {"zh": "铁",         "en": "Iron",          "ideal_sources": 2,
                  "rda_women": 20,   "rda_men": 12,   "unit": "mg"},
    "zinc":      {"zh": "锌",         "en": "Zinc",          "ideal_sources": 1,
                  "rda_women": 7.5,  "rda_men": 12.5, "unit": "mg"},
    "iodine":    {"zh": "碘",         "en": "Iodine",        "ideal_sources": 1,
                  "rda_women": 120,  "rda_men": 120,  "unit": "mcg"},
    "selenium":  {"zh": "硒",         "en": "Selenium",      "ideal_sources": 1,
                  "rda_women": 60,   "rda_men": 60,   "unit": "mcg"},
    "vitamin_a": {"zh": "维生素 A",   "en": "Vitamin A",     "ideal_sources": 1,
                  "rda_women": 700,  "rda_men": 800,  "unit": "mcg"},
    "vitamin_d": {"zh": "维生素 D",   "en": "Vitamin D",     "ideal_sources": 1,
                  "rda_women": 10,   "rda_men": 10,   "unit": "mcg"},
    "vitamin_e": {"zh": "维生素 E",   "en": "Vitamin E",     "ideal_sources": 1,
                  "rda_women": 14,   "rda_men": 14,   "unit": "mg"},
    "vitamin_k": {"zh": "维生素 K",   "en": "Vitamin K",     "ideal_sources": 1,
                  "rda_women": 80,   "rda_men": 80,   "unit": "mcg"},
    "b12":       {"zh": "维生素 B12", "en": "Vitamin B12",   "ideal_sources": 1,
                  "rda_women": 2.4,  "rda_men": 2.4,  "unit": "mcg"},
    "folate":    {"zh": "叶酸",       "en": "Folate",        "ideal_sources": 1,
                  "rda_women": 400,  "rda_men": 400,  "unit": "mcg"},
    "omega3":    {"zh": "Omega-3",    "en": "Omega-3",       "ideal_sources": 1,
                  "rda_women": 1.6,  "rda_men": 1.6,  "unit": "g"},
    "fiber":     {"zh": "膳食纤维",   "en": "Dietary fiber", "ideal_sources": 2,
                  "rda_women": 25,   "rda_men": 30,   "unit": "g"},
}


# ── Tier normaliser ───────────────────────────────────────────────────────────
def _strip_tier(role: str) -> str:
    """'iron_tier1' → 'iron'."""
    return role.split("_tier", 1)[0]


# ── Entry factory ─────────────────────────────────────────────────────────────
def _entry(
    zh: str,
    en: str,
    primary: str,
    kcal: float,
    p: float,
    c: float,
    f: float,
    *,
    fiber: float = 0.0,
    validation: Iterable[str] = (),
    execution: Iterable[str] = (),
    roles: Iterable[str] = (),
    tags: Iterable[str] = (),
    notes: Optional[str] = None,
    weekly_floor: int = 0,
    max_practical_serving_g: float = 200.0,
    # CDR / USDA micronutrient amounts per 100 g edible portion
    nutrients: Optional[dict[str, float]] = None,
) -> dict:
    if primary == "carb" and c > 0:
        ex_g = round(CARB_EXCHANGE_G * 100 / c, 1)
    elif primary == "protein" and p > 0:
        ex_g = round(PROTEIN_EXCHANGE_G * 100 / p, 1)
    elif primary == "fat" and f > 0:
        ex_g = round(FAT_EXCHANGE_G * 100 / f, 1)
    else:
        ex_g = 100.0

    _default_nutrients: dict[str, float] = {
        "calcium_mg": 0.0, "iron_mg": 0.0, "zinc_mg": 0.0,
        "iodine_mcg": 0.0, "selenium_mcg": 0.0,
        "vitamin_a_mcg": 0.0, "vitamin_d_mcg": 0.0,
        "vitamin_e_mg": 0.0, "vitamin_k_mcg": 0.0,
        "b12_mcg": 0.0, "folate_mcg": 0.0,
        "omega3_g": 0.0, "fiber_g": fiber,
    }
    if nutrients:
        _default_nutrients.update(nutrients)

    return {
        "zh": zh, "en": en,
        "primary_macro": primary,
        "kcal_per_100g": kcal,
        "protein_per_100g": p,
        "carbs_per_100g": c,
        "fat_per_100g": f,
        "fiber_per_100g": fiber,
        "exchange_g": ex_g,
        "validation_buckets": tuple(validation),
        "execution_buckets": tuple(execution),
        "micronutrient_roles": tuple(roles),
        "tags": tuple(tags),
        "weekly_floor": weekly_floor,
        "notes": notes,
        "max_practical_serving_g": max_practical_serving_g,
        "nutrients": _default_nutrients,
    }


# ── Food dataset ──────────────────────────────────────────────────────────────
FOOD_LIBRARY: dict[str, dict] = {

    # ── Staples ───────────────────────────────────────────────────────────────
    "rice": _entry("大米（熟）", "Rice (cooked)", "carb", 130, 2.7, 28, 0.3,
        fiber=0.3,
        validation=["staple"], execution=["fast_carb_staple"],
        roles=[], tags=["staple"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 7, "iron_mg": 0.3, "zinc_mg": 0.6,
                   "selenium_mcg": 1.7, "folate_mcg": 5, "fiber_g": 0.3}),

    "brown_rice": _entry("糙米（熟）", "Brown rice (cooked)", "carb", 112, 2.6, 24, 0.9,
        fiber=3.5,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["fiber"], tags=["staple"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 13, "iron_mg": 1.2, "zinc_mg": 1.7,
                   "selenium_mcg": 2.5, "folate_mcg": 20, "fiber_g": 3.5,
                   "vitamin_e_mg": 0.5}),

    "oats": _entry("燕麦片（干）", "Oats (dry)", "carb", 389, 16.9, 66, 6.9,
        fiber=10.6,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["fiber", "iron_tier2"], tags=["staple"],
        max_practical_serving_g=80,
        nutrients={"calcium_mg": 52, "iron_mg": 3.6, "zinc_mg": 3.1,
                   "selenium_mcg": 5.7, "folate_mcg": 56, "fiber_g": 10.6,
                   "vitamin_e_mg": 0.7, "vitamin_k_mcg": 3}),

    "buckwheat": _entry("荞麦（熟）", "Buckwheat (cooked)", "carb", 92, 3.4, 20, 0.6,
        fiber=2.7,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["fiber"], tags=["staple"],
        max_practical_serving_g=250,
        nutrients={"calcium_mg": 7, "iron_mg": 0.8, "zinc_mg": 0.7,
                   "selenium_mcg": 2.2, "folate_mcg": 14, "fiber_g": 2.7}),

    "quinoa": _entry("藜麦（熟）", "Quinoa (cooked)", "carb", 120, 4.4, 21, 1.9,
        fiber=2.8,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["fiber", "iron_tier2"], tags=["staple"],
        max_practical_serving_g=250,
        nutrients={"calcium_mg": 17, "iron_mg": 1.5, "zinc_mg": 1.1,
                   "selenium_mcg": 2.8, "folate_mcg": 42, "fiber_g": 2.8,
                   "vitamin_e_mg": 0.6}),

    "sweet_potato": _entry("红薯（熟）", "Sweet potato", "carb", 86, 1.6, 20, 0.1,
        fiber=3.0,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["vitamin_a", "fiber"], tags=["staple"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 30, "iron_mg": 0.6, "zinc_mg": 0.3,
                   "vitamin_a_mcg": 709, "vitamin_c_mg": 20,
                   "folate_mcg": 11, "fiber_g": 3.0, "vitamin_e_mg": 0.3}),

    "potato": _entry("土豆（熟）", "Potato", "carb", 87, 1.9, 20, 0.1,
        fiber=1.8,
        validation=["staple"], execution=["fast_carb_staple"],
        roles=[], tags=["staple"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 5, "iron_mg": 0.4, "zinc_mg": 0.3,
                   "selenium_mcg": 0.5, "folate_mcg": 9, "fiber_g": 1.8,
                   "vitamin_k_mcg": 2}),

    "corn": _entry("玉米", "Corn", "carb", 86, 3.3, 19, 1.4,
        fiber=2.9,
        validation=["staple"], execution=["fast_carb_staple"],
        roles=["fiber"], tags=["staple"],
        max_practical_serving_g=250,
        nutrients={"calcium_mg": 2, "iron_mg": 0.5, "zinc_mg": 0.5,
                   "selenium_mcg": 0.6, "folate_mcg": 42, "fiber_g": 2.9,
                   "vitamin_e_mg": 0.5}),

    "steamed_bun": _entry("馒头", "Steamed bun", "carb", 223, 7, 47, 0.7,
        fiber=1.3,
        validation=["staple"], execution=["fast_carb_staple"],
        roles=[], tags=["staple"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 18, "iron_mg": 1.2, "zinc_mg": 0.8,
                   "selenium_mcg": 8, "folate_mcg": 22, "fiber_g": 1.3}),

    "pumpkin": _entry("南瓜", "Pumpkin", "carb", 26, 1, 7, 0.1,
        fiber=0.5,
        validation=["staple"], execution=["slow_carb_staple"],
        roles=["vitamin_a", "fiber"], tags=["staple"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 16, "iron_mg": 0.4, "zinc_mg": 0.1,
                   "vitamin_a_mcg": 92, "folate_mcg": 16, "fiber_g": 0.5}),

    # ── Lean protein — white meat & lean fish ─────────────────────────────────
    "chicken_breast": _entry("鸡胸肉", "Chicken breast", "protein", 165, 31, 0, 3.6,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=[], tags=["poultry"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 5, "iron_mg": 0.7, "zinc_mg": 0.9,
                   "selenium_mcg": 17, "b12_mcg": 0.3, "folate_mcg": 4,
                   "vitamin_e_mg": 0.3}),

    "chicken_thigh_skinless": _entry("去皮鸡腿", "Chicken thigh (skinless)", "protein", 177, 24, 0, 9,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=["iron_tier2"], tags=["poultry"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 6, "iron_mg": 1.3, "zinc_mg": 1.5,
                   "selenium_mcg": 18, "b12_mcg": 0.4, "folate_mcg": 5,
                   "vitamin_e_mg": 0.4}),

    "duck_breast": _entry("鸭胸肉", "Duck breast", "protein", 135, 19, 0, 6,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=["iron_tier2"], tags=["poultry"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 7, "iron_mg": 2.2, "zinc_mg": 1.2,
                   "selenium_mcg": 14, "b12_mcg": 0.4, "folate_mcg": 8,
                   "vitamin_e_mg": 0.2}),

    "pork_tenderloin": _entry("猪里脊", "Pork tenderloin", "protein", 143, 26, 0, 3.5,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=["b12"], tags=["pork"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 3, "iron_mg": 1.0, "zinc_mg": 2.0,
                   "selenium_mcg": 23, "b12_mcg": 0.7, "folate_mcg": 3,
                   "vitamin_e_mg": 0.3}),

    "cod": _entry("鳕鱼", "Cod", "protein", 82, 18, 0, 0.7,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=[], tags=["fish"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 16, "iron_mg": 0.4, "zinc_mg": 0.5,
                   "selenium_mcg": 33, "b12_mcg": 0.9, "folate_mcg": 7,
                   "vitamin_d_mcg": 1.0, "omega3_g": 0.2}),

    "sea_bass": _entry("鲈鱼", "Sea bass", "protein", 97, 18, 0, 2,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=[], tags=["fish"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 37, "iron_mg": 0.7, "zinc_mg": 0.8,
                   "selenium_mcg": 33, "b12_mcg": 1.2, "folate_mcg": 12,
                   "vitamin_d_mcg": 1.5, "omega3_g": 0.5}),

    "tilapia": _entry("罗非鱼", "Tilapia", "protein", 96, 20, 0, 1.7,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=[], tags=["fish"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 10, "iron_mg": 0.6, "zinc_mg": 0.4,
                   "selenium_mcg": 41, "b12_mcg": 1.9, "folate_mcg": 24,
                   "vitamin_d_mcg": 1.7, "omega3_g": 0.2}),

    "shrimp": _entry("虾仁", "Shrimp", "protein", 99, 24, 0.2, 0.3,
        validation=["lean_protein"], execution=["lean_white_meat"],
        roles=["selenium"], tags=["shellfish_like"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 62, "iron_mg": 1.7, "zinc_mg": 1.1,
                   "selenium_mcg": 38, "b12_mcg": 1.1, "folate_mcg": 2,
                   "vitamin_e_mg": 0.6}),

    "egg_white": _entry("蛋清", "Egg white", "protein", 52, 11, 0.7, 0.2,
        validation=["lean_protein"], execution=["egg"],
        roles=[], tags=["egg"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 7, "iron_mg": 0.1, "zinc_mg": 0.03,
                   "selenium_mcg": 8, "b12_mcg": 0.09, "folate_mcg": 4,
                   "vitamin_e_mg": 0}),

    # ── Red meat / shellfish / organ ──────────────────────────────────────────
    "beef_tenderloin": _entry("牛里脊", "Beef tenderloin", "protein", 201, 21, 0, 12,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1", "zinc", "b12"], tags=["red_meat"],
        weekly_floor=2, max_practical_serving_g=200,
        nutrients={"calcium_mg": 5, "iron_mg": 2.6, "zinc_mg": 4.6,
                   "selenium_mcg": 25, "b12_mcg": 1.4, "folate_mcg": 6,
                   "vitamin_e_mg": 0.2}),

    "beef_sirloin": _entry("牛里脊（西冷）", "Beef sirloin", "protein", 191, 22, 0, 11,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1", "zinc", "b12"], tags=["red_meat"],
        weekly_floor=2, max_practical_serving_g=200,
        nutrients={"calcium_mg": 5, "iron_mg": 2.5, "zinc_mg": 4.4,
                   "selenium_mcg": 24, "b12_mcg": 1.3, "folate_mcg": 5,
                   "vitamin_e_mg": 0.2}),

    "lamb": _entry("羊肉", "Lamb", "protein", 294, 25, 0, 21,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1", "zinc", "b12"], tags=["red_meat"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 6, "iron_mg": 2.3, "zinc_mg": 3.2,
                   "selenium_mcg": 7, "b12_mcg": 2.6, "folate_mcg": 5,
                   "vitamin_e_mg": 0.3}),

    "beef_liver": _entry("牛肝", "Beef liver", "protein", 135, 20, 4, 4,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1", "vitamin_a", "b12", "folate"], tags=["organ"],
        notes="Nutrient-dense — cap 1 serving/week (50 g max).",
        max_practical_serving_g=50,
        nutrients={"calcium_mg": 6, "iron_mg": 6.5, "zinc_mg": 4.0,
                   "selenium_mcg": 40, "vitamin_a_mcg": 6500,
                   "vitamin_d_mcg": 1.2, "b12_mcg": 60,
                   "folate_mcg": 290, "vitamin_e_mg": 0.5}),

    "chicken_liver": _entry("鸡肝", "Chicken liver", "protein", 119, 17, 0.7, 4.8,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1", "vitamin_a", "b12", "folate"], tags=["organ"],
        notes="Nutrient-dense — cap 1 serving/week (50 g max).",
        max_practical_serving_g=50,
        nutrients={"calcium_mg": 7, "iron_mg": 12.0, "zinc_mg": 2.7,
                   "selenium_mcg": 37, "vitamin_a_mcg": 10414,
                   "b12_mcg": 16.6, "folate_mcg": 590,
                   "vitamin_e_mg": 2.5}),

    "duck_blood": _entry("鸭血", "Duck blood", "protein", 56, 13, 0, 0.4,
        validation=["red_meat_shellfish"], execution=["red_meat"],
        roles=["iron_tier1"], tags=["organ"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 4, "iron_mg": 30.5, "zinc_mg": 0.5,
                   "selenium_mcg": 2, "b12_mcg": 0.0}),

    "oyster": _entry("生蚝", "Oyster", "protein", 68, 7, 3.9, 2.5,
        validation=["red_meat_shellfish"], execution=["shellfish"],
        roles=["zinc", "b12", "iron_tier1", "selenium"], tags=["shellfish"],
        weekly_floor=1, max_practical_serving_g=150,
        nutrients={"calcium_mg": 131, "iron_mg": 7.1, "zinc_mg": 16.6,
                   "selenium_mcg": 154, "b12_mcg": 16.0, "folate_mcg": 7,
                   "vitamin_e_mg": 0.9}),

    "clam": _entry("蛤蜊", "Clam", "protein", 86, 15, 3, 1,
        validation=["red_meat_shellfish"], execution=["shellfish"],
        roles=["iron_tier1", "b12"], tags=["shellfish"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 133, "iron_mg": 13.9, "zinc_mg": 1.7,
                   "selenium_mcg": 24, "b12_mcg": 49.4, "folate_mcg": 28,
                   "vitamin_e_mg": 0.7}),

    "mussel": _entry("贻贝", "Mussel", "protein", 86, 12, 3.7, 2,
        validation=["red_meat_shellfish"], execution=["shellfish"],
        roles=["iron_tier1", "b12"], tags=["shellfish"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 33, "iron_mg": 3.9, "zinc_mg": 1.6,
                   "selenium_mcg": 44, "b12_mcg": 12.0, "folate_mcg": 42,
                   "vitamin_e_mg": 0.9, "omega3_g": 0.5}),

    "scallop": _entry("扇贝", "Scallop", "protein", 69, 12, 3, 0.7,
        validation=["red_meat_shellfish"], execution=["shellfish"],
        roles=["zinc", "b12"], tags=["shellfish"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 140, "iron_mg": 2.0, "zinc_mg": 11.7,
                   "selenium_mcg": 22, "b12_mcg": 1.8, "folate_mcg": 16}),

    # ── Deep-sea fish ─────────────────────────────────────────────────────────
    "salmon": _entry("三文鱼", "Salmon", "protein", 208, 20, 0, 13,
        validation=["lean_protein", "vitamin_d"], execution=["deep_sea_fish"],
        roles=["vitamin_d", "omega3", "b12", "selenium"], tags=["fish", "deep_sea"],
        weekly_floor=2, max_practical_serving_g=200,
        nutrients={"calcium_mg": 12, "iron_mg": 0.8, "zinc_mg": 0.6,
                   "selenium_mcg": 36.5, "vitamin_a_mcg": 12,
                   "vitamin_d_mcg": 13.0, "b12_mcg": 3.2,
                   "folate_mcg": 25, "omega3_g": 2.3,
                   "vitamin_e_mg": 1.1}),

    "hairtail": _entry("带鱼", "Hairtail (beltfish)", "protein", 127, 18, 0, 5,
        validation=["lean_protein", "vitamin_d"], execution=["deep_sea_fish"],
        roles=["vitamin_d", "omega3"], tags=["fish", "deep_sea"],
        weekly_floor=2, max_practical_serving_g=200,
        nutrients={"calcium_mg": 28, "iron_mg": 1.2, "zinc_mg": 0.7,
                   "selenium_mcg": 36, "vitamin_d_mcg": 5.0,
                   "b12_mcg": 2.5, "folate_mcg": 6,
                   "omega3_g": 1.3, "vitamin_e_mg": 0.8}),

    "mackerel": _entry("青花鱼", "Mackerel", "protein", 205, 19, 0, 13.9,
        validation=["lean_protein", "vitamin_d"], execution=["deep_sea_fish"],
        roles=["vitamin_d", "omega3", "b12"], tags=["fish", "deep_sea"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 12, "iron_mg": 1.6, "zinc_mg": 0.9,
                   "selenium_mcg": 44, "vitamin_d_mcg": 16.0,
                   "b12_mcg": 8.7, "folate_mcg": 1,
                   "omega3_g": 2.2, "vitamin_e_mg": 1.5}),

    "sardine": _entry("沙丁鱼", "Sardine", "protein", 208, 25, 0, 11,
        validation=["lean_protein", "vitamin_d", "calcium"], execution=["deep_sea_fish"],
        roles=["vitamin_d", "omega3", "calcium", "b12"], tags=["fish", "deep_sea"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 382, "iron_mg": 2.9, "zinc_mg": 1.3,
                   "selenium_mcg": 52, "vitamin_d_mcg": 4.8,
                   "b12_mcg": 8.9, "folate_mcg": 10,
                   "omega3_g": 1.5, "vitamin_e_mg": 2.0}),

    # ── Eggs ──────────────────────────────────────────────────────────────────
    "whole_egg": _entry("整蛋", "Whole egg", "protein", 155, 13, 1.1, 11,
        validation=["lean_protein", "vitamin_d"], execution=["egg"],
        roles=["vitamin_d", "b12", "vitamin_a"], tags=["egg"],
        max_practical_serving_g=120,
        nutrients={"calcium_mg": 56, "iron_mg": 2.0, "zinc_mg": 1.1,
                   "selenium_mcg": 30.7, "vitamin_a_mcg": 160,
                   "vitamin_d_mcg": 2.0, "b12_mcg": 1.1,
                   "folate_mcg": 47, "vitamin_e_mg": 1.1,
                   "vitamin_k_mcg": 0.3}),

    "egg_yolk": _entry("蛋黄", "Egg yolk", "fat", 322, 16, 3.6, 27,
        validation=["vitamin_d"], execution=["egg"],
        roles=["vitamin_d", "vitamin_a"], tags=["egg"],
        max_practical_serving_g=40,
        nutrients={"calcium_mg": 112, "iron_mg": 2.7, "zinc_mg": 2.3,
                   "selenium_mcg": 56, "vitamin_a_mcg": 589,
                   "vitamin_d_mcg": 5.4, "b12_mcg": 2.1,
                   "folate_mcg": 146, "vitamin_e_mg": 2.6,
                   "vitamin_k_mcg": 0.7}),

    # ── Dairy ─────────────────────────────────────────────────────────────────
    "milk": _entry("牛奶", "Milk", "dairy", 42, 3.4, 5, 1,
        validation=["calcium", "lean_protein"], execution=["dairy"],
        roles=["calcium", "b12"], tags=["dairy"],
        weekly_floor=5, max_practical_serving_g=500,
        nutrients={"calcium_mg": 104, "iron_mg": 0.1, "zinc_mg": 0.4,
                   "selenium_mcg": 1.7, "vitamin_a_mcg": 24,
                   "vitamin_d_mcg": 1.3, "b12_mcg": 0.45,
                   "folate_mcg": 5, "vitamin_e_mg": 0.2,
                   "vitamin_k_mcg": 0.3}),

    "yogurt": _entry("酸奶", "Yogurt", "dairy", 59, 10, 3.6, 0.4,
        validation=["calcium", "lean_protein"], execution=["dairy"],
        roles=["calcium", "b12"], tags=["dairy"],
        weekly_floor=3, max_practical_serving_g=300,
        nutrients={"calcium_mg": 118, "iron_mg": 0.1, "zinc_mg": 0.6,
                   "selenium_mcg": 2.2, "vitamin_a_mcg": 21,
                   "b12_mcg": 0.5, "folate_mcg": 11,
                   "vitamin_e_mg": 0.0}),

    "greek_yogurt": _entry("希腊酸奶", "Greek yogurt", "dairy", 59, 10, 3.6, 0.4,
        validation=["calcium", "lean_protein"], execution=["dairy"],
        roles=["calcium", "b12"], tags=["dairy"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 110, "iron_mg": 0.1, "zinc_mg": 0.5,
                   "selenium_mcg": 2.5, "vitamin_a_mcg": 20,
                   "b12_mcg": 0.5, "folate_mcg": 9}),

    "cheese": _entry("奶酪", "Cheese", "dairy", 402, 25, 1.3, 33,
        validation=["calcium", "lean_protein"], execution=["dairy"],
        roles=["calcium", "b12"], tags=["dairy"],
        notes="Calorie-dense — weigh carefully.",
        max_practical_serving_g=50,
        nutrients={"calcium_mg": 721, "iron_mg": 0.2, "zinc_mg": 3.1,
                   "selenium_mcg": 14.5, "vitamin_a_mcg": 185,
                   "b12_mcg": 0.8, "folate_mcg": 18,
                   "vitamin_e_mg": 0.2, "vitamin_k_mcg": 2.8}),

    # ── Soy ───────────────────────────────────────────────────────────────────
    "tofu_firm": _entry("老豆腐", "Firm tofu", "protein", 144, 17, 3, 8,
        validation=["lean_protein", "calcium"], execution=["soy_product"],
        roles=["calcium", "iron_tier2"], tags=["soy"],
        notes="Assumes calcium-set. Nigari-set has lower calcium.",
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 138, "iron_mg": 2.5, "zinc_mg": 0.8,
                   "selenium_mcg": 8.9, "folate_mcg": 15,
                   "vitamin_e_mg": 0.9, "vitamin_k_mcg": 2.4}),

    "tofu_soft": _entry("嫩豆腐", "Soft tofu", "protein", 76, 8, 1.9, 4.8,
        validation=["lean_protein"], execution=["soy_product"],
        roles=[], tags=["soy"],
        max_practical_serving_g=250,
        nutrients={"calcium_mg": 50, "iron_mg": 1.2, "zinc_mg": 0.8,
                   "selenium_mcg": 1.6, "folate_mcg": 12}),

    "dried_tofu": _entry("豆腐干", "Dried tofu", "protein", 260, 22, 8, 15,
        validation=["lean_protein", "calcium"], execution=["soy_product"],
        roles=["calcium"], tags=["soy"],
        max_practical_serving_g=100,
        nutrients={"calcium_mg": 308, "iron_mg": 5.2, "zinc_mg": 2.7,
                   "selenium_mcg": 3.1, "folate_mcg": 22,
                   "vitamin_e_mg": 0.2}),

    "soy_milk": _entry("豆浆", "Soy milk", "protein", 54, 3.3, 6, 1.8,
        validation=["lean_protein"], execution=["soy_product"],
        roles=[], tags=["soy"],
        max_practical_serving_g=500,
        nutrients={"calcium_mg": 10, "iron_mg": 0.7, "zinc_mg": 0.3,
                   "selenium_mcg": 1.5, "folate_mcg": 15}),

    "natto": _entry("纳豆", "Natto", "protein", 212, 18, 13, 11,
        fiber=5.4,
        validation=["lean_protein"], execution=["soy_product"],
        roles=["vitamin_k", "iron_tier2"], tags=["soy"],
        max_practical_serving_g=100,
        nutrients={"calcium_mg": 217, "iron_mg": 8.6, "zinc_mg": 3.0,
                   "selenium_mcg": 8.8, "folate_mcg": 120,
                   "vitamin_k_mcg": 870,   # K2 (MK-7) — CDR tracks K1 only (34 mcg)
                   "fiber_g": 5.4, "vitamin_e_mg": 0.0}),

    "tempeh": _entry("天贝", "Tempeh", "protein", 192, 19, 9, 11,
        fiber=4.1,
        validation=["lean_protein"], execution=["soy_product"],
        roles=["iron_tier2"], tags=["soy"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 111, "iron_mg": 2.7, "zinc_mg": 1.1,
                   "selenium_mcg": 1.7, "folate_mcg": 24,
                   "fiber_g": 4.1, "vitamin_e_mg": 0.0}),

    "edamame": _entry("毛豆", "Edamame", "protein", 121, 12, 9, 5,
        fiber=4.2,
        validation=["lean_protein"], execution=["soy_product"],
        roles=["folate", "fiber"], tags=["soy"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 197, "iron_mg": 3.6, "zinc_mg": 1.4,
                   "selenium_mcg": 1.5, "folate_mcg": 165,
                   "fiber_g": 5.2, "vitamin_e_mg": 0.7,
                   "vitamin_k_mcg": 27}),

    # ── Dark leafy greens ─────────────────────────────────────────────────────
    "spinach": _entry("菠菜", "Spinach", "veg", 23, 2.9, 3.6, 0.4,
        fiber=2.2,
        validation=["dark_green_cruciferous"],
        execution=["dark_leafy_green"],
        roles=["folate", "vitamin_k", "iron_tier2", "fiber"], tags=["leafy_green"],
        notes="Oxalates reduce calcium absorption — blanch before use.",
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 99, "iron_mg": 2.7, "zinc_mg": 0.5,
                   "selenium_mcg": 1.0, "vitamin_a_mcg": 469,
                   "folate_mcg": 194, "fiber_g": 2.2,
                   "vitamin_e_mg": 2.0, "vitamin_k_mcg": 483}),

    "bok_choy": _entry("上海青", "Bok choy", "veg", 13, 1.5, 2.2, 0.2,
        fiber=1.0,
        validation=["dark_green_cruciferous", "calcium"],
        execution=["dark_leafy_green"],
        roles=["calcium", "vitamin_k", "folate"], tags=["leafy_green"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 105, "iron_mg": 0.8, "zinc_mg": 0.2,
                   "selenium_mcg": 0.5, "vitamin_a_mcg": 243,
                   "folate_mcg": 66, "fiber_g": 1.0,
                   "vitamin_e_mg": 0.1, "vitamin_k_mcg": 45}),

    "kale": _entry("羽衣甘蓝", "Kale", "veg", 49, 4.3, 8.8, 0.9,
        fiber=3.6,
        validation=["dark_green_cruciferous", "calcium"],
        execution=["dark_leafy_green"],
        roles=["calcium", "vitamin_k", "vitamin_a", "folate"], tags=["leafy_green", "cruciferous"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 150, "iron_mg": 1.5, "zinc_mg": 0.4,
                   "selenium_mcg": 0.9, "vitamin_a_mcg": 500,
                   "folate_mcg": 141, "fiber_g": 3.6,
                   "vitamin_e_mg": 1.5, "vitamin_k_mcg": 817}),

    "amaranth": _entry("苋菜", "Amaranth greens", "veg", 23, 2.5, 4, 0.3,
        fiber=1.8,
        validation=["dark_green_cruciferous"],
        execution=["dark_leafy_green"],
        roles=["iron_tier2", "calcium"], tags=["leafy_green"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 215, "iron_mg": 2.9, "zinc_mg": 0.9,
                   "selenium_mcg": 0.9, "vitamin_a_mcg": 292,
                   "folate_mcg": 85, "fiber_g": 1.8,
                   "vitamin_k_mcg": 1140}),

    "mustard_greens": _entry("芥蓝", "Mustard greens", "veg", 27, 2.9, 4.7, 0.4,
        fiber=1.4,
        validation=["dark_green_cruciferous"],
        execution=["dark_leafy_green"],
        roles=["vitamin_k", "folate"], tags=["leafy_green"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 84, "iron_mg": 1.2, "zinc_mg": 0.4,
                   "selenium_mcg": 0.9, "vitamin_a_mcg": 152,
                   "folate_mcg": 187, "fiber_g": 1.4,
                   "vitamin_k_mcg": 390}),

    # ── Cruciferous / fungi / algae ───────────────────────────────────────────
    "broccoli": _entry("西兰花", "Broccoli", "veg", 34, 2.8, 7, 0.4,
        fiber=2.6,
        validation=["dark_green_cruciferous"],
        execution=["cruciferous_fungi_algae"],
        roles=["vitamin_k", "folate", "fiber"], tags=["cruciferous"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 47, "iron_mg": 0.7, "zinc_mg": 0.4,
                   "selenium_mcg": 2.5, "vitamin_a_mcg": 31,
                   "folate_mcg": 63, "fiber_g": 2.6,
                   "vitamin_e_mg": 0.8, "vitamin_k_mcg": 102}),

    "cauliflower": _entry("菜花", "Cauliflower", "veg", 25, 1.9, 5, 0.3,
        fiber=2.0,
        validation=["dark_green_cruciferous"],
        execution=["cruciferous_fungi_algae"],
        roles=["fiber"], tags=["cruciferous"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 22, "iron_mg": 0.4, "zinc_mg": 0.3,
                   "selenium_mcg": 0.6, "vitamin_a_mcg": 0,
                   "folate_mcg": 57, "fiber_g": 2.0,
                   "vitamin_k_mcg": 16}),

    "cabbage": _entry("卷心菜", "Cabbage", "veg", 25, 1.3, 5.8, 0.1,
        fiber=2.5,
        validation=["dark_green_cruciferous"],
        execution=["cruciferous_fungi_algae"],
        roles=["vitamin_k"], tags=["cruciferous"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 40, "iron_mg": 0.5, "zinc_mg": 0.2,
                   "selenium_mcg": 0.3, "vitamin_a_mcg": 5,
                   "folate_mcg": 43, "fiber_g": 2.5,
                   "vitamin_k_mcg": 76}),

    "shiitake": _entry("香菇", "Shiitake mushroom", "veg", 34, 2.2, 6.8, 0.5,
        fiber=2.5,
        execution=["cruciferous_fungi_algae"],
        roles=["fiber"], tags=["fungi"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 3, "iron_mg": 0.4, "zinc_mg": 1.0,
                   "selenium_mcg": 5.7, "folate_mcg": 13,
                   "fiber_g": 2.5, "vitamin_e_mg": 0.0}),

    "shiitake_sun": _entry("干香菇（日晒）", "Sun-exposed shiitake", "veg", 34, 2.2, 6.8, 0.5,
        fiber=2.5,
        validation=["vitamin_d"], execution=["cruciferous_fungi_algae"],
        roles=["vitamin_d", "fiber"], tags=["fungi"],
        notes="Must be sun-exposed to provide vitamin D2.",
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 3, "iron_mg": 0.4, "zinc_mg": 1.0,
                   "selenium_mcg": 5.7, "vitamin_d_mcg": 13.4,
                   "folate_mcg": 13, "fiber_g": 2.5}),

    "enoki": _entry("金针菇", "Enoki mushroom", "veg", 37, 2.7, 7.8, 0.3,
        fiber=2.7,
        execution=["cruciferous_fungi_algae"],
        roles=["fiber"], tags=["fungi"],
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 3, "iron_mg": 1.1, "zinc_mg": 0.9,
                   "selenium_mcg": 1.4, "folate_mcg": 40,
                   "fiber_g": 2.7}),

    "wood_ear": _entry("木耳", "Wood ear mushroom", "veg", 25, 1.5, 6, 0.2,
        fiber=7.0,
        execution=["cruciferous_fungi_algae"],
        roles=["iron_tier2", "fiber"], tags=["fungi"],
        notes="Dry weight: ~35 g iron/100 g; values here are for rehydrated.",
        max_practical_serving_g=100,
        nutrients={"calcium_mg": 34, "iron_mg": 5.5, "zinc_mg": 0.5,
                   "selenium_mcg": 3.7, "folate_mcg": 12,
                   "fiber_g": 7.0}),

    "kelp": _entry("海带", "Kelp", "veg", 43, 1.7, 9.6, 0.6,
        fiber=1.6,
        validation=["iodine"], execution=["cruciferous_fungi_algae"],
        roles=["iodine", "fiber"], tags=["algae"],
        weekly_floor=2, max_practical_serving_g=100,
        nutrients={"calcium_mg": 241, "iron_mg": 3.3, "zinc_mg": 0.2,
                   "iodine_mcg": 240, "selenium_mcg": 4.9,
                   "folate_mcg": 180, "fiber_g": 11.3,
                   "vitamin_e_mg": 1.9}),

    "seaweed": _entry("紫菜 / 海苔", "Seaweed / nori", "veg", 35, 5.8, 5, 0.3,
        fiber=3.1,
        validation=["iodine"], execution=["cruciferous_fungi_algae"],
        roles=["iodine"], tags=["algae"],
        weekly_floor=2, max_practical_serving_g=10,
        nutrients={"calcium_mg": 264, "iron_mg": 54.9, "zinc_mg": 2.5,
                   "iodine_mcg": 4320, "selenium_mcg": 7.2,
                   "vitamin_a_mcg": 403, "b12_mcg": 0.0,
                   "folate_mcg": 146, "fiber_g": 21.5,
                   "vitamin_e_mg": 1.6}),

    "tomato": _entry("番茄", "Tomato", "veg", 18, 0.9, 3.9, 0.2,
        fiber=1.2,
        execution=["cruciferous_fungi_algae"],
        roles=[], tags=["veg"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 10, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.4, "vitamin_a_mcg": 42,
                   "folate_mcg": 15, "fiber_g": 1.2,
                   "vitamin_e_mg": 0.5, "vitamin_k_mcg": 8}),

    "cucumber": _entry("黄瓜", "Cucumber", "veg", 15, 0.7, 3.6, 0.1,
        fiber=0.5,
        execution=["cruciferous_fungi_algae"],
        roles=[], tags=["veg"],
        max_practical_serving_g=300,
        nutrients={"calcium_mg": 16, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.4, "vitamin_a_mcg": 5,
                   "folate_mcg": 7, "fiber_g": 0.5,
                   "vitamin_k_mcg": 16}),

    "carrot": _entry("胡萝卜", "Carrot", "veg", 41, 0.9, 10, 0.2,
        fiber=2.8,
        execution=["cruciferous_fungi_algae"],
        roles=["vitamin_a"], tags=["veg"],
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 33, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.7, "vitamin_a_mcg": 835,
                   "folate_mcg": 19, "fiber_g": 2.8,
                   "vitamin_e_mg": 0.7, "vitamin_k_mcg": 13}),

    # ── Fruits ────────────────────────────────────────────────────────────────
    "blueberry": _entry("蓝莓", "Blueberry", "carb", 57, 0.7, 14, 0.3,
        fiber=2.4,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 6, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.1, "vitamin_a_mcg": 3,
                   "folate_mcg": 6, "fiber_g": 2.4,
                   "vitamin_e_mg": 0.6, "vitamin_k_mcg": 19}),

    "strawberry": _entry("草莓", "Strawberry", "carb", 32, 0.7, 7.7, 0.3,
        fiber=2.0,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 16, "iron_mg": 0.4, "zinc_mg": 0.1,
                   "selenium_mcg": 0.4, "vitamin_a_mcg": 1,
                   "folate_mcg": 24, "fiber_g": 2.0,
                   "vitamin_k_mcg": 2}),

    "pineapple": _entry("菠萝", "Pineapple", "carb", 50, 0.5, 13, 0.1,
        fiber=1.4,
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 13, "iron_mg": 0.3, "zinc_mg": 0.1,
                   "selenium_mcg": 0.1, "folate_mcg": 18, "fiber_g": 1.4}),

    "mulberry": _entry("桑葚", "Mulberry", "carb", 43, 1.4, 10, 0.4,
        fiber=1.7,
        max_practical_serving_g=150,
        nutrients={"calcium_mg": 39, "iron_mg": 1.9, "zinc_mg": 0.1,
                   "selenium_mcg": 0.6, "vitamin_a_mcg": 1,
                   "folate_mcg": 6, "fiber_g": 1.7,
                   "vitamin_e_mg": 0.9, "vitamin_k_mcg": 7}),

    "apple": _entry("苹果", "Apple", "carb", 52, 0.3, 14, 0.2,
        fiber=2.4,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 6, "iron_mg": 0.1, "zinc_mg": 0.0,
                   "selenium_mcg": 0.0, "vitamin_a_mcg": 3,
                   "folate_mcg": 3, "fiber_g": 2.4,
                   "vitamin_k_mcg": 2}),

    "raspberry": _entry("树莓", "Raspberry", "carb", 52, 1.2, 12, 0.7,
        fiber=6.5,
        roles=["fiber"], max_practical_serving_g=150,
        nutrients={"calcium_mg": 25, "iron_mg": 0.7, "zinc_mg": 0.4,
                   "selenium_mcg": 0.2, "vitamin_a_mcg": 2,
                   "folate_mcg": 21, "fiber_g": 6.5,
                   "vitamin_k_mcg": 8}),

    "banana": _entry("香蕉", "Banana", "carb", 89, 1.1, 23, 0.3,
        fiber=2.6,
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 5, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 1.0, "vitamin_a_mcg": 3,
                   "folate_mcg": 20, "fiber_g": 2.6,
                   "vitamin_e_mg": 0.1, "vitamin_k_mcg": 1}),

    "orange": _entry("橙子", "Orange", "carb", 47, 0.9, 12, 0.1,
        fiber=2.4,
        roles=["folate"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 40, "iron_mg": 0.1, "zinc_mg": 0.1,
                   "selenium_mcg": 0.5, "vitamin_a_mcg": 11,
                   "folate_mcg": 30, "fiber_g": 2.4,
                   "vitamin_e_mg": 0.2, "vitamin_k_mcg": 0}),

    "kiwi": _entry("猕猴桃", "Kiwi", "carb", 61, 1.1, 15, 0.5,
        fiber=3.0,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 34, "iron_mg": 0.3, "zinc_mg": 0.1,
                   "selenium_mcg": 0.2, "vitamin_a_mcg": 4,
                   "folate_mcg": 25, "fiber_g": 3.0,
                   "vitamin_e_mg": 1.5, "vitamin_k_mcg": 40}),

    # ── Nuts ──────────────────────────────────────────────────────────────────
    # Generic "nuts" entry removed — use specific slugs below.
    # weekly_floor is now enforced at the validation-bucket level in the audit.

    "walnuts": _entry("核桃", "Walnuts", "fat", 654, 15, 14, 65,
        fiber=6.7,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["omega3", "vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 98, "iron_mg": 2.9, "zinc_mg": 3.1,
                   "selenium_mcg": 4.9, "vitamin_a_mcg": 1,
                   "folate_mcg": 98, "fiber_g": 6.7,
                   "vitamin_e_mg": 0.7, "omega3_g": 9.1}),

    "almonds": _entry("杏仁", "Almonds", "fat", 579, 21, 22, 50,
        fiber=12.5,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e", "calcium"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 264, "iron_mg": 3.7, "zinc_mg": 3.1,
                   "selenium_mcg": 4.1, "folate_mcg": 44,
                   "fiber_g": 12.5, "vitamin_e_mg": 25.6}),

    "cashews": _entry("腰果", "Cashews", "fat", 553, 18, 30, 44,
        fiber=3.3,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["iron_tier2"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 37, "iron_mg": 6.7, "zinc_mg": 5.8,
                   "selenium_mcg": 19.9, "folate_mcg": 25,
                   "fiber_g": 3.3, "vitamin_e_mg": 0.9}),

    "pumpkin_seeds": _entry("南瓜子", "Pumpkin seeds", "fat", 559, 30, 11, 49,
        fiber=6.0,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["zinc", "iron_tier2"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 46, "iron_mg": 15.0, "zinc_mg": 7.8,
                   "selenium_mcg": 9.4, "folate_mcg": 57,
                   "fiber_g": 18.4, "vitamin_e_mg": 2.2,
                   "omega3_g": 0.2}),

    "sunflower_seeds": _entry("葵花籽", "Sunflower seeds", "fat", 584, 21, 20, 51,
        fiber=8.6,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 78, "iron_mg": 5.2, "zinc_mg": 5.0,
                   "selenium_mcg": 53, "folate_mcg": 227,
                   "fiber_g": 8.6, "vitamin_e_mg": 35.2}),

    "brazil_nuts": _entry("巴西坚果", "Brazil nuts", "fat", 656, 14, 12, 66,
        fiber=7.5,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["selenium", "vitamin_e"], tags=["nut_seed"],
        notes="Extremely selenium-dense — 1-2 nuts/day is already a full weekly dose.",
        max_practical_serving_g=6,
        nutrients={"calcium_mg": 160, "iron_mg": 2.4, "zinc_mg": 4.1,
                   "selenium_mcg": 1917, "folate_mcg": 22,
                   "fiber_g": 7.5, "vitamin_e_mg": 5.7}),

    "flaxseed": _entry("亚麻籽", "Flaxseed", "fat", 534, 18, 29, 42,
        fiber=27.3,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["omega3", "fiber"], tags=["nut_seed"],
        notes="Primary omega-3 is ALA (plant-source). High fiber — grind before use.",
        max_practical_serving_g=15,
        nutrients={"calcium_mg": 255, "iron_mg": 5.7, "zinc_mg": 4.3,
                   "selenium_mcg": 25.4, "folate_mcg": 87,
                   "fiber_g": 27.3, "vitamin_e_mg": 0.3,
                   "omega3_g": 22.8}),

    "chia_seed": _entry("奇亚籽", "Chia seed", "fat", 486, 17, 42, 31,
        fiber=34.4,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["omega3", "fiber", "calcium"], tags=["nut_seed"],
        notes="High fiber and ALA omega-3; 42 g carbs/100 g but ~34 g are fiber — net carbs ~8 g.",
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 631, "iron_mg": 7.7, "zinc_mg": 4.6,
                   "selenium_mcg": 55.2, "folate_mcg": 49,
                   "fiber_g": 34.4, "vitamin_e_mg": 0.5,
                   "omega3_g": 17.8}),

    "sesame": _entry("芝麻", "Sesame seeds", "fat", 573, 18, 23, 50,
        fiber=11.8,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["calcium"], tags=["nut_seed"],
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 975, "iron_mg": 14.6, "zinc_mg": 7.8,
                   "selenium_mcg": 34.4, "folate_mcg": 97,
                   "fiber_g": 11.8, "vitamin_e_mg": 2.5}),

    "pine_nuts": _entry("松子", "Pine nuts", "fat", 673, 14, 13, 68,
        fiber=3.7,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 16, "iron_mg": 5.5, "zinc_mg": 6.4,
                   "selenium_mcg": 0.7, "folate_mcg": 58,
                   "fiber_g": 3.7, "vitamin_e_mg": 9.3,
                   "omega3_g": 0.2}),

    "pistachios": _entry("开心果", "Pistachios", "fat", 562, 20, 28, 45,
        fiber=10.3,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 107, "iron_mg": 3.9, "zinc_mg": 2.2,
                   "selenium_mcg": 7.0, "vitamin_a_mcg": 26,
                   "folate_mcg": 51, "fiber_g": 10.3,
                   "vitamin_e_mg": 2.3, "vitamin_k_mcg": 14}),

    "hazelnuts": _entry("榛子", "Hazelnuts", "fat", 628, 15, 17, 61,
        fiber=9.7,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 114, "iron_mg": 4.7, "zinc_mg": 2.5,
                   "selenium_mcg": 2.4, "vitamin_a_mcg": 1,
                   "folate_mcg": 113, "fiber_g": 9.7,
                   "vitamin_e_mg": 15.0}),

    "peanuts": _entry("花生", "Peanuts", "fat", 567, 26, 16, 49,
        fiber=8.5,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 92, "iron_mg": 4.6, "zinc_mg": 3.3,
                   "selenium_mcg": 7.2, "folate_mcg": 240,
                   "fiber_g": 8.5, "vitamin_e_mg": 8.3}),

    "macadamia": _entry("澳洲坚果", "Macadamia nuts", "fat", 718, 8, 14, 76,
        fiber=8.6,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 85, "iron_mg": 3.7, "zinc_mg": 1.3,
                   "selenium_mcg": 3.6, "folate_mcg": 11,
                   "fiber_g": 8.6, "vitamin_e_mg": 0.5}),

    # ── Functional / condiment ────────────────────────────────────────────────
    "iodized_salt": _entry("加碘盐", "Iodized salt", "condiment", 0, 0, 0, 0,
        validation=["iodine"], execution=[],
        roles=["iodine"], tags=["condiment"],
        notes="25 mg iodine per kg salt; typical use ~5 g/day → ~125 mcg iodine.",
        max_practical_serving_g=5,
        nutrients={"iodine_mcg": 2500}),

    "olive_oil": _entry("橄榄油", "Olive oil", "fat", 884, 0, 0, 100,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["oil"],
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 1, "iron_mg": 0.6, "zinc_mg": 0.0,
                   "selenium_mcg": 0.0, "vitamin_e_mg": 14.4,
                   "vitamin_k_mcg": 60}),

    # User-facing overrides and newly allowed preference items.
    # Keep these near the end so corrected slugs override any historical mojibake
    # entries defined earlier in the literal.
    "blueberry": _entry("蓝莓", "Blueberry", "carb", 57, 0.7, 14, 0.3,
        fiber=2.4,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 6, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.1, "vitamin_a_mcg": 3,
                   "folate_mcg": 6, "fiber_g": 2.4,
                   "vitamin_e_mg": 0.6, "vitamin_k_mcg": 19}),

    "strawberry": _entry("草莓", "Strawberry", "carb", 32, 0.7, 7.7, 0.3,
        fiber=2.0,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 16, "iron_mg": 0.4, "zinc_mg": 0.1,
                   "selenium_mcg": 0.4, "vitamin_a_mcg": 1,
                   "folate_mcg": 24, "fiber_g": 2.0,
                   "vitamin_k_mcg": 2}),

    "cherry_tomato": _entry("圣女果", "Cherry tomato", "veg", 18, 0.9, 3.9, 0.2,
        fiber=1.2,
        execution=["cruciferous_fungi_algae"],
        roles=[], tags=["veg"],
        max_practical_serving_g=250,
        nutrients={"calcium_mg": 10, "iron_mg": 0.3, "zinc_mg": 0.2,
                   "selenium_mcg": 0.4, "vitamin_a_mcg": 42,
                   "folate_mcg": 15, "fiber_g": 1.2,
                   "vitamin_e_mg": 0.5, "vitamin_k_mcg": 7}),

    "pineapple": _entry("菠萝", "Pineapple", "carb", 50, 0.5, 13, 0.1,
        fiber=1.4,
        max_practical_serving_g=200,
        nutrients={"calcium_mg": 13, "iron_mg": 0.3, "zinc_mg": 0.1,
                   "selenium_mcg": 0.1, "folate_mcg": 18, "fiber_g": 1.4}),

    "kiwi": _entry("猕猴桃", "Kiwi", "carb", 61, 1.1, 15, 0.5,
        fiber=3.0,
        roles=["fiber"], max_practical_serving_g=200,
        nutrients={"calcium_mg": 34, "iron_mg": 0.3, "zinc_mg": 0.1,
                   "selenium_mcg": 0.2, "vitamin_a_mcg": 4,
                   "folate_mcg": 25, "fiber_g": 3.0,
                   "vitamin_e_mg": 1.5, "vitamin_k_mcg": 40}),

    "pomelo": _entry("柚子", "Pomelo", "carb", 38, 0.8, 9.6, 0.0,
        fiber=1.0,
        roles=["folate"], max_practical_serving_g=300,
        nutrients={"calcium_mg": 4, "iron_mg": 0.1, "zinc_mg": 0.1,
                   "selenium_mcg": 0.1, "vitamin_a_mcg": 2,
                   "folate_mcg": 13, "fiber_g": 1.0,
                   "vitamin_e_mg": 0.0, "vitamin_k_mcg": 0}),

    "nut_mix": _entry("坚果堆", "Mixed nuts", "fat", 607, 18, 21, 54,
        fiber=8.5,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["nut_seed"],
        max_practical_serving_g=30,
        nutrients={"calcium_mg": 120, "iron_mg": 3.1, "zinc_mg": 3.0,
                   "selenium_mcg": 7.0, "folate_mcg": 65,
                   "fiber_g": 8.5, "vitamin_e_mg": 7.2}),

    "chia_seed": _entry("奇亚籽", "Chia seed", "fat", 486, 17, 42, 31,
        fiber=34.4,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["omega3", "fiber", "calcium"], tags=["nut_seed"],
        notes="High fiber and ALA omega-3; 42 g carbs/100 g but ~34 g are fiber 鈥?net carbs ~8 g.",
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 631, "iron_mg": 7.7, "zinc_mg": 4.6,
                   "selenium_mcg": 55.2, "folate_mcg": 49,
                   "fiber_g": 34.4, "vitamin_e_mg": 0.5,
                   "omega3_g": 17.8}),

    "sesame": _entry("芝麻", "Sesame seeds", "fat", 573, 18, 23, 50,
        fiber=11.8,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["calcium"], tags=["nut_seed"],
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 975, "iron_mg": 14.6, "zinc_mg": 7.8,
                   "selenium_mcg": 34.4, "folate_mcg": 97,
                   "fiber_g": 11.8, "vitamin_e_mg": 2.5}),

    "olive_oil": _entry("橄榄油", "Olive oil", "fat", 884, 0, 0, 100,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["oil"],
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 1, "iron_mg": 0.6, "zinc_mg": 0.0,
                   "selenium_mcg": 0.0, "vitamin_e_mg": 14.4,
                   "vitamin_k_mcg": 60}),

    "cooking_oil": _entry("其他炒菜油", "Cooking oil", "fat", 884, 0, 0, 100,
        validation=["vitamin_e_healthy_fat"],
        execution=["nut_seed_functional"],
        roles=["vitamin_e"], tags=["oil"],
        max_practical_serving_g=20,
        nutrients={"calcium_mg": 0, "iron_mg": 0.0, "zinc_mg": 0.0,
                   "selenium_mcg": 0.0, "vitamin_e_mg": 8.0,
                   "vitamin_k_mcg": 24}),
}


# ── Accessors ─────────────────────────────────────────────────────────────────
def get_food(slug: str) -> Optional[dict]:
    return FOOD_LIBRARY.get(slug)


def all_slugs() -> list[str]:
    return sorted(FOOD_LIBRARY.keys())


def slugs_by_validation_bucket(bucket: str) -> list[str]:
    return [s for s, f in FOOD_LIBRARY.items() if bucket in f["validation_buckets"]]


def slugs_by_execution_bucket(bucket: str) -> list[str]:
    return [s for s, f in FOOD_LIBRARY.items() if bucket in f["execution_buckets"]]


def slugs_by_micronutrient(role: str) -> list[str]:
    matches: list[str] = []
    for slug, f in FOOD_LIBRARY.items():
        for declared in f["micronutrient_roles"]:
            if _strip_tier(declared) == role:
                matches.append(slug)
                break
    return matches


def filter_library(slugs: Iterable[str]) -> dict[str, dict]:
    return {s: FOOD_LIBRARY[s] for s in slugs if s in FOOD_LIBRARY}


def display_name(slug: str, lang: str = "zh") -> str:
    f = FOOD_LIBRARY.get(slug)
    if not f:
        return slug
    return f.get(lang) or f.get("zh") or slug


def substitutes_for(slug: str, candidate_pool: Optional[Iterable[str]] = None) -> list[str]:
    """Return slugs that can substitute `slug` without nutritional regression.

    A substitute must:
      1. Share at least one execution bucket with the target food (same meal slot).
      2. Cover every micronutrient role the target carries (no role left uncovered).

    If `candidate_pool` is given, only foods in that set are considered (useful
    for within-library substitution). Otherwise the full FOOD_LIBRARY is searched.
    """
    target = FOOD_LIBRARY.get(slug)
    if not target:
        return []

    target_buckets = set(target["execution_buckets"])
    target_roles = {_strip_tier(r) for r in target["micronutrient_roles"]}

    pool = candidate_pool if candidate_pool is not None else FOOD_LIBRARY.keys()
    result: list[str] = []
    for candidate in pool:
        if candidate == slug:
            continue
        entry = FOOD_LIBRARY.get(candidate)
        if not entry:
            continue
        if not target_buckets & set(entry["execution_buckets"]):
            continue
        candidate_roles = {_strip_tier(r) for r in entry["micronutrient_roles"]}
        if target_roles <= candidate_roles:
            result.append(candidate)
    return sorted(result)
