"""M00 / P0 e2e scaffold — service topology probes for the journey baseline.

These are not feature tests. They pin down the CURRENT deployment topology so
that P1 (M01 BFF / M15 startup) has an executable before/after:

1. FastAPI auth loop works in-process (J01 prerequisite on the UI path).
2. The Display API the browser calls directly (frontend/js/api.js AGENT_API_BASE,
   default http://127.0.0.1:8788) is NOT started by start.bat. When it is down
   we skip with BLOCKED_ENV per the M00 failure-handling rule — the skip reason
   itself is the recorded baseline finding (M15 gap).
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import pytest

from tests.conftest import register

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend" / "js" / "api.js"


def test_auth_loop_enables_ui_journeys(client, clean_db):
    auth = register(client, "journey-user")

    r = client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "journey-user"


def test_frontend_default_agent_mode_is_bff():
    """M01 acceptance: by default every browser health request goes through
    the authenticated BFF; direct connection is an opt-in dev fallback."""
    api_js = FRONTEND_DIR.read_text(encoding="utf-8")
    mode = re.search(r"AGENT_API_MODE\s*=.*['\"](\w+)['\"];", api_js)
    assert mode is not None, "AGENT_API_MODE not found in frontend/js/api.js"
    assert mode.group(1) == "bff"


def test_display_api_reachable_under_documented_startup():
    """start.bat does not start the Display API; probe it and record the gap.

    If this skips, the meal-engine pages' backend is down under the documented
    startup flow — the exact M15 finding the baseline must preserve.
    """
    url = "http://127.0.0.1:8788/api/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            assert response.status == 200
    except Exception:
        pytest.skip(
            "BLOCKED_ENV: Display API :8788 not running — start.bat starts only "
            "FastAPI :8000 and the static server :5500 (M15 gap; see "
            "docs/health-journeys/README.md)"
        )
