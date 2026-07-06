from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import models  # noqa: E402
from database import DATABASE_URL, SessionLocal  # noqa: E402


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_sha256_hex(value: str | None) -> bool:
    return bool(value and _SHA256_HEX.fullmatch(value))


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_database_url(raw: str) -> str:
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable database url>"


def session_factory_for_url(database_url: str) -> Callable:
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False}
        if database_url.startswith("sqlite")
        else {},
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def migrate_refresh_tokens(
    *,
    apply: bool = False,
    session_factory: Callable = SessionLocal,
    database_url: str = DATABASE_URL,
) -> dict[str, int | str]:
    db = session_factory()
    try:
        rows = db.query(models.RefreshToken).all()
        hashed_tokens = {
            row.token for row in rows
            if is_sha256_hex(row.token)
        }
        legacy_updates: list[tuple[models.RefreshToken, str]] = []
        conflicts: list[int] = []
        for row in rows:
            if not row.token or is_sha256_hex(row.token):
                continue
            hashed = hash_refresh_token(row.token)
            if hashed in hashed_tokens:
                conflicts.append(int(row.id))
                continue
            legacy_updates.append((row, hashed))

        result = {
            "database_url": safe_database_url(database_url),
            "total": len(rows),
            "already_hashed": len(hashed_tokens),
            "migrated": len(legacy_updates),
            "conflicts": len(conflicts),
        }
        if conflicts:
            db.rollback()
            result["committed"] = 0
            if apply:
                raise RuntimeError(
                    "aborting refresh-token migration; hashed-token conflicts "
                    f"for row ids: {', '.join(map(str, conflicts[:10]))}"
                )
            return result

        for row, hashed in legacy_updates:
            row.token = hashed

        if apply:
            db.commit()
            result["committed"] = 1
        else:
            db.rollback()
            result["committed"] = 0
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hash legacy plaintext refresh tokens. Dry-run by default; "
            "pass --apply to commit changes."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the migration. Without this flag, no database changes are saved.",
    )
    parser.add_argument(
        "--database-url",
        default=DATABASE_URL,
        help=(
            "Database URL to migrate. Defaults to DATABASE_URL from the environment "
            "or the app default."
        ),
    )
    args = parser.parse_args()

    factory = (
        SessionLocal
        if args.database_url == DATABASE_URL
        else session_factory_for_url(args.database_url)
    )
    result = migrate_refresh_tokens(
        apply=args.apply,
        session_factory=factory,
        database_url=args.database_url,
    )
    mode = "applied" if args.apply else "dry-run"
    print(
        f"{mode}: database={result['database_url']} "
        f"total={result['total']} "
        f"already_hashed={result['already_hashed']} "
        f"migrated={result['migrated']} "
        f"conflicts={result['conflicts']} "
        f"committed={result['committed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
