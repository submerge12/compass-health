"""
Admin audit trail.

`record()` stages an AdminAuditLog row on the provided session and emits a
structured `compass.audit` log line. The caller is expected to `db.commit()`
in the same transaction as the action being audited, so the DB row and the
mutation can never diverge.

The `compass.audit` logger is configured (in logging_config.py) with a
separate 90-day rotating file — longer retention than the general app log —
so a paper trail exists even if the DB is wiped.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

import models
from logging_config import request_id_var

_log = logging.getLogger("compass.audit")


def record(
    db: Session,
    actor: models.User,
    action: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Stage an audit row + emit a log line. Does NOT commit."""
    request_id = request_id_var.get()
    details_json: Optional[str] = None
    if details is not None:
        try:
            details_json = json.dumps(details, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            details_json = json.dumps({"_unserialisable": repr(details)})

    row = models.AdminAuditLog(
        actor_user_id=actor.id,
        actor_username=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details_json,
        request_id=request_id,
    )
    db.add(row)

    _log.info(
        "admin action",
        extra={
            "event": "admin_action",
            "action": action,
            "actor_user_id": actor.id,
            "actor_username": actor.username,
            "target_type": target_type,
            "target_id": target_id,
            # Keep the log line compact — full diff lives in the DB row.
            "details_keys": sorted(details.keys()) if isinstance(details, dict) else None,
        },
    )
