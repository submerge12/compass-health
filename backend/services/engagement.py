"""
Engagement helpers — check-in streak computation.

Single source of truth used by user_routes, stats_routes, and admin_routes.
All three used to carry their own 15-line copy of the streak algorithm;
this module is the canonical version.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import models


def calc_checkin_streak(db: Session, user_id: int) -> int:
    """Consecutive-day streak counting backward from today.

    If the user hasn't checked in *today*, start counting from yesterday so
    the existing streak isn't wiped to 0 before today's check-in lands.
    """
    dates = {
        d for (d,) in db.query(models.CheckIn.date)
        .filter(models.CheckIn.user_id == user_id)
        .all()
    }
    now = datetime.now(timezone.utc)
    cursor = now if now.strftime("%Y-%m-%d") in dates else now - timedelta(days=1)
    streak = 0
    while cursor.strftime("%Y-%m-%d") in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def is_checked_in_today(db: Session, user_id: int) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        db.query(models.CheckIn)
        .filter(models.CheckIn.user_id == user_id, models.CheckIn.date == today)
        .first()
        is not None
    )
