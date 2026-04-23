"""Spec-v1 Phase 7 smoke — day-level greedy picker + slot assignment.

Exercises the three behaviors the user signed off on:
  1. Lex ordering (kcal > protein > carbs > fat) — no pantry gate.
  2. Quota hint (e.g. red_meat_day) prefers quota-satisfying recipes until
     one pick covers the quota.
  3. Slot assignment uses meal_types tags first, kcal tiebreaker for
     ambiguous picks (lightest → breakfast, heaviest → dinner).

Doesn't spin up the FastAPI app or hit a real DB — uses a minimal query
stub so we can isolate the scoring logic.
"""

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.planning_context import NutritionTarget
from services import recipe_matcher


# ── Stub DB: satisfy the matcher's `db.query(Recipe).filter(...).filter(...).all()` chain ──

class _StubQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **kw):
        return self

    def all(self):
        return list(self._rows)


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _StubQuery(self._rows)


def _recipe(rid, name, calories, protein, carbs, fat, slugs, meal_types=""):
    return SimpleNamespace(
        id=rid,
        name=name,
        calories=calories,
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
        is_approved=True,
        ingredients_json=json.dumps(
            [{"slug": s, "grams": 100, "required": True} for s in slugs]
        ),
        meal_types=meal_types,
    )


# ── Assertions ───────────────────────────────────────────────────────────────

results: list[tuple[str, bool, str]] = []


def check(label, cond, detail=""):
    results.append((label, bool(cond), detail))


# Test 1 — lex ordering: kcal delta dominates when other macros tie
target = NutritionTarget(calories=1800, protein=90, carbs=225, fat=60)
# Three single-meal candidates, identical protein/carb/fat, differing kcal:
# with k=1, per-pick target = 1800 kcal — closest kcal wins.
rA = _recipe(1, "A", calories=2200, protein=90, carbs=225, fat=60, slugs=["rice"])
rB = _recipe(2, "B", calories=1800, protein=90, carbs=225, fat=60, slugs=["rice"])  # exact
rC = _recipe(3, "C", calories=1400, protein=90, carbs=225, fat=60, slugs=["rice"])
db = _StubDB([rA, rB, rC])

picks = recipe_matcher.pick_day_set(db, target, k=1)
check(
    "lex: kcal-closest wins when other macros tie",
    len(picks) == 1 and picks[0].id == 2,
    f"got ids={[p.id for p in picks]}",
)

# Test 2 — lex ordering: kcal tied, protein breaks it
rD = _recipe(10, "D", calories=1800, protein=60, carbs=225, fat=60, slugs=["rice"])
rE = _recipe(11, "E", calories=1800, protein=90, carbs=225, fat=60, slugs=["rice"])  # exact
rF = _recipe(12, "F", calories=1800, protein=120, carbs=225, fat=60, slugs=["rice"])
db = _StubDB([rD, rE, rF])
picks = recipe_matcher.pick_day_set(db, target, k=1)
check(
    "lex: protein breaks kcal tie",
    len(picks) == 1 and picks[0].id == 11,
    f"got ids={[p.id for p in picks]}",
)

# Test 3 — k=3, remaining target is subtracted after each pick
# Three ~equal-third recipes — picker should select all three.
r1 = _recipe(21, "third-a", calories=600, protein=30, carbs=75, fat=20, slugs=["rice"])
r2 = _recipe(22, "third-b", calories=600, protein=30, carbs=75, fat=20, slugs=["rice"])
r3 = _recipe(23, "third-c", calories=600, protein=30, carbs=75, fat=20, slugs=["rice"])
db = _StubDB([r1, r2, r3])
picks = recipe_matcher.pick_day_set(db, target, k=3)
check(
    "k=3 across three equal candidates returns all three",
    len(picks) == 3 and {p.id for p in picks} == {21, 22, 23},
    f"got ids={[p.id for p in picks]}",
)

# Test 4 — quota hint: red_meat_day boosts a beef recipe over a kcal-closer fish recipe
# Use macros where the quota-hitting pick would lose on pure kcal.
rFish = _recipe(31, "fish-closer", calories=1800, protein=90, carbs=225, fat=60, slugs=["salmon"])
rBeef = _recipe(32, "beef-farther", calories=1400, protein=80, carbs=200, fat=55, slugs=["beef_tenderloin"])
db = _StubDB([rFish, rBeef])
picks = recipe_matcher.pick_day_set(db, target, k=1, quota_hint="red_meat")
check(
    "quota_hint=red_meat boosts beef over closer-fitting non-red-meat",
    len(picks) == 1 and picks[0].id == 32,
    f"got ids={[p.id for p in picks]}",
)

# Test 5 — once quota satisfied, subsequent picks drop the boost
# Slot 1 hits red_meat (beef); slot 2 should pick by macro fit alone.
rBeefBig = _recipe(41, "beef", calories=900, protein=45, carbs=110, fat=30, slugs=["beef_tenderloin"])
rChickenClose = _recipe(42, "chicken-close", calories=900, protein=45, carbs=115, fat=30, slugs=["chicken_breast"])
rBeefFar = _recipe(43, "beef-far", calories=300, protein=20, carbs=40, fat=10, slugs=["beef_tenderloin"])
db = _StubDB([rBeefBig, rChickenClose, rBeefFar])
picks = recipe_matcher.pick_day_set(db, target, k=2, quota_hint="red_meat")
check(
    "after quota hit, second pick goes by macro fit (not quota)",
    len(picks) == 2 and 41 in {p.id for p in picks} and 42 in {p.id for p in picks},
    f"got ids={[p.id for p in picks]}",
)

# Test 6 — excluded_recipe_ids actually excludes
db = _StubDB([rA, rB, rC])  # reuse from Test 1 where rB is exact
picks = recipe_matcher.pick_day_set(db, target, k=1, excluded_recipe_ids=[2])
check(
    "excluded_recipe_ids removes the exact-fit recipe",
    len(picks) == 1 and picks[0].id != 2,
    f"got ids={[p.id for p in picks]}",
)

# Test 7 — library smaller than k: return what we have
db = _StubDB([rA])
picks = recipe_matcher.pick_day_set(db, target, k=3)
check(
    "k=3 against single-recipe library returns 1 pick",
    len(picks) == 1,
    f"got ids={[p.id for p in picks]}",
)

# Test 8 — meal_type_filter keeps tagged recipes, drops untagged-for-the-slot-set
rBreakfastOnly = _recipe(51, "bf", calories=500, protein=25, carbs=70, fat=15,
                         slugs=["oats"], meal_types="breakfast")
rDinnerOnly    = _recipe(52, "dn", calories=700, protein=35, carbs=80, fat=22,
                         slugs=["pork"], meal_types="dinner")
rUntagged      = _recipe(53, "any", calories=600, protein=30, carbs=75, fat=20,
                         slugs=["rice"], meal_types="")
db = _StubDB([rBreakfastOnly, rDinnerOnly, rUntagged])
picks = recipe_matcher.pick_day_set(db, target, k=3, meal_type_filter=["breakfast", "lunch"])
# Dinner-only recipe must be filtered out; untagged kept (treated as usable).
picked_ids = {p.id for p in picks}
check(
    "meal_type_filter excludes dinner-only when filter=breakfast/lunch",
    52 not in picked_ids and 51 in picked_ids and 53 in picked_ids,
    f"got ids={sorted(picked_ids)}",
)

# Test 9 — assign_picks_to_slots: tag-first wins
bf_tag = _recipe(61, "bf-tag", calories=500, protein=25, carbs=70, fat=15,
                 slugs=["oats"], meal_types="breakfast")
lu_tag = _recipe(62, "lu-tag", calories=700, protein=35, carbs=90, fat=22,
                 slugs=["rice"], meal_types="lunch")
dn_tag = _recipe(63, "dn-tag", calories=900, protein=45, carbs=110, fat=28,
                 slugs=["pork"], meal_types="dinner")
assigned = recipe_matcher.assign_picks_to_slots(
    [dn_tag, bf_tag, lu_tag],  # deliberately out of canonical order
    ["breakfast", "lunch", "dinner"],
)
check(
    "assign: tag-first routes each recipe to its tagged slot",
    assigned.get("breakfast") is bf_tag
    and assigned.get("lunch") is lu_tag
    and assigned.get("dinner") is dn_tag,
    f"got {[(k, v.id) for k, v in assigned.items()]}",
)

# Test 10 — assign_picks_to_slots: kcal tiebreaker when untagged
u1 = _recipe(71, "u1", calories=400, protein=20, carbs=50, fat=12, slugs=["a"])
u2 = _recipe(72, "u2", calories=700, protein=35, carbs=90, fat=22, slugs=["b"])
u3 = _recipe(73, "u3", calories=1000, protein=50, carbs=120, fat=32, slugs=["c"])
assigned = recipe_matcher.assign_picks_to_slots(
    [u2, u3, u1],
    ["breakfast", "lunch", "dinner"],
)
check(
    "assign: untagged → lightest=breakfast, heaviest=dinner, median=lunch",
    assigned.get("breakfast") is u1
    and assigned.get("lunch") is u2
    and assigned.get("dinner") is u3,
    f"got {[(k, v.id) for k, v in assigned.items()]}",
)

# Test 11 — assign_picks_to_slots: mixed tag + untagged, dinner-tagged claims dinner
mixed_untagged = _recipe(81, "mu", calories=400, protein=20, carbs=50, fat=12, slugs=["a"])
mixed_dinner   = _recipe(82, "md", calories=600, protein=30, carbs=75, fat=20,
                         slugs=["b"], meal_types="dinner")
assigned = recipe_matcher.assign_picks_to_slots(
    [mixed_untagged, mixed_dinner],
    ["breakfast", "dinner"],
)
check(
    "assign: dinner-tagged claims dinner, untagged falls to breakfast",
    assigned.get("breakfast") is mixed_untagged and assigned.get("dinner") is mixed_dinner,
    f"got {[(k, v.id) for k, v in assigned.items()]}",
)


# ── Report ───────────────────────────────────────────────────────────────────

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
width = max(len(label) for label, *_ in results)
for label, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"  [{mark}] {label.ljust(width)}{suffix}")
print(f"\n{passed}/{total} checks passed")
sys.exit(0 if passed == total else 1)
