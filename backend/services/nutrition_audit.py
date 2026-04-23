"""
Nutrition audit of the user's closed food library.

Answers four questions:
  1. Does the minimum closed loop exist?
  2. Are key micronutrient roles covered?
  3. Can realistic serving sizes actually meet each RDA? (sufficiency)
  4. Which foods are non-substitutable?
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models
from services import food_library as FL


# ── User library retrieval ───────────────────────────────────────────────────

def load_user_library(db: Session, user_id: int) -> list[str]:
    rows = (
        db.query(models.FoodPreference.item_key)
        .filter(models.FoodPreference.user_id == user_id)
        .all()
    )
    known = set(FL.FOOD_LIBRARY.keys())
    return sorted({r[0] for r in rows if r[0] in known})


# ── Classification helpers ───────────────────────────────────────────────────

def _classify_library(slugs: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {b: [] for b in FL.EXECUTION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["execution_buckets"]:
            grouped[bucket].append(slug)
    return grouped


def _validation_coverage(slugs: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {b: [] for b in FL.VALIDATION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["validation_buckets"]:
            grouped[bucket].append(slug)
    return grouped


# ── Micronutrient coverage ───────────────────────────────────────────────────

def _micronutrient_coverage(slugs: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for role, meta in FL.MICRONUTRIENT_ROLES.items():
        carriers: list[str] = []
        tiered: dict[str, list[str]] = {}
        for slug in slugs:
            entry = FL.FOOD_LIBRARY[slug]
            for declared in entry["micronutrient_roles"]:
                base = FL._strip_tier(declared)
                if base == role:
                    carriers.append(slug)
                    tiered.setdefault(declared, []).append(slug)
                    break
        ideal = meta.get("ideal_sources", 1)
        status = "missing" if not carriers else (
            "sufficient" if len(carriers) >= ideal else "thin"
        )
        result[role] = {
            "label_zh": meta["zh"],
            "label_en": meta["en"],
            "carriers": sorted(set(carriers)),
            "carriers_by_tier": {k: sorted(set(v)) for k, v in tiered.items()},
            "ideal_sources": ideal,
            "status": status,
        }
    return result


# ── Sufficiency check ────────────────────────────────────────────────────────
# A food is a "practical carrier" of a nutrient only if eating it at its
# max_practical_serving_g provides at least MIN_COVERAGE_PCT of the daily RDA.
MIN_COVERAGE_PCT = 10.0   # a single food needn't cover the whole RDA alone

# Maps nutrient role name → key in the food's `nutrients` dict.
_ROLE_TO_NUTRIENT_KEY: dict[str, str] = {
    "calcium":   "calcium_mg",
    "iron":      "iron_mg",
    "zinc":      "zinc_mg",
    "iodine":    "iodine_mcg",
    "selenium":  "selenium_mcg",
    "vitamin_a": "vitamin_a_mcg",
    "vitamin_d": "vitamin_d_mcg",
    "vitamin_e": "vitamin_e_mg",
    "vitamin_k": "vitamin_k_mcg",
    "b12":       "b12_mcg",
    "folate":    "folate_mcg",
    "omega3":    "omega3_g",
    "fiber":     "fiber_g",
}


def _practical_coverage_pct(slug: str, role: str, gender: str = "female") -> float:
    """Return how many % of the RDA this food covers at its max practical serving."""
    entry = FL.FOOD_LIBRARY.get(slug)
    if not entry:
        return 0.0
    meta = FL.MICRONUTRIENT_ROLES.get(role)
    if not meta:
        return 0.0
    nutrient_key = _ROLE_TO_NUTRIENT_KEY.get(role)
    if not nutrient_key:
        return 0.0

    amount_per_100g = entry.get("nutrients", {}).get(nutrient_key, 0.0)
    if amount_per_100g <= 0:
        return 0.0

    max_g = entry.get("max_practical_serving_g", 200.0)
    rda = meta.get(f"rda_{gender}", meta.get("rda_women", 1.0)) or 1.0

    daily_amount = amount_per_100g * max_g / 100.0
    return daily_amount / rda * 100.0


def _sufficiency_check(
    slugs: list[str],
    gender: str = "female",
) -> dict[str, dict]:
    """For each micronutrient, check whether its carriers can realistically
    cover MIN_COVERAGE_PCT of the RDA at normal serving sizes.

    Returns a dict keyed by role:
      {
        "label_zh", "label_en",
        "rda", "unit",
        "carriers": [
          {slug, max_serving_g, amount_at_max_g, coverage_pct, is_practical}
        ],
        "best_coverage_pct": float,
        "status": "ok" | "thin" | "impractical" | "missing",
        "message_zh", "message_en",
      }
    """
    result: dict[str, dict] = {}
    for role, meta in FL.MICRONUTRIENT_ROLES.items():
        rda = meta.get(f"rda_{gender}", meta.get("rda_women", 1.0)) or 1.0
        unit = meta.get("unit", "")
        nutrient_key = _ROLE_TO_NUTRIENT_KEY.get(role)

        carrier_details: list[dict] = []
        best_pct = 0.0

        for slug in slugs:
            entry = FL.FOOD_LIBRARY.get(slug)
            if not entry:
                continue
            # Must be declared as a carrier for this role
            declared_roles = {FL._strip_tier(r) for r in entry.get("micronutrient_roles", [])}
            if role not in declared_roles:
                continue

            amount_per_100g = entry.get("nutrients", {}).get(nutrient_key or "", 0.0)
            max_g = entry.get("max_practical_serving_g", 200.0)
            amount_at_max = round(amount_per_100g * max_g / 100.0, 2)
            pct = round(amount_at_max / rda * 100.0, 1)
            is_practical = pct >= MIN_COVERAGE_PCT

            carrier_details.append({
                "slug": slug,
                "name_zh": FL.display_name(slug, "zh"),
                "name_en": FL.display_name(slug, "en"),
                "max_serving_g": max_g,
                "amount_at_max_g": amount_at_max,
                "unit": unit,
                "coverage_pct": pct,
                "is_practical": is_practical,
            })
            best_pct = max(best_pct, pct)

        # Determine status
        if not carrier_details:
            status = "missing"
        elif best_pct < MIN_COVERAGE_PCT:
            status = "impractical"
        elif best_pct < 30.0:
            status = "thin"
        else:
            status = "ok"

        # Build human-readable message
        if status == "missing":
            msg_zh = f"当前食物库中无{meta['zh']}来源。"
            msg_en = f"No {meta['en']} source in the current library."
        elif status == "impractical":
            best = max(carrier_details, key=lambda c: c["coverage_pct"], default=None)
            best_name = best["name_zh"] if best else "—"
            best_pct_str = f"{best_pct:.0f}%"
            msg_zh = (
                f"当前{meta['zh']}载体食物的实际用量覆盖率最高仅为 {best_pct_str}（最佳：{best_name}），"
                "无法满足基本需求。建议添加更高效的来源。"
            )
            msg_en = (
                f"The best {meta['en']} carrier in this library covers only "
                f"{best_pct_str} of the RDA at max practical serving ({best_name}). "
                "Add a more concentrated source."
            )
        elif status == "thin":
            msg_zh = f"{meta['zh']}覆盖率偏低，建议提高食用频率或增加替代来源。"
            msg_en = f"{meta['en']} coverage is thin — increase frequency or add a second source."
        else:
            msg_zh = ""
            msg_en = ""

        result[role] = {
            "label_zh": meta["zh"],
            "label_en": meta["en"],
            "rda": rda,
            "unit": unit,
            "carriers": sorted(carrier_details, key=lambda c: -c["coverage_pct"]),
            "best_coverage_pct": round(best_pct, 1),
            "status": status,
            "message_zh": msg_zh,
            "message_en": msg_en,
        }
    return result


# ── Substitute derivation ────────────────────────────────────────────────────

def substitutes_for_in_library(slug: str, user_slugs: list[str]) -> list[dict]:
    """Return within-library substitutes for `slug` with swap notes."""
    target = FL.FOOD_LIBRARY.get(slug)
    if not target:
        return []
    target_roles = {FL._strip_tier(r) for r in target["micronutrient_roles"]}
    target_buckets = set(target["execution_buckets"])

    result: list[dict] = []
    for candidate in user_slugs:
        if candidate == slug:
            continue
        entry = FL.FOOD_LIBRARY.get(candidate)
        if not entry:
            continue
        if not target_buckets & set(entry["execution_buckets"]):
            continue
        cand_roles = {FL._strip_tier(r) for r in entry["micronutrient_roles"]}
        missing_roles = target_roles - cand_roles
        result.append({
            "slug": candidate,
            "name_zh": FL.display_name(candidate, "zh"),
            "name_en": FL.display_name(candidate, "en"),
            "covers_all_roles": not missing_roles,
            "missing_roles": sorted(missing_roles),
        })
    return sorted(result, key=lambda r: (not r["covers_all_roles"], r["slug"]))


# ── Non-substitutable flag ───────────────────────────────────────────────────

def _non_substitutable(
    validation: dict[str, list[str]],
    micronutrients: dict[str, dict],
) -> list[dict]:
    sole_reasons: dict[str, list[str]] = {}
    for bucket, carriers in validation.items():
        if len(carriers) == 1:
            sole_reasons.setdefault(carriers[0], []).append(f"bucket:{bucket}")
    for role, info in micronutrients.items():
        if len(info["carriers"]) == 1:
            sole_reasons.setdefault(info["carriers"][0], []).append(f"nutrient:{role}")
    return [
        {
            "slug": slug,
            "name_zh": FL.display_name(slug, "zh"),
            "name_en": FL.display_name(slug, "en"),
            "reasons": reasons,
        }
        for slug, reasons in sorted(sole_reasons.items())
    ]


# ── Feasibility verdict ──────────────────────────────────────────────────────

_BLOCKING_BUCKETS = {"staple", "lean_protein", "red_meat_shellfish", "calcium"}


def _feasibility(
    validation: dict[str, list[str]],
    micronutrients: dict[str, dict],
) -> dict:
    buckets_detail: dict[str, dict] = {}
    missing_blocking: list[str] = []
    missing_soft: list[str] = []

    for bucket in FL.VALIDATION_BUCKETS:
        carriers = validation.get(bucket, [])
        label = FL.VALIDATION_BUCKET_LABELS[bucket]
        buckets_detail[bucket] = {
            "label_zh": label["zh"],
            "label_en": label["en"],
            "carriers": carriers,
            "status": "ok" if carriers else "missing",
        }
        if not carriers:
            if bucket in _BLOCKING_BUCKETS:
                missing_blocking.append(bucket)
            else:
                missing_soft.append(bucket)

    missing_nutrients = [
        role for role, info in micronutrients.items()
        if info["status"] == "missing"
    ]

    if missing_blocking:
        overall = "not_closed_loop"
    elif missing_soft or missing_nutrients:
        overall = "feasible_with_gaps"
    else:
        overall = "feasible"

    return {
        "overall": overall,
        "buckets": buckets_detail,
        "missing_blocking_buckets": missing_blocking,
        "missing_soft_buckets": missing_soft,
        "missing_nutrients": missing_nutrients,
    }


# ── Actionable suggestions ───────────────────────────────────────────────────

def _suggestions(
    validation: dict[str, list[str]],
    micronutrients: dict[str, dict],
) -> list[dict]:
    out: list[dict] = []

    for bucket in FL.VALIDATION_BUCKETS:
        if validation.get(bucket):
            continue
        label = FL.VALIDATION_BUCKET_LABELS[bucket]
        candidates = FL.slugs_by_validation_bucket(bucket)[:6]
        out.append({
            "kind": "bucket",
            "ref": bucket,
            "label_zh": label["zh"],
            "label_en": label["en"],
            "resolution": "add_food",
            "candidates": [{"slug": c, "name_zh": FL.display_name(c, "zh"),
                            "name_en": FL.display_name(c, "en")} for c in candidates],
            "message_zh": (
                f"当前食物库缺少「{label['zh']}」类别。建议从下列食物中加入至少一种，"
                "否则系统无法为该类别安排稳定供应。"
            ),
            "message_en": (
                f"The library has no food in the '{label['en']}' category — "
                "add at least one carrier, or the planner cannot schedule this group."
            ),
        })

    for role, info in micronutrients.items():
        if info["status"] == "sufficient":
            continue
        candidates = FL.slugs_by_micronutrient(role)
        have = set(info["carriers"])
        missing_candidates = [c for c in candidates if c not in have][:6]
        resolution = "add_food" if info["status"] == "missing" else "frequency"
        out.append({
            "kind": "nutrient",
            "ref": role,
            "label_zh": info["label_zh"],
            "label_en": info["label_en"],
            "resolution": resolution,
            "candidates": [{"slug": c, "name_zh": FL.display_name(c, "zh"),
                            "name_en": FL.display_name(c, "en")} for c in missing_candidates],
            "message_zh": (
                f"「{info['label_zh']}」的载体食物偏少"
                + ("且当前库中没有任何稳定来源。" if resolution == "add_food"
                   else "——建议提高使用频率或增加替代来源。")
            ),
            "message_en": (
                f"'{info['label_en']}' has "
                + ("no stable carrier in the current library — add one below."
                   if resolution == "add_food"
                   else "thin coverage — raise its weekly frequency or add a second source.")
            ),
        })

    return out


# ── Public: full audit report ────────────────────────────────────────────────

def run_audit(db: Session, user: models.User) -> dict:
    gender = getattr(user.bmr_profile, "gender", "female") if user.bmr_profile else "female"
    slugs = load_user_library(db, user.id)
    classification = _classify_library(slugs)
    validation = _validation_coverage(slugs)
    micronutrients = _micronutrient_coverage(slugs)
    verdict = _feasibility(validation, micronutrients)
    non_subs = _non_substitutable(validation, micronutrients)
    fixes = _suggestions(validation, micronutrients)
    sufficiency = _sufficiency_check(slugs, gender)

    # Per-food substitute map (within library only)
    substitute_map = {
        slug: substitutes_for_in_library(slug, slugs)
        for slug in slugs
    }

    return {
        "slug_count": len(slugs),
        "library": slugs,
        "classification": {
            bucket: {
                "label_zh": FL.EXECUTION_BUCKET_LABELS[bucket]["zh"],
                "label_en": FL.EXECUTION_BUCKET_LABELS[bucket]["en"],
                "slugs": sorted(classification[bucket]),
            }
            for bucket in FL.EXECUTION_BUCKETS
        },
        "validation": verdict,
        "micronutrients": micronutrients,
        "sufficiency": sufficiency,
        "non_substitutable": non_subs,
        "suggestions": fixes,
        "substitutes": substitute_map,
    }


# ── Exchange matrix ──────────────────────────────────────────────────────────

def exchange_matrix(slugs: list[str]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {"carb": [], "protein": [], "fat": []}
    for slug in slugs:
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        macro = entry["primary_macro"]
        if macro not in grouped:
            continue
        grouped[macro].append({
            "slug": slug,
            "name_zh": entry["zh"],
            "name_en": entry["en"],
            "exchange_g": entry["exchange_g"],
            "kcal_per_100g": entry["kcal_per_100g"],
            "protein_per_100g": entry["protein_per_100g"],
            "carbs_per_100g": entry["carbs_per_100g"],
            "fat_per_100g": entry["fat_per_100g"],
            "execution_buckets": list(entry["execution_buckets"]),
            "micronutrient_roles": list(entry["micronutrient_roles"]),
            "notes": entry.get("notes"),
        })
    for rows in grouped.values():
        rows.sort(key=lambda r: r["exchange_g"])
    return grouped
