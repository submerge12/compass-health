from __future__ import annotations

import re
from typing import Any, Optional

from services import food_library as FL


_OIL_TERMS = ("食用油", "橄榄油", "花生油", "菜籽油", "玉米油", "香油", "芝麻油", "油")
_SUGAR_TERMS = ("白糖", "糖", "冰糖", "蜂蜜", "糖浆")
_SAUCE_TERMS = ("沙拉酱", "蛋黄酱", "花生酱", "芝麻酱", "火锅底料", "辣椒油", "红油")
_FATTY_TERMS = ("五花肉", "肥牛", "肥羊", "培根", "香肠", "腊肠", "肥肉", "奶油", "黄油", "芝士")
_PROTEIN_TERMS = (
    "鸡胸", "鸡腿", "鸡蛋", "牛肉", "牛里脊", "虾", "鱼", "三文鱼", "鳕鱼", "巴沙鱼",
    "龙利鱼", "豆腐", "豆干", "牛奶", "酸奶", "鸡肉", "瘦肉",
)
_VEG_TERMS = (
    "西兰花", "菠菜", "油菜", "上海青", "娃娃菜", "白菜", "生菜", "黄瓜", "番茄", "西红柿",
    "洋葱", "青椒", "彩椒", "蘑菇", "香菇", "金针菇", "芦笋", "莴笋", "西葫芦", "胡萝卜",
)
_LOW_FAT_METHODS = ("蒸", "煮", "炖", "焖", "凉拌", "水煮", "白灼", "空气炸锅", "烤")
_RISK_METHODS = ("油炸", "炸", "干炸", "酥炸", "煎炸", "红油", "重油")
_MID_METHODS = ("煎", "炒", "爆炒", "红烧")

_ALIAS_TO_SLUG = {
    "鸡胸": "chicken_breast",
    "鸡胸肉": "chicken_breast",
    "鸡腿": "chicken_thigh",
    "鸡蛋": "whole_egg",
    "蛋": "whole_egg",
    "虾仁": "shrimp",
    "虾": "shrimp",
    "牛里脊": "beef_tenderloin",
    "牛肉": "beef_tenderloin",
    "三文鱼": "salmon",
    "鳕鱼": "cod",
    "巴沙鱼": "basa_fish",
    "龙利鱼": "basa_fish",
    "豆腐": "tofu_firm",
    "豆干": "tofu_dry",
    "西兰花": "broccoli",
    "菠菜": "spinach",
    "油菜": "you_cai",
    "娃娃菜": "baby_napa_cabbage",
    "洋葱": "onion",
    "青椒": "green_pepper",
    "彩椒": "bell_pepper",
    "蘑菇": "mushroom",
    "香菇": "shiitake",
    "莴笋": "celtuce",
    "西葫芦": "zucchini",
    "魔芋": "konjac",
    "红豆": "red_beans",
    "绿豆": "mung_beans",
    "黑豆": "black_beans",
    "米饭": "rice_cooked",
    "糙米": "brown_rice_cooked",
    "燕麦": "oats",
    "土豆": "potato",
    "红薯": "sweet_potato",
    "芝麻酱": "sesame_paste",
}


def _grams_from_line(line: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(克|g|G|毫升|ml|mL|ML)", line)
    if match:
        value = float(match.group(1))
        unit = match.group(2).lower()
        return round(value * 0.9, 1) if unit in {"毫升", "ml"} else round(value, 1)

    egg_match = re.search(r"(\d+(?:\.\d+)?)\s*(个|只)\s*(鸡蛋|蛋)", line)
    if egg_match:
        return round(float(egg_match.group(1)) * 55.0, 1)

    return None


def _split_lines(text: str) -> list[str]:
    lines = []
    for raw in re.split(r"[\n；;]+", text or ""):
        line = raw.strip().lstrip("•-·").strip()
        if line:
            lines.append(line)
    return lines


def _match_slug(line: str) -> Optional[str]:
    for term, slug in _ALIAS_TO_SLUG.items():
        if term in line and slug in FL.FOOD_LIBRARY:
            return slug
    lower = line.lower()
    for slug, entry in FL.FOOD_LIBRARY.items():
        if entry.get("zh") and str(entry["zh"]) in line:
            return slug
        if entry.get("en") and str(entry["en"]).lower() in lower:
            return slug
    return None


def _estimate_nutrition(ingredients: str, servings: int) -> tuple[list[dict], dict]:
    parsed: list[dict] = []
    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for line in _split_lines(ingredients):
        grams = _grams_from_line(line)
        slug = _match_slug(line)
        if not slug or grams is None:
            continue
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        factor = grams / 100.0
        kcal = entry["kcal_per_100g"] * factor
        protein = entry["protein_per_100g"] * factor
        carbs = entry["carbs_per_100g"] * factor
        fat = entry["fat_per_100g"] * factor
        totals["kcal"] += kcal
        totals["protein_g"] += protein
        totals["carbs_g"] += carbs
        totals["fat_g"] += fat
        parsed.append({
            "line": line,
            "slug": slug,
            "name_zh": entry["zh"],
            "grams": grams,
            "kcal": round(kcal, 1),
            "protein_g": round(protein, 1),
            "carbs_g": round(carbs, 1),
            "fat_g": round(fat, 1),
        })

    safe_servings = max(1, servings)
    per_serving = {
        "kcal": round(totals["kcal"] / safe_servings, 1),
        "protein_g": round(totals["protein_g"] / safe_servings, 1),
        "carbs_g": round(totals["carbs_g"] / safe_servings, 1),
        "fat_g": round(totals["fat_g"] / safe_servings, 1),
        "coverage": "estimated" if parsed else "low_confidence",
    }
    return parsed, per_serving


def _sum_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _oil_grams(ingredients: str) -> Optional[float]:
    grams = 0.0
    found = False
    for line in _split_lines(ingredients):
        if any(term in line for term in _OIL_TERMS):
            amount = _grams_from_line(line)
            if amount is not None:
                grams += amount
                found = True
    return round(grams, 1) if found else None


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def _dimension_scores(text: str, ingredients: str, servings: int, per_serving: dict) -> dict:
    oil = _oil_grams(ingredients)
    oil_per_serving = oil / max(1, servings) if oil is not None else None
    risk_methods = _sum_terms(text, _RISK_METHODS)
    mid_methods = _sum_terms(text, _MID_METHODS)
    fatty_terms = _sum_terms(text, _FATTY_TERMS)
    sauce_terms = _sum_terms(text, _SAUCE_TERMS)
    sugar_terms = _sum_terms(text, _SUGAR_TERMS)
    low_fat_methods = _sum_terms(text, _LOW_FAT_METHODS)

    fat_score = 92
    if oil_per_serving is None:
        fat_score -= 8
    elif oil_per_serving > 20:
        fat_score -= 38
    elif oil_per_serving > 12:
        fat_score -= 24
    elif oil_per_serving > 8:
        fat_score -= 12
    elif oil_per_serving <= 5:
        fat_score += 4
    fat_score -= 14 * len(fatty_terms)
    fat_score -= 8 * len(sauce_terms)
    fat_score -= 10 * len(risk_methods)

    kcal = per_serving.get("kcal") or 0
    if per_serving.get("coverage") == "low_confidence" or kcal <= 0:
        calorie_score = 68
    elif kcal <= 420:
        calorie_score = 95
    elif kcal <= 550:
        calorie_score = 82
    elif kcal <= 700:
        calorie_score = 62
    else:
        calorie_score = 42

    protein = per_serving.get("protein_g") or 0
    if protein >= 30:
        protein_score = 96
    elif protein >= 20:
        protein_score = 84
    elif protein >= 12:
        protein_score = 68
    elif _sum_terms(text, _PROTEIN_TERMS):
        protein_score = 64
    else:
        protein_score = 45

    veg_hits = _sum_terms(text, _VEG_TERMS)
    veg_score = 90 if len(set(veg_hits)) >= 2 else (76 if veg_hits else 48)

    method_score = 78
    if risk_methods:
        method_score = 42
    elif low_fat_methods:
        method_score = 92
    elif mid_methods:
        method_score = 74

    line_count = len(_split_lines(ingredients))
    quantified_count = sum(1 for line in _split_lines(ingredients) if _grams_from_line(line) is not None)
    clarity_score = 55 if not line_count else 55 + 45 * (quantified_count / line_count)
    if servings <= 0:
        clarity_score -= 15

    if sugar_terms:
        calorie_score -= 8 * len(sugar_terms)

    return {
        "fat_control": _clamp(fat_score),
        "calorie_density": _clamp(calorie_score),
        "protein_quality": _clamp(protein_score),
        "fiber_and_vegetables": _clamp(veg_score),
        "cooking_method": _clamp(method_score),
        "portion_clarity": _clamp(clarity_score),
    }


def _grade(score: int) -> tuple[str, str]:
    if score >= 85:
        return "excellent", "green"
    if score >= 70:
        return "fit", "green"
    if score >= 55:
        return "caution", "yellow"
    return "not_fit", "red"


def _suggestions(text: str, ingredients: str, servings: int, per_serving: dict, scores: dict) -> list[str]:
    tips: list[str] = []
    oil = _oil_grams(ingredients)
    oil_per_serving = oil / max(1, servings) if oil is not None else None
    if oil_per_serving is None:
        tips.append("标清食用油克数，低脂评估会更可靠。")
    elif oil_per_serving > 8:
        tips.append("把每份用油控制到 5-8g，优先用不粘锅、蒸煮或焯水后快炒。")
    if _sum_terms(text, _RISK_METHODS):
        tips.append("避免油炸/红油做法，改成蒸、煮、炖、烤或少油煎。")
    if _sum_terms(text, _FATTY_TERMS):
        tips.append("把肥肉、培根、奶油、黄油这类高脂食材换成鸡胸、虾仁、鱼或瘦牛肉。")
    if _sum_terms(text, _SAUCE_TERMS):
        tips.append("酱料按克数使用，芝麻酱、花生酱、沙拉酱建议减半或做蘸料。")
    if scores["protein_quality"] < 70:
        tips.append("补一个明确的优质蛋白来源，例如鸡胸肉、虾仁、鱼、蛋或豆腐。")
    if scores["fiber_and_vegetables"] < 70:
        tips.append("每份增加 150-250g 蔬菜或菌菇，提高饱腹感。")
    if per_serving.get("kcal", 0) > 550:
        tips.append("总量偏高时，先减主食或高脂配料，不要先砍蛋白质。")
    return tips[:4] or ["整体结构不错，保持清晰克数和少油做法即可。"]


def assess_low_fat_recipe(
    *,
    name: str,
    ingredients: str,
    steps: str,
    servings: int = 1,
) -> dict:
    """Score a submitted recipe for low-fat/fat-loss suitability."""
    safe_servings = max(1, int(servings or 1))
    text = "\n".join([name or "", ingredients or "", steps or ""])
    parsed, per_serving = _estimate_nutrition(ingredients or "", safe_servings)
    scores = _dimension_scores(text, ingredients or "", safe_servings, per_serving)
    weighted = (
        scores["fat_control"] * 0.30
        + scores["calorie_density"] * 0.20
        + scores["protein_quality"] * 0.18
        + scores["fiber_and_vegetables"] * 0.14
        + scores["cooking_method"] * 0.10
        + scores["portion_clarity"] * 0.08
    )
    score = _clamp(weighted)
    grade, traffic_light = _grade(score)
    oil = _oil_grams(ingredients or "")
    flags = []
    for key, terms in (
        ("high_fat_ingredient", _FATTY_TERMS),
        ("heavy_sauce", _SAUCE_TERMS),
        ("sugar_added", _SUGAR_TERMS),
        ("fried_or_heavy_oil_method", _RISK_METHODS),
    ):
        hits = _sum_terms(text, terms)
        if hits:
            flags.append({"key": key, "terms": hits})
    if oil is not None:
        flags.append({"key": "oil_grams", "grams_total": oil, "grams_per_serving": round(oil / safe_servings, 1)})

    return {
        "score": score,
        "grade": grade,
        "traffic_light": traffic_light,
        "servings": safe_servings,
        "dimension_scores": scores,
        "estimated_nutrition_per_serving": per_serving,
        "matched_ingredients": parsed,
        "risk_flags": flags,
        "suggestions": _suggestions(text, ingredients or "", safe_servings, per_serving, scores),
        "summary_zh": _summary_zh(score, grade, per_serving),
    }


def _summary_zh(score: int, grade: str, per_serving: dict) -> str:
    grade_text = {
        "excellent": "很适合低脂/减脂期",
        "fit": "整体适合低脂/减脂期",
        "caution": "可以吃，但需要调整做法或份量",
        "not_fit": "当前做法不太适合低脂/减脂期",
    }.get(grade, "需要更多信息")
    kcal = per_serving.get("kcal")
    protein = per_serving.get("protein_g")
    fat = per_serving.get("fat_g")
    if per_serving.get("coverage") == "estimated" and kcal:
        return f"{grade_text}，评分 {score}/100；估算每份约 {kcal} kcal，蛋白质 {protein}g，脂肪 {fat}g。"
    return f"{grade_text}，评分 {score}/100；食材克数不完整，营养估算置信度偏低。"
