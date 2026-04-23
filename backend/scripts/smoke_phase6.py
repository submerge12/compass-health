"""
Phase 6 API-contract smoke.

Validates the backend responses match the shape the updated frontend expects:
- GET /api/fixed-meals  → { items: [...] }  consumed by _renderFixedMeals, _renderRequirements
- POST /api/fixed-meals → 201 with full row (cached macros)
- Fixed-meal row fields match _openFixedMealForm field names
- Procurement POST accepts {start_date} body (not {plan}) and returns the new shape with warnings

Exits non-zero on first failure. Depends on backend running at 127.0.0.1:8001.
"""
from __future__ import annotations

import json
import os
import sys
from urllib import request as urlreq
from urllib.error import HTTPError

# Let us import models/database to seed a recipe with macros directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://127.0.0.1:8001"


def _req(method: str, path: str, *, token: str | None = None, body=None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urlreq.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urlreq.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def _ok(label, cond, detail=""):
    icon = "PASS" if cond else "FAIL"
    print(f"  [{icon}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        sys.exit(1)


def main():
    print("Phase 6 API-contract smoke")

    # Register + login
    username = "phase6_smoke"
    pw = "testpass123"
    status, _ = _req("POST", "/api/auth/register", body={"username": username, "password": pw})
    _ok(f"register (or already exists) → {status}", status in (200, 201, 409))
    status, login = _req("POST", "/api/auth/login", body={"username": username, "password": pw})
    _ok(f"login → {status}", status == 200 and "access_token" in (login or {}))
    tok = login["access_token"]

    # Clean slate: wipe any fixed meals left over from a previous run
    status, resp = _req("GET", "/api/fixed-meals", token=tok)
    if status == 200:
        for item in resp.get("items", []):
            _req("DELETE", f"/api/fixed-meals/{item['id']}", token=tok)

    # 1) GET fixed-meals baseline
    status, resp = _req("GET", "/api/fixed-meals", token=tok)
    _ok(f"GET /api/fixed-meals → {status}", status == 200)
    _ok("response shape has 'items' list", isinstance(resp, dict) and isinstance(resp.get("items"), list))
    _ok("list empty after cleanup", resp["items"] == [])

    # Seed a recipe with macros directly — POST /api/recipes doesn't accept
    # macros (admin/LLM paths populate them); this keeps the smoke self-contained.
    import models
    from database import SessionLocal
    db = SessionLocal()
    try:
        r = models.Recipe(
            name="P6 test dish",
            meal_types="lunch",
            serving_g=400,
            calories=500,
            protein_g=30.0,
            carbs_g=60.0,
            fat_g=15.0,
            is_builtin=False,
            is_approved=True,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        rid = r.id
        print(f"  [seed] recipe id={rid} (calories=500, serving_g=400)")
    finally:
        db.close()

    # 2) POST fixed-meal (with recipe, half portion → half macros)
    status, fixed = _req(
        "POST",
        "/api/fixed-meals",
        token=tok,
        body={"meal_type": "lunch", "weekday": 1, "recipe_id": rid, "portion_g": 200, "custom_name": None},
    )
    _ok(f"POST /api/fixed-meals → {status}", status in (200, 201))
    for field in ("id", "meal_type", "weekday", "recipe_id", "portion_g", "custom_name",
                  "calories", "protein_g", "carbs_g", "fat_g"):
        _ok(f"row has field '{field}'", field in fixed)
    _ok("cached calories halved", fixed["calories"] == 250, detail=f"got {fixed['calories']}")
    _ok("cached protein halved", abs(fixed["protein_g"] - 15.0) < 0.01)

    fid = fixed["id"]

    # 3) GET list now has our row
    status, resp = _req("GET", "/api/fixed-meals", token=tok)
    _ok("GET lists our row", any(i["id"] == fid for i in resp["items"]))

    # 4) PATCH portion_g (half → quarter → calories should rescale to 125)
    status, patched = _req("PATCH", f"/api/fixed-meals/{fid}", token=tok, body={"portion_g": 100})
    _ok(f"PATCH portion_g=100 → {status}", status == 200)
    _ok("rescaled calories", patched["calories"] == 125, detail=f"got {patched['calories']}")

    # 5) Conflict check: cannot create dup (user, weekday=1, meal_type=lunch).
    # SQLite UNIQUE ignores NULLs, so we use an integer weekday here.
    status, err = _req(
        "POST",
        "/api/fixed-meals",
        token=tok,
        body={"meal_type": "lunch", "weekday": 1, "recipe_id": rid, "portion_g": 200},
    )
    _ok(f"duplicate rejected → {status}", status == 409)

    # 6) DELETE
    status, _ = _req("DELETE", f"/api/fixed-meals/{fid}", token=tok)
    _ok(f"DELETE → {status}", status in (200, 204))

    # 7) Procurement: accepts new body shape {start_date} (not legacy {plan}).
    # Test users without a closed-loop library get the short-circuit shape
    # {feasibility: "not_closed_loop", message_zh, message_en}; users with
    # a plan get {start_date, feasibility, groups, total_slugs,
    # total_planned_g, warnings}. The frontend handles both
    # (see meal_engine.js _renderProcurement).
    status, proc = _req(
        "POST",
        "/api/meal-engine/procurement",
        token=tok,
        body={"start_date": "2026-04-20"},
    )
    _ok(f"POST /procurement with {{start_date}} body → {status}", status == 200)
    _ok("response has 'feasibility'", "feasibility" in proc)
    if proc["feasibility"] == "not_closed_loop":
        _ok("short-circuit has bilingual message", "message_zh" in proc and "message_en" in proc)
        print("  [note] procurement short-circuited (no closed-loop library for test user)")
    else:
        for field in ("groups", "total_slugs", "total_planned_g", "warnings", "start_date"):
            _ok(f"full response has '{field}'", field in proc)

    print("ALL GOOD — Phase 6 API contracts match frontend expectations.")


if __name__ == "__main__":
    main()
