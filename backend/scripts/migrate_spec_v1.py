"""Idempotent migration for spec-v1: slot-status + fixed meals + structured recipes.

Run from the `backend/` directory:

    python -m scripts.migrate_spec_v1              # operate on ./compass.db
    python -m scripts.migrate_spec_v1 --db PATH    # any SQLite file
    python -m scripts.migrate_spec_v1 --dry-run    # report only, no writes

Changes applied (each guarded by its own existence check, so running twice is
safe):

    1. meal_plan_entries.status          (TEXT NOT NULL DEFAULT 'recipe')
         Backfilled from recipe_id: recipe if recipe_id IS NOT NULL,
         otherwise generated.
    2. recipes.ingredients_json          (TEXT NULL)
         Backfilled from ingredient_slugs as
         `[{slug, grams: null, required: true}, ...]`.
    3. user_fixed_meals                  (new table, see models.py)

This script intentionally uses raw sqlite3 rather than SQLAlchemy so it can
run before the ORM metadata is loaded and so it never triggers
`create_all`'s side effects on a live DB.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Callable


# ── Output helpers ───────────────────────────────────────────────────────────

@dataclass
class Report:
    applied: list[str]
    skipped: list[str]
    notes:   list[str]

    def log(self) -> None:
        for line in self.applied:
            print(f"  [applied] {line}")
        for line in self.skipped:
            print(f"  [skipped] {line}")
        for line in self.notes:
            print(f"  [note   ] {line}")


# ── Introspection ────────────────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


# ── Individual steps ─────────────────────────────────────────────────────────

def _add_meal_plan_status(conn: sqlite3.Connection, report: Report, dry: bool) -> None:
    if not _table_exists(conn, "meal_plan_entries"):
        report.notes.append("meal_plan_entries table missing — first-run install")
        return
    if _column_exists(conn, "meal_plan_entries", "status"):
        report.skipped.append("meal_plan_entries.status already present")
        return
    if dry:
        report.applied.append("WOULD add meal_plan_entries.status")
        return
    conn.execute(
        "ALTER TABLE meal_plan_entries "
        "ADD COLUMN status TEXT NOT NULL DEFAULT 'recipe'"
    )
    updated = conn.execute(
        "UPDATE meal_plan_entries SET status = 'generated' WHERE recipe_id IS NULL"
    ).rowcount
    report.applied.append(
        f"added meal_plan_entries.status (backfilled {updated} custom_name rows → 'generated')"
    )


def _add_recipes_ingredients_json(conn: sqlite3.Connection, report: Report, dry: bool) -> None:
    if not _table_exists(conn, "recipes"):
        report.notes.append("recipes table missing — first-run install")
        return
    if _column_exists(conn, "recipes", "ingredients_json"):
        report.skipped.append("recipes.ingredients_json already present")
        return
    if dry:
        report.applied.append("WOULD add recipes.ingredients_json")
        return
    conn.execute("ALTER TABLE recipes ADD COLUMN ingredients_json TEXT")

    # Backfill from ingredient_slugs. Flat string array → structured array
    # with `required: true` (we have no data to say otherwise) and `grams:
    # null` (we don't know per-ingredient portions yet).
    rows = conn.execute(
        "SELECT id, ingredient_slugs FROM recipes WHERE ingredient_slugs IS NOT NULL"
    ).fetchall()
    written = 0
    malformed = 0
    for rid, raw in rows:
        try:
            slugs = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            malformed += 1
            continue
        if not isinstance(slugs, list):
            malformed += 1
            continue
        structured = [
            {"slug": s, "grams": None, "required": True}
            for s in slugs
            if isinstance(s, str) and s
        ]
        conn.execute(
            "UPDATE recipes SET ingredients_json = ? WHERE id = ?",
            (json.dumps(structured, ensure_ascii=False), rid),
        )
        written += 1
    report.applied.append(
        f"added recipes.ingredients_json (backfilled {written} rows; {malformed} malformed skipped)"
    )


def _create_user_fixed_meals(conn: sqlite3.Connection, report: Report, dry: bool) -> None:
    if _table_exists(conn, "user_fixed_meals"):
        report.skipped.append("user_fixed_meals already present")
        return
    if dry:
        report.applied.append("WOULD create user_fixed_meals")
        return
    conn.execute("""
        CREATE TABLE user_fixed_meals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            weekday     INTEGER,
            meal_type   TEXT NOT NULL,
            recipe_id   INTEGER,
            custom_name TEXT,
            portion_g   REAL,
            calories    INTEGER,
            protein_g   REAL,
            carbs_g     REAL,
            fat_g       REAL,
            created_at  DATETIME,
            updated_at  DATETIME,
            FOREIGN KEY (user_id)   REFERENCES users   (id),
            FOREIGN KEY (recipe_id) REFERENCES recipes (id)
        )
    """)
    conn.execute(
        "CREATE INDEX ix_user_fixed_meals_user_id ON user_fixed_meals (user_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX uq_user_fixed_meal "
        "ON user_fixed_meals (user_id, weekday, meal_type)"
    )
    report.applied.append("created user_fixed_meals (+ index on user_id, unique on user_id/weekday/meal_type)")


# ── Orchestration ────────────────────────────────────────────────────────────

STEPS: tuple[Callable[[sqlite3.Connection, Report, bool], None], ...] = (
    _add_meal_plan_status,
    _add_recipes_ingredients_json,
    _create_user_fixed_meals,
)


def migrate(db_path: str, dry_run: bool = False) -> Report:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")

    report = Report(applied=[], skipped=[], notes=[])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for step in STEPS:
            step(conn, report, dry_run)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def _resolve_default_db() -> str:
    # DATABASE_URL mirrors database.py: sqlite:///./compass.db by default.
    url = os.getenv("DATABASE_URL", "sqlite:///./compass.db")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    raise SystemExit(f"migrate_spec_v1 only supports SQLite; DATABASE_URL={url!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="path to SQLite file (default: ./compass.db)")
    parser.add_argument("--dry-run", action="store_true", help="report changes, don't write")
    args = parser.parse_args(argv)

    db_path = args.db or _resolve_default_db()
    print(f"Migrating {db_path} (dry_run={args.dry_run}):")
    report = migrate(db_path, dry_run=args.dry_run)
    report.log()

    if args.dry_run:
        print("Dry run complete — no changes committed.")
    else:
        print(f"Migration complete: {len(report.applied)} change(s) applied, {len(report.skipped)} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
