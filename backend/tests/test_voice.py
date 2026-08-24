"""M09 / P6 voice tests — intent classification and route contracts.

Provider is mocked via httpx.MockTransport; no real MiMo calls in tests.
Covers the J08 gates: query/record/modify/feedback routing, low-confidence
confirmation gate, unknown-intent refusal, audio format guards, and the
commit path reusing diet v2 idempotently.
"""
from __future__ import annotations

import httpx
import pytest

from services.voice_intent import classify_intent

from tests.conftest import register


# ── intent classification ──────────────────────────────────────────────────

def test_query_intent():
    intent = classify_intent("今天练什么")
    assert intent.category == "query"
    assert intent.action == "ask_today_training"
    assert not intent.needs_confirmation


def test_record_meal_with_food_entity():
    intent = classify_intent("我中午吃了一碗牛肉面")
    assert intent.category == "record"
    assert intent.action == "log_meal"
    assert "牛肉面" in intent.entities.get("food_description", "")
    assert not intent.needs_confirmation


def test_record_sets_parses_cn_numbers():
    intent = classify_intent("卧推做了三组每组八次")
    assert intent.category == "record"
    assert intent.action == "log_sets"
    assert intent.entities["sets"] == 3
    assert intent.entities["reps"] == 8


def test_hedged_record_requires_confirmation():
    intent = classify_intent("我大概吃了个汉堡")
    assert intent.category == "record"
    assert intent.needs_confirmation  # hedged phrasing must confirm before save


def test_pain_feedback_flags_confirmation_and_body_part():
    intent = classify_intent("今天膝盖疼")
    assert intent.category == "feedback"
    assert intent.action == "report_pain"
    assert intent.entities.get("body_part") == "膝盖"
    assert intent.needs_confirmation  # pain is sensitive; confirm before recording


def test_modify_always_needs_confirmation():
    for text in ("晚餐换成高蛋白", "器械被别人占了", "把那条记录删掉"):
        intent = classify_intent(text)
        assert intent.category == "modify", text
        assert intent.needs_confirmation, text


def test_unknown_intent_is_refusal_ready():
    intent = classify_intent("帮我订机票")
    assert intent.category == "unknown"
    assert intent.needs_confirmation


def test_empty_transcript():
    intent = classify_intent("  ")
    assert intent.category == "unknown"


# ── routes (provider mocked) ───────────────────────────────────────────────

@pytest.fixture()
def auth_client(client, clean_db):
    auth = register(client, "voice-user")
    return {"client": client, "token": auth["access_token"]}


def _mock_asr_transport(transcript: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "prov-1",
            "model": "mimo-v2.5-asr",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": transcript,
                                     "tool_calls": None, "audio": None,
                                     "audio_tokens": None}}],
            "created": 1787546406,
            "object": "chat.completion",
            "usage": {"seconds": 2},
        })

    return httpx.MockTransport(handler)


def test_transcribe_route_returns_transcript_and_intent(auth_client, monkeypatch):
    import routers.voice_routes as routes

    monkeypatch.setattr(routes, "_transcriber", lambda: MiMoStub("我今天卧推做了三组，每组八次"))

    res = auth_client["client"].post(
        "/api/voice/transcribe",
        headers={"Authorization": f"Bearer {auth_client['token']}"},
        files={"audio": ("test.wav", b"RIFF....", "audio/wav")},
        data={"language": "zh"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "卧推" in body["transcript"]
    assert body["intent"]["action"] == "log_sets"
    assert body["intent"]["entities"]["sets"] == 3
    assert body["audio_retained"] is False


class MiMoStub:
    """Same shape as MiMoTranscriber without network."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str):
        from services.asr.mimo import TranscriptionResult

        return TranscriptionResult(text=self._text, provider_request_id="stub", model="mimo-v2.5-asr")


def test_transcribe_rejects_bad_format(auth_client, monkeypatch):
    import routers.voice_routes as routes
    monkeypatch.setattr(routes, "_transcriber", lambda: MiMoStub("x"))
    res = auth_client["client"].post(
        "/api/voice/transcribe",
        headers={"Authorization": f"Bearer {auth_client['token']}"},
        files={"audio": ("test.ogg", b"data", "audio/ogg")},
    )
    assert res.status_code == 400


def test_text_fallback_route(auth_client):
    res = auth_client["client"].post(
        "/api/voice/transcribe:text",
        headers={"Authorization": f"Bearer {auth_client['token']}"},
        json={"transcript": "今天膝盖疼"},
    )
    assert res.status_code == 200
    assert res.json()["intent"]["category"] == "feedback"


def test_commit_refuses_unknown_intent(auth_client):
    res = auth_client["client"].post(
        "/api/voice/commit",
        headers={"Authorization": f"Bearer {auth_client['token']}"},
        json={"transcript": "帮我订机票", "confirmed": True},
    )
    assert res.status_code == 422


def test_commit_gates_on_confirmation_for_pain(auth_client):
    client = auth_client["client"]
    auth = {"access_token": auth_client["token"]}

    # Pain without confirmation → needs_confirmation, nothing sent downstream.
    res = client.post(
        "/api/voice/commit",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        json={"transcript": "今天膝盖疼", "date": "2026-08-24", "confirmed": False},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "needs_confirmation"
