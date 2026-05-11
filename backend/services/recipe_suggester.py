"""
Recipe suggester — LLM layer that wraps the deterministic solver's
food + portion picks into named, cookable dishes.

This is the ONLY LLM touch-point in the meal-planning pipeline. The
deterministic solver (`services.menu_planner`) chooses which foods and
how many grams of each go into every slot; this module asks the LLM to
give that proposal a dish name, a cooking method, and (optionally)
small amounts of free seasonings.

Invariants enforced on the LLM's response:
  * Every ingredient slug must be in the user's closed library — dishes
    that leak outside the library are dropped.
  * Dish structure must be well-formed (name, non-empty ingredients,
    method steps); malformed candidates are dropped.
  * Macro drift from the slot target is *advisory*: each surviving
    candidate carries a `drift` block (`kcal_diff`, `*_diff_pct`,
    `off_target`) so the UI can badge it, but no candidate is dropped
    purely for missing the target.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from services import deepseek, food_library as FL

log = logging.getLogger("compass.app")


CANDIDATES_PER_SLOT = 3
POOL_NAME_BATCH_SIZE = 15

# Drift reporting — a candidate's macros are advisory only. Dishes that
# land outside these thresholds are still surfaced to the user, just
# tagged `off_target=True` so the UI can badge them.
OFF_TARGET_MACRO_PCT = 15.0
OFF_TARGET_KCAL = 75.0


# ── Nutrition math ──────────────────────────────────────────────────────────

def _compute_totals(ingredients: list[dict]) -> dict:
    """Sum macros from library slugs. Unknown slugs contribute zero."""
    kcal = protein = carbs = fat = 0.0
    for ing in ingredients:
        slug = ing.get("slug")
        grams = float(ing.get("grams") or 0)
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        factor = grams / 100.0
        kcal += entry["kcal_per_100g"] * factor
        protein += entry["protein_per_100g"] * factor
        carbs += entry["carbs_per_100g"] * factor
        fat += entry["fat_per_100g"] * factor
    return {
        "kcal": round(kcal, 1),
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
    }


def _compute_drift(computed: dict, slot: dict) -> dict:
    """Return per-macro deltas vs the slot target and an `off_target` flag.

    Deltas are always reported; the flag drives a UI badge when any macro
    exceeds `OFF_TARGET_MACRO_PCT` % or kcal exceeds `OFF_TARGET_KCAL`.
    """
    kcal_diff = round(computed["kcal"] - float(slot["target_kcal"] or 0), 1)

    def pct(got: float, tgt: float) -> float:
        if tgt <= 0:
            return 0.0
        return round((got - tgt) / tgt * 100.0, 1)

    protein_pct = pct(computed["protein_g"], float(slot["target_protein_g"] or 0))
    carbs_pct   = pct(computed["carbs_g"],   float(slot["target_carbs_g"]   or 0))
    fat_pct     = pct(computed["fat_g"],     float(slot["target_fat_g"]     or 0))

    off_target = (
        abs(kcal_diff) > OFF_TARGET_KCAL
        or abs(protein_pct) > OFF_TARGET_MACRO_PCT
        or abs(carbs_pct) > OFF_TARGET_MACRO_PCT
        or abs(fat_pct) > OFF_TARGET_MACRO_PCT
    )
    return {
        "kcal_diff": kcal_diff,
        "protein_diff_pct": protein_pct,
        "carbs_diff_pct": carbs_pct,
        "fat_diff_pct": fat_pct,
        "off_target": off_target,
    }


# ── Candidate validation ────────────────────────────────────────────────────

def _clean_candidate(
    cand: dict,
    slot: dict,
    library_slugs: set[str],
) -> Optional[dict]:
    """Return a normalised candidate if it passes all gates, else None."""
    if not isinstance(cand, dict):
        return None
    name = str(cand.get("name", "")).strip()
    if not name:
        return None

    raw_ings = cand.get("ingredients")
    if not isinstance(raw_ings, list) or not raw_ings:
        return None
    cleaned_ings: list[dict] = []
    for ing in raw_ings:
        if not isinstance(ing, dict):
            return None
        slug = ing.get("slug")
        if slug not in library_slugs:
            return None  # out-of-library ingredient — reject
        grams = float(ing.get("grams") or 0)
        if grams <= 0:
            return None
        cleaned_ings.append({"slug": slug, "grams": round(grams, 1)})

    totals = _compute_totals(cleaned_ings)
    drift = _compute_drift(totals, slot)

    # Method steps accepted as list or newline-separated text.
    raw_steps = cand.get("method_steps")
    if isinstance(raw_steps, list):
        steps_text = "\n".join(
            f"{i+1}. {str(s).strip()}"
            for i, s in enumerate(raw_steps)
            if str(s).strip()
        )
    else:
        steps_text = str(raw_steps or "").strip()
    if not steps_text:
        return None

    # Seasonings: free-form names + grams; not constrained to the library.
    seasonings = cand.get("seasonings") or []
    if not isinstance(seasonings, list):
        seasonings = []
    cleaned_seasonings = [
        {
            "name": str(s.get("name", "")).strip(),
            "grams": float(s.get("grams") or 0),
        }
        for s in seasonings
        if isinstance(s, dict) and str(s.get("name", "")).strip()
    ]

    return {
        "name": name,
        "ingredients": cleaned_ings,
        "seasonings": cleaned_seasonings,
        "method_steps": steps_text,
        "totals": totals,
        "drift": drift,
    }


def _reject_reason(cand, library_slugs: set[str]) -> str:
    """Short human-readable reason `_clean_candidate` dropped this candidate.
    Only runs when a rejection already happened — pure diagnostic helper."""
    if not isinstance(cand, dict):
        return f"not_a_dict({type(cand).__name__})"
    if not str(cand.get("name", "")).strip():
        return "empty_name"
    ings = cand.get("ingredients")
    if not isinstance(ings, list) or not ings:
        return "no_ingredients"
    for ing in ings:
        if not isinstance(ing, dict):
            return f"ingredient_not_dict({type(ing).__name__})"
        slug = ing.get("slug")
        if slug not in library_slugs:
            return f"slug_outside_library:{slug!r}"
        try:
            if float(ing.get("grams") or 0) <= 0:
                return f"zero_grams:{slug!r}"
        except (TypeError, ValueError):
            return f"bad_grams:{slug!r}:{ing.get('grams')!r}"
    steps = cand.get("method_steps")
    if isinstance(steps, list):
        if not any(str(s).strip() for s in steps):
            return "empty_method_steps_list"
    elif not str(steps or "").strip():
        return "empty_method_steps"
    return "unknown_reason"


# ── Prompt construction ─────────────────────────────────────────────────────

def _library_table(library_slugs: list[str]) -> str:
    rows = []
    for slug in sorted(library_slugs):
        e = FL.FOOD_LIBRARY.get(slug)
        if not e:
            continue
        rows.append(
            f"  {slug} | {e['zh']} ({e['en']}) | "
            f"{e['kcal_per_100g']:.0f} kcal/100g | "
            f"P{e['protein_per_100g']:.1f} C{e['carbs_per_100g']:.1f} F{e['fat_per_100g']:.1f}"
        )
    return "\n".join(rows)


def _slot_block(slot: dict) -> str:
    parts_lines = []
    for p in slot.get("parts", []):
        parts_lines.append(
            f"    - {p['slug']} ({p['name_zh']}) × {p['grams']} g → "
            f"{p['kcal']} kcal / P{p['protein_g']} C{p['carbs_g']} F{p['fat_g']}"
        )
    parts_block = "\n".join(parts_lines) if parts_lines else "    (empty)"
    return (
        f"  [{slot['slot_key']}] {slot['meal_type']}\n"
        f"    target: {slot['target_kcal']} kcal / "
        f"P{slot['target_protein_g']} C{slot['target_carbs_g']} F{slot['target_fat_g']}\n"
        f"    solver picks:\n{parts_block}"
    )


def _build_day_prompt(
    date_str: str,
    day_slots: list[dict],
    library_slugs: list[str],
    language: str,
    n: int,
) -> tuple[str, str]:
    lang_label = "Simplified Chinese (zh-CN)" if language != "en" else "English"

    system_prompt = f"""
You are a meal-planning chef specialising in healthy Chinese home-style cooking.

For each meal SLOT below, propose exactly {n} distinct dishes that could be
cooked from the SOLVER'S picked ingredients (shown under "solver picks").
You may:
  * use the exact slugs and grams from the solver's picks,
  * adjust any single ingredient's grams by up to ±15 %,
  * add or swap ingredients ONLY from the closed library listed below,
  * add small amounts of seasonings (e.g. soy sauce, salt, ginger, garlic,
    vinegar, cooking oil) — these do not need to come from the library.

You MUST NOT introduce ingredients outside the library as main ingredients.

Each dish must keep the slot's macro targets within ±10 % and kcal within ±50.

Write dish names and cooking steps in {lang_label}.

Return ONLY valid JSON in this exact shape (no prose, no markdown fences):
{{
  "slots": {{
    "<slot_key>": [
      {{
        "name": "菜名",
        "ingredients": [{{"slug": "<library_slug>", "grams": <number>}}, ...],
        "seasonings": [{{"name": "生抽", "grams": 5}}, ...],
        "method_steps": ["步骤1...", "步骤2...", "步骤3..."]
      }},
      ...
    ]
  }}
}}
""".strip()

    library_block = _library_table(library_slugs)
    slot_block = "\n".join(_slot_block(s) for s in day_slots)

    user_prompt = f"""
Date: {date_str}

Closed library (slug | name | kcal/100g | macros):
{library_block}

Slots for this day:
{slot_block}

Produce {n} candidates per slot.
""".strip()

    return system_prompt, user_prompt


# ── LLM roundtrip ───────────────────────────────────────────────────────────

def _call_llm_for_day(
    date_str: str,
    day_slots: list[dict],
    library_slugs: list[str],
    language: str,
    n: int,
) -> dict:
    system_prompt, user_prompt = _build_day_prompt(
        date_str, day_slots, library_slugs, language, n,
    )
    log.info(
        "recipe_suggester[%s] prompt: library_slugs=%d slots=%s",
        date_str, len(library_slugs), [s["slot_key"] for s in day_slots],
    )
    client = deepseek.get_client()
    resp = client.chat.completions.create(
        model=deepseek.DEEPSEEK_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=4000,
    )
    content = resp.choices[0].message.content or "{}"
    log.info("recipe_suggester[%s] raw response: %s", date_str, content[:2000])
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        log.warning("recipe_suggester[%s] JSON parse failed", date_str)
        return {"slots": {}}
    slots = data.get("slots")
    if not isinstance(slots, dict):
        log.warning(
            "recipe_suggester[%s] 'slots' missing or wrong shape; top-level keys=%s",
            date_str, list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )
        return {"slots": {}}
    log.info(
        "recipe_suggester[%s] returned slot_keys=%s (expected %s)",
        date_str, list(slots.keys()), [s["slot_key"] for s in day_slots],
    )
    return {"slots": slots}


# ── Revision pass ───────────────────────────────────────────────────────────

def _build_revision_prompt(
    date_str: str,
    slots_to_revise: list[dict],
    library_slugs: list[str],
    language: str,
    n: int,
) -> tuple[str, str]:
    lang_label = "Simplified Chinese (zh-CN)" if language != "en" else "English"

    system_prompt = f"""
You are a meal-planning chef REVISING dishes that missed their macro target.

For each slot below you will see the PREVIOUS candidates you produced, along
with how far each one drifted from the slot's target (kcal delta and per-macro
percentages). Produce exactly {n} REVISED candidates per slot that:
  * draw main ingredients only from the closed library listed below,
  * stay within ±10 % of each macro target and ±50 kcal of the kcal target,
  * correct the drift shown — if kcal was too high, reduce portions or swap
    for a lower-density food; if protein was too low, raise the protein-source
    grams or substitute a denser protein; likewise for carbs/fat,
  * remain plausible as a healthy home-cooked Chinese meal.

Seasonings (soy sauce, salt, ginger, garlic, vinegar, cooking oil) are free and
do not need to come from the library.

Write dish names and cooking steps in {lang_label}.

Return ONLY valid JSON in this exact shape (no prose, no markdown fences):
{{
  "slots": {{
    "<slot_key>": [
      {{
        "name": "菜名",
        "ingredients": [{{"slug": "<library_slug>", "grams": <number>}}, ...],
        "seasonings": [{{"name": "生抽", "grams": 5}}, ...],
        "method_steps": ["步骤1...", "步骤2...", "步骤3..."]
      }},
      ...
    ]
  }}
}}
""".strip()

    library_block = _library_table(library_slugs)

    slot_sections = []
    for entry in slots_to_revise:
        slot = entry["slot"]
        prev = entry["prev_candidates"]
        prev_lines = []
        for i, c in enumerate(prev, 1):
            ings_str = ", ".join(
                f"{ing['slug']} {ing['grams']}g" for ing in c["ingredients"]
            )
            t = c["totals"]
            d = c["drift"]
            prev_lines.append(
                f"    #{i} {c['name']}\n"
                f"       ingredients: {ings_str}\n"
                f"       got: {t['kcal']} kcal / P{t['protein_g']} C{t['carbs_g']} F{t['fat_g']}\n"
                f"       drift: {d['kcal_diff']:+.0f} kcal, "
                f"P{d['protein_diff_pct']:+.1f}%, "
                f"C{d['carbs_diff_pct']:+.1f}%, "
                f"F{d['fat_diff_pct']:+.1f}%"
            )
        prev_block = "\n".join(prev_lines) if prev_lines else "    (none)"

        slot_sections.append(
            f"  [{slot['slot_key']}] {slot['meal_type']}\n"
            f"    target: {slot['target_kcal']} kcal / "
            f"P{slot['target_protein_g']} C{slot['target_carbs_g']} F{slot['target_fat_g']}\n"
            f"    previous off-target candidates:\n{prev_block}"
        )

    user_prompt = f"""
Date: {date_str}

Closed library (slug | name | kcal/100g | macros):
{library_block}

Slots needing revision:
{chr(10).join(slot_sections)}

Produce {n} revised candidates per slot that stay within the macro targets.
""".strip()

    return system_prompt, user_prompt


def _call_llm_for_revision(
    date_str: str,
    slots_to_revise: list[dict],
    library_slugs: list[str],
    language: str,
    n: int,
) -> dict:
    system_prompt, user_prompt = _build_revision_prompt(
        date_str, slots_to_revise, library_slugs, language, n,
    )
    client = deepseek.get_client()
    resp = client.chat.completions.create(
        model=deepseek.DEEPSEEK_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=4000,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"slots": {}}
    slots = data.get("slots")
    if not isinstance(slots, dict):
        return {"slots": {}}
    return {"slots": slots}


# ── Public API ──────────────────────────────────────────────────────────────

def build_day_slots(
    day: dict,
    slot_filter: Optional[set[str]] = None,
) -> list[dict]:
    """Project a `solved_picks` day entry into the slot dicts the LLM prompt
    and validator both consume. Honours an optional slot-key allow-list."""
    date_str = day["date"]
    day_slots: list[dict] = []
    for meal_type, meal in day["meals"].items():
        slot_key = f"{date_str}/{meal_type}"
        if slot_filter is not None and slot_key not in slot_filter:
            continue
        day_slots.append({
            "slot_key": slot_key,
            "date": date_str,
            "meal_type": meal_type,
            "target_kcal": meal["target_kcal"],
            "target_protein_g": meal["target_protein_g"],
            "target_carbs_g": meal["target_carbs_g"],
            "target_fat_g": meal["target_fat_g"],
            "parts": meal.get("parts", []),
        })
    return day_slots


def suggest_for_day(
    date_str: str,
    day_slots: list[dict],
    library_slugs: list[str],
    language: str = "zh",
    candidates_per_slot: int = CANDIDATES_PER_SLOT,
) -> dict:
    """Generate validated candidates for the slots of a single day.

    Returns a dict shaped like:
      {
        "date": "<YYYY-MM-DD>",
        "candidates": {"<date>/<meal_type>": [...cleaned...], ...},
        "warnings": [...],
      }

    Never raises — LLM or validation failures are converted to warnings so
    callers can keep streaming other days' results.
    """
    library_set = set(library_slugs)
    candidates: dict[str, list[dict]] = {}
    warnings: list[str] = []

    if not day_slots:
        return {"date": date_str, "candidates": candidates, "warnings": warnings}

    try:
        day_resp = _call_llm_for_day(
            date_str, day_slots, library_slugs, language, candidates_per_slot,
        )
    except Exception as exc:  # LLM outage — skip the day, don't sink the week.
        warnings.append(f"{date_str}: LLM call failed ({exc.__class__.__name__})")
        for slot in day_slots:
            candidates[slot["slot_key"]] = []
        return {"date": date_str, "candidates": candidates, "warnings": warnings}

    slot_by_key: dict[str, dict] = {}
    for slot in day_slots:
        slot_by_key[slot["slot_key"]] = slot
        raw = day_resp["slots"].get(slot["slot_key"], [])
        if not isinstance(raw, list):
            raw = []
        valid: list[dict] = []
        reject_reasons: list[str] = []
        for cand in raw:
            cleaned = _clean_candidate(cand, slot, library_set)
            if cleaned:
                valid.append(cleaned)
            else:
                # Capture *why* this candidate failed — invaluable when all
                # 21 slots start reporting "no usable candidates".
                reject_reasons.append(_reject_reason(cand, library_set))
        candidates[slot["slot_key"]] = valid
        # Drift is advisory — only warn when the slot has nothing at all,
        # which is genuinely actionable. Off-target candidates are still
        # surfaced to the UI with a badge (see `drift.off_target`).
        if not valid:
            warnings.append(f"{slot['slot_key']}: LLM returned no usable candidates")
            log.warning(
                "recipe_suggester[%s] slot=%s raw_count=%d reject_reasons=%s",
                date_str, slot["slot_key"], len(raw), reject_reasons,
            )

    # Revision pass: any slot where every candidate missed the macro target
    # gets one more shot, this time prompted with the specific drift numbers
    # so the LLM can correct course. Single attempt — no recursion.
    slots_to_revise = [
        {"slot": slot_by_key[key], "prev_candidates": cands}
        for key, cands in candidates.items()
        if cands and all(c["drift"]["off_target"] for c in cands)
    ]
    if slots_to_revise:
        try:
            rev_resp = _call_llm_for_revision(
                date_str, slots_to_revise, library_slugs, language, candidates_per_slot,
            )
        except Exception as exc:
            warnings.append(f"{date_str}: revision pass failed ({exc.__class__.__name__})")
        else:
            for entry in slots_to_revise:
                slot = entry["slot"]
                raw = rev_resp["slots"].get(slot["slot_key"], [])
                if not isinstance(raw, list):
                    continue
                revised: list[dict] = []
                for cand in raw:
                    cleaned = _clean_candidate(cand, slot, library_set)
                    if cleaned:
                        revised.append(cleaned)
                # Only swap in revisions if at least one came back structurally
                # valid — otherwise keep the originals so the user still sees
                # something (badged off-target).
                if revised:
                    candidates[slot["slot_key"]] = revised

    for slot_key, cands in list(candidates.items()):
        on_target = [c for c in cands if not c["drift"]["off_target"]]
        if cands and not on_target:
            warnings.append(f"{slot_key}: all candidates missed macro target")
        candidates[slot_key] = on_target

    return {"date": date_str, "candidates": candidates, "warnings": warnings}


# ── Pool naming (dish-sketch → named dish) ──────────────────────────────────

def _build_pool_prompt(
    batch: list[dict],
    language: str,
) -> tuple[str, str]:
    lang_label = "Simplified Chinese (zh-CN)" if language != "en" else "English"
    system_prompt = f"""
You are a meal-planning chef specialising in healthy Chinese home-style cooking.

For each dish sketch below, assign a realistic dish name and step-by-step cooking method.
Each sketch lists the FIXED main ingredients with gram quantities — do not change them.
You may suggest small amounts of free seasonings (salt, soy sauce, ginger, garlic, cooking oil, etc.).

Write dish names and cooking steps in {lang_label}.

Return ONLY valid JSON (no markdown fences):
{{
  "dishes": {{
    "<sketch_id>": {{
      "name": "dish name",
      "seasonings": [{{"name": "...", "grams": <number>}}, ...],
      "method_steps": ["Step 1...", "Step 2...", "Step 3..."]
    }},
    ...
  }}
}}
""".strip()

    lines: list[str] = []
    for sketch in batch:
        sid = sketch["sketch_id"]
        meal = sketch["meal_type"]
        parts_str = ", ".join(
            f"{p.get('name_zh', p['slug'])} {p['grams']}g"
            for p in sketch.get("parts", [])
        )
        t = sketch.get("totals", {})
        lines.append(
            f"{sid} [{meal}]: {parts_str} "
            f"({t.get('kcal', '?')} kcal / "
            f"P{t.get('protein_g', '?')} "
            f"C{t.get('carbs_g', '?')} "
            f"F{t.get('fat_g', '?')})"
        )
    return system_prompt, "\n".join(lines)


def _call_llm_for_pool_batch(batch: list[dict], language: str) -> dict:
    system_prompt, user_prompt = _build_pool_prompt(batch, language)
    sketch_ids = [s["sketch_id"] for s in batch]
    log.info("recipe_suggester[pool] naming batch sketch_ids=%s", sketch_ids)
    client = deepseek.get_client()
    resp = client.chat.completions.create(
        model=deepseek.DEEPSEEK_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=4000,
    )
    content = resp.choices[0].message.content or "{}"
    log.info("recipe_suggester[pool] raw response: %s", content[:2000])
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        log.warning("recipe_suggester[pool] JSON parse failed")
        return {}
    dishes = data.get("dishes")
    if not isinstance(dishes, dict):
        log.warning(
            "recipe_suggester[pool] 'dishes' missing; keys=%s",
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )
        return {}
    return dishes


def suggest_pool_names(
    pool: list[dict],
    language: str = "zh",
    batch_size: int = POOL_NAME_BATCH_SIZE,
) -> dict:
    """Assign dish names and cooking methods to pool sketches via LLM.

    Accepts the combined pool list from generate_dish_pool()
    (breakfast_pool + main_pool concatenated). Returns:
      {
        "named_dishes": [
          {
            "sketch_id": str,
            "meal_type": "breakfast" | "main",
            "day_type_affinities": [...],
            "name": str,
            "ingredients": [{"slug": ..., "grams": ...}],
            "seasonings": [...],
            "method_steps": str,
            "totals": {...},
            "ingredient_slugs": [...],
          },
          ...
        ],
        "warnings": [str, ...]
      }
    """
    named_by_id: dict[str, dict] = {}
    warnings: list[str] = []

    for i in range(0, len(pool), batch_size):
        batch = pool[i : i + batch_size]
        try:
            dishes = _call_llm_for_pool_batch(batch, language)
        except Exception as exc:
            warnings.append(
                f"pool batch {i // batch_size}: LLM call failed ({exc.__class__.__name__})"
            )
            continue
        named_by_id.update({str(k): v for k, v in dishes.items()})

    named_dishes: list[dict] = []
    for sketch in pool:
        sid = str(sketch["sketch_id"])
        llm_data = named_by_id.get(sid)
        if not llm_data or not isinstance(llm_data, dict):
            warnings.append(f"sketch {sid}: LLM did not return a name")
            continue
        name = str(llm_data.get("name", "")).strip()
        if not name:
            warnings.append(f"sketch {sid}: empty name from LLM")
            continue
        raw_steps = llm_data.get("method_steps")
        if isinstance(raw_steps, list):
            steps_text = "\n".join(
                f"{j + 1}. {str(s).strip()}"
                for j, s in enumerate(raw_steps)
                if str(s).strip()
            )
        else:
            steps_text = str(raw_steps or "").strip()
        if not steps_text:
            warnings.append(f"sketch {sid}: empty method_steps from LLM")
            continue
        raw_seasonings = llm_data.get("seasonings") or []
        seasonings = [
            {"name": str(s.get("name", "")).strip(), "grams": float(s.get("grams") or 0)}
            for s in (raw_seasonings if isinstance(raw_seasonings, list) else [])
            if isinstance(s, dict) and str(s.get("name", "")).strip()
        ]
        ingredients = [
            {"slug": p["slug"], "grams": p["grams"]}
            for p in sketch.get("parts", [])
        ]
        named_dishes.append({
            "sketch_id": sid,
            "meal_type": sketch["meal_type"],
            "day_type_affinities": sketch.get("day_type_affinities", []),
            "name": name,
            "ingredients": ingredients,
            "seasonings": seasonings,
            "method_steps": steps_text,
            "totals": sketch.get("totals", {}),
            "ingredient_slugs": sketch.get("ingredient_slugs", []),
        })

    return {"named_dishes": named_dishes, "warnings": warnings}


def suggest_for_solved_picks(
    solved_picks: dict,
    library_slugs: list[str],
    language: str = "zh",
    candidates_per_slot: int = CANDIDATES_PER_SLOT,
    slot_filter: Optional[set[str]] = None,
) -> dict:
    """Synchronous whole-week variant. Kept for batch / test use; the
    streaming endpoint parallelises `suggest_for_day` across days instead."""
    candidates: dict[str, list[dict]] = {}
    warnings: list[str] = []

    for day in solved_picks.get("days", []):
        day_slots = build_day_slots(day, slot_filter=slot_filter)
        if not day_slots:
            continue
        day_result = suggest_for_day(
            day["date"], day_slots, library_slugs, language, candidates_per_slot,
        )
        candidates.update(day_result["candidates"])
        warnings.extend(day_result["warnings"])

    return {"candidates": candidates, "warnings": warnings}
