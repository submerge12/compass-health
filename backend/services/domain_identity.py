"""M01: stable mapping from a FastAPI (SQLite) user to the health domain's
external user id used by the PostgreSQL Display API.

The mapping must be derived from the immutable numeric user id, never from the
mutable username, so that renames cannot detach a user from their health
history (plan §18.1 step 3).
"""
from __future__ import annotations


def external_id_for_user(user_id: int) -> str:
    return f"compass-health:{user_id}"
