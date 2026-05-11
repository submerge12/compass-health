"""
Food preference onboarding.

The user picks liked foods by category. For loose categories (leafy greens,
mushrooms), the user types free text; DeepSeek classifies that text into
canonical item slugs before persisting.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import deepseek, llm_quota

router = APIRouter(prefix="/api/preferences", tags=["preferences"])
app_log = logging.getLogger("compass.app")
llm_log = logging.getLogger("compass.llm")


# ── Canonical vocabulary ─────────────────────────────────────────────────────
# Item slugs grouped by category. The classifier is told to return slugs from
# this list (or propose new lowercase_snake slugs for vegetables/mushrooms).
CATEGORY_ITEMS: dict[str, list[str]] = {
    "grains":        ["rice", "brown_rice", "oats", "buckwheat", "quinoa",
                      "steamed_bun", "sweet_potato", "corn", "potato", "pumpkin"],
    "vegetables":    ["tomato", "cucumber", "broccoli", "cauliflower", "cabbage",
                      "spinach", "bok_choy", "kale", "amaranth", "mustard_greens",
                      "carrot", "shiitake", "shiitake_sun", "enoki", "wood_ear",
                      "kelp", "seaweed"],
    "fruits":        ["strawberry", "cherry_tomato", "pomelo",
                      "blueberry", "kiwi", "pineapple"],
    "meat_low_fat":  ["chicken_breast", "chicken_thigh_skinless",
                      "pork_tenderloin", "cod", "sea_bass", "tilapia",
                      "shrimp", "egg_white"],
    "meat_mid_fat":  ["whole_egg", "egg_yolk",
                      "beef_tenderloin", "lamb",
                      "chicken_liver",
                      "salmon", "hairtail", "mackerel", "sardine",
                      "oyster", "clam", "mussel", "scallop"],
    "soy":           ["tofu_firm", "tofu_soft", "dried_tofu", "soy_milk",
                      "natto", "edamame"],
    "dairy":         ["milk", "yogurt", "greek_yogurt"],
    "nuts":          ["nut_mix", "chia_seed", "sesame", "olive_oil", "cooking_oil"],
}
CATEGORIES = set(CATEGORY_ITEMS.keys())


# ── Request / response schemas ───────────────────────────────────────────────

class PreferenceItem(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    item_key: str = Field(..., min_length=1, max_length=80)


class CustomEntry(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)           # the category bucket to classify into (usually "vegetables")
    hint: Optional[str] = Field(default=None, max_length=80)   # optional sub-category hint: "leafy_greens", "mushrooms", ...
    text: str = Field(..., min_length=1, max_length=1000)               # user's free-form text


class PreferenceUpsert(BaseModel):
    items: list[PreferenceItem] = Field(default_factory=list, max_length=200)
    custom: list[CustomEntry] = Field(default_factory=list, max_length=20)
    replace: bool = False   # when true, wipe existing prefs before inserting


# ── Classifier ───────────────────────────────────────────────────────────────

def _refund_preference_quota(db: Session, user_id: int, call_log_id: Optional[int]) -> None:
    if call_log_id is None:
        return
    llm_quota.refund_call(
        db,
        call_log_id,
        user_id=user_id,
        kind=llm_quota.PREFERENCE_CLASSIFY,
    )


def classify_custom_text(entry: CustomEntry, db: Session, user_id: int) -> list[str]:
    """Map free-form user text to a list of canonical item slugs."""
    if entry.category not in CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category '{entry.category}'",
        )

    llm_log.info(
        "preference classification requested",
        extra={
            "event": "preference_classification_requested",
            "domain": "preferences",
            "category": entry.category,
            "hint": entry.hint or "",
            "text_chars": len(entry.text or ""),
        },
    )

    hint_line = f"Hint sub-category: {entry.hint}\n" if entry.hint else ""
    known = ", ".join(CATEGORY_ITEMS[entry.category])

    system_prompt = f"""
You are a food classifier.

Given a free-text list of foods (possibly in Chinese), return their canonical
slugs under the category "{entry.category}". A slug is lowercase ASCII with
underscores, e.g. "spinach", "bok_choy", "shiitake", "enoki".

Known slugs in this category: {known}

Reuse a known slug when it matches. If the user names a food not in the list,
propose a new slug in the same style. Discard anything that is not a food or
does not belong to this category.

Return ONLY valid JSON: {{"items": ["slug1", "slug2"]}}.
""".strip()

    user_prompt = f"{hint_line}Free text:\n{entry.text}"

    quota_call_id: Optional[int] = None
    try:
        quota_usage = llm_quota.check_and_consume(db, user_id, llm_quota.PREFERENCE_CLASSIFY)
    except llm_quota.LLMQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exhausted",
                "kind": llm_quota.PREFERENCE_CLASSIFY,
                "message_zh": "本周 AI 食材识别次数已用完，请先从列表中选择或稍后再试。",
                "message_en": "AI preference-classification quota is exhausted for this week.",
                "next_refresh_at": exc.next_refresh_at.isoformat()
                if getattr(exc, "next_refresh_at", None) else None,
            },
        )
    else:
        quota_call_id = quota_usage.get("call_log_id")

    try:
        client = deepseek.get_client()
        resp = client.chat.completions.create(
            model=deepseek.DEEPSEEK_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("Empty response from DeepSeek")
        data = json.loads(content)
        items = data.get("items", [])
        if not isinstance(items, list):
            raise ValueError("DeepSeek response 'items' is not a list")
        slugs = [str(x).strip().lower() for x in items if str(x).strip()]
        llm_log.info(
            "preference classification succeeded",
            extra={
                "event": "preference_classification_succeeded",
                "domain": "preferences",
                "category": entry.category,
                "hint": entry.hint or "",
                "classified_count": len(slugs),
            },
        )
        return slugs
    except json.JSONDecodeError:
        _refund_preference_quota(db, user_id, quota_call_id)
        llm_log.warning(
            "preference classification returned invalid json",
            extra={
                "event": "preference_classification_invalid_json",
                "domain": "preferences",
                "category": entry.category,
                "hint": entry.hint or "",
            },
        )
        raise HTTPException(status_code=502, detail="Preference classification returned invalid JSON")
    except Exception as e:
        _refund_preference_quota(db, user_id, quota_call_id)
        llm_log.exception(
            "preference classification failed",
            extra={
                "event": "preference_classification_failed",
                "domain": "preferences",
                "category": entry.category,
                "hint": entry.hint or "",
                "exc_class": e.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Preference classification failed",
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

def _grouped_preferences(db: Session, user_id: int) -> dict[str, list[str]]:
    rows = (
        db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == user_id)
        .all()
    )
    grouped: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for r in rows:
        allowed = CATEGORY_ITEMS.get(r.category)
        if allowed is None or r.item_key not in allowed:
            continue
        grouped.setdefault(r.category, []).append(r.item_key)
    return grouped


@router.get("/food")
def list_preferences(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return {
        "categories": _grouped_preferences(db, current_user.id),
        "known": CATEGORY_ITEMS,
    }


@router.post("/food")
def upsert_preferences(
    body: PreferenceUpsert,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if body.replace:
        db.query(models.FoodPreference).filter(
            models.FoodPreference.user_id == current_user.id
        ).delete()

    classified: dict[str, list[str]] = {}
    to_insert: list[tuple[str, str]] = []  # (category, item_key)

    for item in body.items:
        if item.category not in CATEGORIES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown category '{item.category}'",
            )
        key = item.item_key.strip().lower()
        if key not in CATEGORY_ITEMS[item.category]:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown item_key '{key}' for category '{item.category}'",
            )
        to_insert.append((item.category, key))

    for entry in body.custom:
        slugs = classify_custom_text(entry, db, current_user.id)
        classified[entry.text] = slugs
        for s in slugs:
            to_insert.append((entry.category, s))

    # Dedupe against what's already stored and within this request.
    existing = {
        (r.category, r.item_key)
        for r in db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == current_user.id)
        .all()
    }
    seen_in_req: set[tuple[str, str]] = set()
    for cat, key in to_insert:
        if not key:
            continue
        if (cat, key) in existing or (cat, key) in seen_in_req:
            continue
        seen_in_req.add((cat, key))
        db.add(models.FoodPreference(
            user_id=current_user.id,
            category=cat,
            item_key=key,
        ))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflict while saving preferences")

    grouped = _grouped_preferences(db, current_user.id)
    app_log.info(
        "food preferences saved",
        extra={
            "event": "preferences_saved",
            "domain": "preferences",
            "replace": body.replace,
            "selected_count": len(body.items),
            "custom_count": len(body.custom),
            "inserted_count": len(seen_in_req),
            "classified_entry_count": len(classified),
            "total_preference_count": sum(len(items) for items in grouped.values()),
        },
    )
    return {
        "categories": grouped,
        "known": CATEGORY_ITEMS,
        "classified": classified,
    }


@router.delete("/food")
def clear_preferences(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    deleted = (
        db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == current_user.id)
        .delete()
    )
    db.commit()
    app_log.info(
        "food preferences cleared",
        extra={
            "event": "preferences_cleared",
            "domain": "preferences",
            "deleted_count": deleted,
        },
    )
    return {"deleted": deleted}
