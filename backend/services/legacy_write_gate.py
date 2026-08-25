"""WO-HS-04 / M02, P0-8: legacy health write gate.

``HEALTH_LEGACY_WRITE_MODE`` controls the old FastAPI health write routes:

- ``enabled``: routes behave as before — opt-in escape hatch only;
- ``readonly``: writes return 410 with a machine-readable code;
- ``disabled`` (production default): same as readonly.

Reads are never blocked — the archive stays queryable (plan §七.3).
"""
from __future__ import annotations

import os

from fastapi import HTTPException, status


def legacy_write_mode() -> str:
    return os.environ.get("HEALTH_LEGACY_WRITE_MODE", "disabled").strip().lower()


def reject_legacy_write() -> None:
    """Call at the top of every legacy health write route."""
    if legacy_write_mode() in ("readonly", "disabled"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "legacy_health_write_disabled",
                "message": "健康记录已迁移到新数据源，请使用页面正常操作（数据会自动保存到新库）",
            },
        )
