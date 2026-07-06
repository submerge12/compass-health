"""
Build an integrated food nutrition database from multiple Chinese and international sources.

Primary:   中国食物成分表.xlsx (1,752 foods, 38 nutrient columns)
Supplement: CFCT6 (Nitr-Navigator 6th ed.) — fill missing sodium, add missing foods
Supplement: Juhe — fill dietary fiber, iodine, fatty acid ratios
Supplement: USDA — add international items (Greek yogurt, etc.)

Output:    integrated_food_nutrition.csv
"""

import openpyxl
import csv
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX_PATH = os.path.join(BASE_DIR, "中国食物成分表.xlsx")
PER_SOURCE = os.path.join(BASE_DIR, "per_source_food_nutrition")
CFCT6_DIR = os.path.join(PER_SOURCE, "04_nitr_navigator_cfct6_json")
JUHE_DIR = os.path.join(PER_SOURCE, "02_juhe_food_nutrition_11087")
USDA_DIR = os.path.join(PER_SOURCE, "05_usda_fooddata_central")
OUTPUT_PATH = os.path.join(BASE_DIR, "integrated_food_nutrition.csv")

# Manual sodium overrides for items that don't match by exact name across sources.
# {xlsx_name_substring: sodium_mg}
MANUAL_SODIUM = {
    "馒头（代表值）": 165.1,       # Juhe: 馒头(均值) = 165.1mg
    "馒头（标准粉）": 232.0,       # Juhe: 馒头(标准粉) = 232.0mg
    "馒头（富强粉）": 142.0,       # Juhe: 馒头(富强粉) = 142.0mg
}

FIELDS = [
    "food_id", "slug", "name_zh", "name_en", "category_code", "category_zh",
    "edible_percent", "source_primary", "source_supplements",
    "energy_kcal", "energy_kj",
    "water_g", "protein_g", "fat_g", "carbohydrate_g", "dietary_fiber_g",
    "cholesterol_mg", "ash_g",
    "vitamin_a_ug_re", "thiamin_mg", "riboflavin_mg", "niacin_mg", "vitamin_c_mg",
    "vitamin_e_mg", "alpha_vitamin_e_mg",
    "calcium_mg", "phosphorus_mg", "potassium_mg", "sodium_mg",
    "magnesium_mg", "iron_mg", "zinc_mg", "selenium_ug", "copper_mg", "manganese_mg",
    "iodine_ug",
    "carotene_ug", "retinol_ug",
    "sfa_percent", "mufa_percent", "pufa_percent",
    "basis",
]


def safe_float(v, default=None):
    if v is None or v == "" or v == "—" or v == "Tr" or v == "None":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def slugify(name_zh):
    """Simple slug from Chinese name — replace brackets and spaces."""
    s = name_zh.strip()
    s = re.sub(r"[（(].+?[）)]", "", s)
    s = re.sub(r"\[.+?\]", "", s)
    s = s.strip().replace(" ", "_").replace("，", "_").replace(",", "_")
    return s


# ── Step 1: Load CFCT6 foods + sodium values ────────────────────────────

def load_cfct6_sodium():
    """Returns {cfct6_code: sodium_mg} for all cfct6 foods."""
    sodium_map = {}
    path = os.path.join(CFCT6_DIR, "food_nutrients.csv")
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["nutrient_code"] == "sodium":
                code = row["source_food_id"]
                val = safe_float(row["amount"])
                if val is not None:
                    sodium_map[code] = val
    return sodium_map


def load_cfct6_foods():
    """Returns {name_zh_normalized: {food_id, name_zh, sodium, ...}}."""
    foods = {}
    path = os.path.join(CFCT6_DIR, "foods.csv")
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name_zh"].strip()
            norm = re.sub(r"\s+", "", name)
            foods[norm] = {
                "food_id": row["food_id"],
                "source_food_id": row["source_food_id"],
                "name_zh": name,
                "edible": safe_float(row["edible_part_percent"]),
            }
    return foods


def load_cfct6_nutrients():
    """Returns {food_id: {nutrient_code: amount}}."""
    data = {}
    path = os.path.join(CFCT6_DIR, "food_nutrients.csv")
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row["food_id"]
            if fid not in data:
                data[fid] = {}
            val = safe_float(row["amount"])
            data[fid][row["nutrient_code"]] = val
    return data


# ── Step 2: Load Juhe supplements (fiber, iodine, fatty acids) ──────────

def load_juhe_supplements():
    """Returns {name_zh_normalized: {fiber, iodine, sfa, mufa, pufa}}."""
    foods = {}
    foods_path = os.path.join(JUHE_DIR, "foods.csv")
    nutrients_path = os.path.join(JUHE_DIR, "food_nutrients.csv")

    name_map = {}
    with open(foods_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name_zh"].strip()
            norm = re.sub(r"\s+", "", name)
            name_map[row["food_id"]] = norm

    nutrients = {}
    with open(nutrients_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row["food_id"]
            code = row["nutrient_code"]
            if code in ("dietary_fiber", "iodine", "sfa_percent", "mufa_percent",
                        "pufa_percent"):
                if fid not in nutrients:
                    nutrients[fid] = {}
                nutrients[fid][code] = safe_float(row["amount"])

    for fid, norm_name in name_map.items():
        if fid in nutrients:
            foods[norm_name] = nutrients[fid]

    return foods


# ── Step 3: Load USDA for supplementary items ───────────────────────────

def load_usda_greek_yogurt():
    """Search USDA for Greek yogurt and return as a food dict."""
    foods_path = os.path.join(USDA_DIR, "foods.csv")
    nutrients_path = os.path.join(USDA_DIR, "food_nutrients.csv")

    yogurt_ids = []
    with open(foods_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name_zh", "") + " " + row.get("name_en", "")).lower()
            if "greek" in name and "yogurt" in name and ("plain" in name or "nonfat" in name):
                yogurt_ids.append(row["food_id"])
                break

    if not yogurt_ids:
        with open(foods_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                desc = row.get("description_original", "").lower()
                if "greek" in desc and "yogurt" in desc and "plain" in desc:
                    yogurt_ids.append(row["food_id"])
                    break

    if not yogurt_ids:
        return None

    nutrients = {}
    target_id = yogurt_ids[0]
    with open(nutrients_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["food_id"] == target_id:
                nutrients[row["nutrient_code"]] = safe_float(row["amount"])

    return {
        "food_id": "usda_greek_yogurt",
        "slug": "greek_yogurt_plain_nonfat",
        "name_zh": "无糖希腊酸奶（脱脂）",
        "name_en": "Greek yogurt, plain, nonfat",
        "category_code": "10",
        "category_zh": "乳类及其制品",
        "edible_percent": 100,
        "source_primary": "usda",
        "source_supplements": "",
        "energy_kcal": nutrients.get("energy_kcal", nutrients.get("energy", 59)),
        "energy_kj": nutrients.get("energy_kj", 247),
        "water_g": nutrients.get("water", 81.3),
        "protein_g": nutrients.get("protein", 10.2),
        "fat_g": nutrients.get("fat", 0.7),
        "carbohydrate_g": nutrients.get("carbohydrate", 3.6),
        "dietary_fiber_g": nutrients.get("dietary_fiber", 0),
        "cholesterol_mg": nutrients.get("cholesterol", 5),
        "ash_g": nutrients.get("ash", 0),
        "vitamin_a_ug_re": nutrients.get("vitamin_a", 2),
        "thiamin_mg": nutrients.get("thiamin", 0.02),
        "riboflavin_mg": nutrients.get("riboflavin", 0.27),
        "niacin_mg": nutrients.get("niacin", 0.21),
        "vitamin_c_mg": nutrients.get("vitamin_c", 0),
        "vitamin_e_mg": nutrients.get("vitamin_e_total", 0),
        "alpha_vitamin_e_mg": nutrients.get("vitamin_e_alpha", 0),
        "calcium_mg": nutrients.get("calcium", 100),
        "phosphorus_mg": nutrients.get("phosphorus", 135),
        "potassium_mg": nutrients.get("potassium", 141),
        "sodium_mg": nutrients.get("sodium", 36),
        "magnesium_mg": nutrients.get("magnesium", 11),
        "iron_mg": nutrients.get("iron", 0.1),
        "zinc_mg": nutrients.get("zinc", 0.5),
        "selenium_ug": nutrients.get("selenium", 9.7),
        "copper_mg": nutrients.get("copper", 0),
        "manganese_mg": nutrients.get("manganese", 0),
        "iodine_ug": None,
        "carotene_ug": nutrients.get("carotene", 0),
        "retinol_ug": nutrients.get("retinol", 2),
        "sfa_percent": None,
        "mufa_percent": None,
        "pufa_percent": None,
        "basis": "per_100g_edible_portion",
    }


# ── Step 4: Process xlsx as primary, supplement from other sources ───────

def build_integrated_db():
    print("Loading supplementary data...")
    cfct6_sodium = load_cfct6_sodium()
    cfct6_foods = load_cfct6_foods()
    cfct6_nutrients = load_cfct6_nutrients()
    juhe_supps = load_juhe_supplements()
    print("  CFCT6: {} foods with sodium".format(len(cfct6_sodium)))
    print("  CFCT6: {} foods total".format(len(cfct6_foods)))
    print("  Juhe supplements: {} foods".format(len(juhe_supps)))

    # Load category mapping from xlsx sheet 2
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True)
    ws_cat = wb[wb.sheetnames[1]]
    cat_map = {}
    for row in ws_cat.iter_rows(min_row=3, values_only=True):
        if row[1] and row[3]:
            cat_map[str(row[1]).strip()] = str(row[3]).strip()

    # Process main food sheet
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    next(rows_iter)  # title
    next(rows_iter)  # headers

    results = []
    xlsx_names = set()

    for row in rows_iter:
        vals = list(row)
        if vals[0] is None:
            continue

        seq = int(vals[0])
        name_zh = str(vals[1]).strip()
        cat_code = str(vals[2]).strip() if vals[2] else ""
        sub_code = str(vals[3]).strip() if vals[3] else ""
        cat_name = cat_map.get(cat_code, cat_map.get(sub_code, ""))

        norm_name = re.sub(r"\s+", "", name_zh)
        xlsx_names.add(norm_name)

        # Base values from xlsx
        edible = safe_float(vals[4], 100)
        energy_kcal = safe_float(vals[6])
        energy_kj = safe_float(vals[7])

        sodium_val = safe_float(vals[26])
        supplements_used = []

        # Supplement sodium from CFCT6 if xlsx is 0/null
        if not sodium_val or sodium_val == 0:
            # Try manual overrides first
            if name_zh in MANUAL_SODIUM:
                sodium_val = MANUAL_SODIUM[name_zh]
                supplements_used.append("manual:sodium")
            else:
                cfct6_match = cfct6_foods.get(norm_name)
                if cfct6_match:
                    fid = cfct6_match["food_id"]
                    if fid in cfct6_nutrients and "sodium" in cfct6_nutrients[fid]:
                        cfct6_na = cfct6_nutrients[fid]["sodium"]
                        if cfct6_na is not None and cfct6_na > 0:
                            sodium_val = cfct6_na
                            supplements_used.append("cfct6:sodium")

        # Supplement fiber, iodine, fatty acids from Juhe
        fiber_val = safe_float(vals[11])
        iodine_val = safe_float(vals[33])
        sfa = None
        mufa = None
        pufa = None

        juhe_match = juhe_supps.get(norm_name)
        if juhe_match:
            if (not fiber_val or fiber_val == 0) and juhe_match.get("dietary_fiber"):
                fiber_val = juhe_match["dietary_fiber"]
                supplements_used.append("juhe:fiber")
            if (not iodine_val or iodine_val == 0) and juhe_match.get("iodine"):
                iodine_val = juhe_match["iodine"]
                supplements_used.append("juhe:iodine")
            if juhe_match.get("sfa_percent"):
                sfa = juhe_match["sfa_percent"]
                mufa = juhe_match.get("mufa_percent")
                pufa = juhe_match.get("pufa_percent")
                supplements_used.append("juhe:fatty_acids")

        # Convert iodine from mg to μg if from xlsx (xlsx header says mg)
        if iodine_val and "juhe:iodine" not in supplements_used:
            iodine_val = iodine_val * 1000 if iodine_val < 1 else iodine_val

        food_id = "xlsx_{:04d}".format(seq)
        slug = slugify(name_zh)

        results.append({
            "food_id": food_id,
            "slug": slug,
            "name_zh": name_zh,
            "name_en": "",
            "category_code": cat_code,
            "category_zh": cat_name,
            "edible_percent": edible,
            "source_primary": "xlsx_cfct6_2018",
            "source_supplements": ";".join(supplements_used),
            "energy_kcal": energy_kcal,
            "energy_kj": energy_kj,
            "water_g": safe_float(vals[5]),
            "protein_g": safe_float(vals[8]),
            "fat_g": safe_float(vals[9]),
            "carbohydrate_g": safe_float(vals[10]),
            "dietary_fiber_g": fiber_val,
            "cholesterol_mg": safe_float(vals[12]),
            "ash_g": safe_float(vals[13]),
            "vitamin_a_ug_re": safe_float(vals[14]),
            "thiamin_mg": safe_float(vals[15]),
            "riboflavin_mg": safe_float(vals[16]),
            "niacin_mg": safe_float(vals[20]),
            "vitamin_c_mg": safe_float(vals[21]),
            "vitamin_e_mg": safe_float(vals[22]),
            "alpha_vitamin_e_mg": safe_float(vals[37]),
            "calcium_mg": safe_float(vals[23]),
            "phosphorus_mg": safe_float(vals[24]),
            "potassium_mg": safe_float(vals[25]),
            "sodium_mg": sodium_val,
            "magnesium_mg": safe_float(vals[27]),
            "iron_mg": safe_float(vals[28]),
            "zinc_mg": safe_float(vals[29]),
            "selenium_ug": safe_float(vals[30]),
            "copper_mg": safe_float(vals[31]),
            "manganese_mg": safe_float(vals[32]),
            "iodine_ug": iodine_val if iodine_val and iodine_val > 0 else None,
            "carotene_ug": safe_float(vals[34]),
            "retinol_ug": safe_float(vals[35]),
            "sfa_percent": sfa,
            "mufa_percent": mufa,
            "pufa_percent": pufa,
            "basis": "per_100g_edible_portion",
        })

    wb.close()

    # ── Step 5: Add CFCT6 foods not in xlsx ──────────────────────────────
    cfct6_added = 0
    for norm_name, cfct6_food in cfct6_foods.items():
        if norm_name in xlsx_names:
            continue

        fid = cfct6_food["food_id"]
        if fid not in cfct6_nutrients:
            continue
        n = cfct6_nutrients[fid]

        if not n.get("protein") and not n.get("energy_kcal"):
            continue

        results.append({
            "food_id": fid,
            "slug": slugify(cfct6_food["name_zh"]),
            "name_zh": cfct6_food["name_zh"],
            "name_en": "",
            "category_code": "",
            "category_zh": "",
            "edible_percent": cfct6_food["edible"] or 100,
            "source_primary": "cfct6",
            "source_supplements": "",
            "energy_kcal": n.get("energy_kcal"),
            "energy_kj": n.get("energy_kj"),
            "water_g": n.get("water"),
            "protein_g": n.get("protein"),
            "fat_g": n.get("fat"),
            "carbohydrate_g": n.get("carbohydrate"),
            "dietary_fiber_g": None,
            "cholesterol_mg": n.get("cholesterol"),
            "ash_g": n.get("ash"),
            "vitamin_a_ug_re": n.get("vitamin_a"),
            "thiamin_mg": n.get("thiamin"),
            "riboflavin_mg": n.get("riboflavin"),
            "niacin_mg": n.get("niacin"),
            "vitamin_c_mg": n.get("vitamin_c"),
            "vitamin_e_mg": n.get("vitamin_e_total"),
            "alpha_vitamin_e_mg": n.get("vitamin_e_alpha"),
            "calcium_mg": n.get("calcium"),
            "phosphorus_mg": n.get("phosphorus"),
            "potassium_mg": n.get("potassium"),
            "sodium_mg": n.get("sodium"),
            "magnesium_mg": n.get("magnesium"),
            "iron_mg": n.get("iron"),
            "zinc_mg": n.get("zinc"),
            "selenium_ug": n.get("selenium"),
            "copper_mg": n.get("copper"),
            "manganese_mg": n.get("manganese"),
            "iodine_ug": None,
            "carotene_ug": n.get("carotene"),
            "retinol_ug": n.get("retinol"),
            "sfa_percent": None,
            "mufa_percent": None,
            "pufa_percent": None,
            "basis": "per_100g_edible_portion",
        })
        cfct6_added += 1

    # ── Step 6: Add USDA Greek yogurt ────────────────────────────────────
    print("Loading USDA Greek yogurt...")
    try:
        greek = load_usda_greek_yogurt()
        if greek:
            results.append(greek)
            print("  Added: {}".format(greek["name_en"]))
        else:
            # Fallback with known USDA values
            results.append({
                "food_id": "usda_greek_yogurt",
                "slug": "greek_yogurt_plain_nonfat",
                "name_zh": "无糖希腊酸奶（脱脂）",
                "name_en": "Greek yogurt, plain, nonfat",
                "category_code": "10",
                "category_zh": "乳类及其制品",
                "edible_percent": 100,
                "source_primary": "usda_manual",
                "source_supplements": "",
                "energy_kcal": 59, "energy_kj": 247,
                "water_g": 81.3, "protein_g": 10.2, "fat_g": 0.7,
                "carbohydrate_g": 3.6, "dietary_fiber_g": 0,
                "cholesterol_mg": 5, "ash_g": 0.8,
                "vitamin_a_ug_re": 2, "thiamin_mg": 0.02,
                "riboflavin_mg": 0.27, "niacin_mg": 0.21,
                "vitamin_c_mg": 0, "vitamin_e_mg": 0, "alpha_vitamin_e_mg": 0,
                "calcium_mg": 100, "phosphorus_mg": 135, "potassium_mg": 141,
                "sodium_mg": 36, "magnesium_mg": 11,
                "iron_mg": 0.1, "zinc_mg": 0.5, "selenium_ug": 9.7,
                "copper_mg": 0.02, "manganese_mg": 0.01, "iodine_ug": None,
                "carotene_ug": 0, "retinol_ug": 2,
                "sfa_percent": None, "mufa_percent": None, "pufa_percent": None,
                "basis": "per_100g_edible_portion",
            })
            print("  Added Greek yogurt (fallback values)")
    except Exception as e:
        print("  USDA load failed: {}. Using fallback.".format(e))
        results.append({
            "food_id": "usda_greek_yogurt",
            "slug": "greek_yogurt_plain_nonfat",
            "name_zh": "无糖希腊酸奶（脱脂）",
            "name_en": "Greek yogurt, plain, nonfat",
            "category_code": "10", "category_zh": "乳类及其制品",
            "edible_percent": 100, "source_primary": "usda_manual",
            "source_supplements": "",
            "energy_kcal": 59, "energy_kj": 247,
            "water_g": 81.3, "protein_g": 10.2, "fat_g": 0.7,
            "carbohydrate_g": 3.6, "dietary_fiber_g": 0,
            "cholesterol_mg": 5, "ash_g": 0.8,
            "vitamin_a_ug_re": 2, "thiamin_mg": 0.02,
            "riboflavin_mg": 0.27, "niacin_mg": 0.21,
            "vitamin_c_mg": 0, "vitamin_e_mg": 0, "alpha_vitamin_e_mg": 0,
            "calcium_mg": 100, "phosphorus_mg": 135, "potassium_mg": 141,
            "sodium_mg": 36, "magnesium_mg": 11,
            "iron_mg": 0.1, "zinc_mg": 0.5, "selenium_ug": 9.7,
            "copper_mg": 0.02, "manganese_mg": 0.01, "iodine_ug": None,
            "carotene_ug": 0, "retinol_ug": 2,
            "sfa_percent": None, "mufa_percent": None, "pufa_percent": None,
            "basis": "per_100g_edible_portion",
        })

    # ── Step 7: Write output ─────────────────────────────────────────────
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    # Stats
    xlsx_count = sum(1 for r in results if r["source_primary"] == "xlsx_cfct6_2018")
    na_supplemented = sum(1 for r in results if "cfct6:sodium" in r.get("source_supplements", ""))
    fiber_supplemented = sum(1 for r in results if "juhe:fiber" in r.get("source_supplements", ""))
    fa_supplemented = sum(1 for r in results if "juhe:fatty_acids" in r.get("source_supplements", ""))

    print("\n=== INTEGRATION COMPLETE ===")
    print("Total foods: {}".format(len(results)))
    print("  From xlsx (primary): {}".format(xlsx_count))
    print("  From CFCT6 (added): {}".format(cfct6_added))
    print("  From USDA (added): 1")
    print("\nSupplementation stats:")
    print("  Sodium filled from CFCT6: {} foods".format(na_supplemented))
    print("  Fiber filled from Juhe: {} foods".format(fiber_supplemented))
    print("  Fatty acids from Juhe: {} foods".format(fa_supplemented))
    print("\nOutput: {}".format(OUTPUT_PATH))


if __name__ == "__main__":
    build_integrated_db()
