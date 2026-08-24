"""M09 / P6: voice routes — transcribe → preview intent → (confirm) commit.

POST /api/voice/transcribe       multipart audio → transcript + intent preview
POST /api/voice/transcribe:text  transcript only → intent preview (text fallback)
POST /api/voice/commit           confirmed record: routes to diet v2 / observations

Privacy (plan §15/M14): audio is processed in memory and never persisted by
default; logs carry ids and stage codes only, never audio or full transcripts.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_current_user
from models import User
from services.asr.mimo import AsrUnavailableError, MiMoTranscriber, default_language
from services.domain_identity import external_id_for_user
from services.health_domain_client import DomainUnavailableError, HealthDomainClient
from services.voice_intent import classify_intent

logger = logging.getLogger("compass.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])

_MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def _transcriber() -> MiMoTranscriber:
    return MiMoTranscriber()


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form(""),
    user: User = Depends(get_current_user),
) -> dict:
    suffix = "." + (audio.filename or "").rsplit(".", 1)[-1].lower()
    mime = _MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise HTTPException(status_code=400, detail="仅支持 wav / mp3 音频")

    data = await audio.read()
    if len(data) > 7_500_000:
        raise HTTPException(status_code=413, detail="音频过大（编码后上限约 10MB）")

    try:
        result = await _transcriber().transcribe(
            data, "audio/x-wav" if mime == "audio/wav" else mime,
            language or default_language(),
        )
    except AsrUnavailableError as exc:
        logger.warning("asr unavailable for user %s: %s", user.id, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "asr_unavailable", "message": "语音服务暂不可用，请改用文本输入"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    intent = classify_intent(result.text)
    return {
        "transcript": result.text,
        "intent": {
            "category": intent.category,
            "action": intent.action,
            "confidence": intent.confidence,
            "entities": intent.entities,
            "needs_confirmation": intent.needs_confirmation,
            "reply_hint_zh": intent.reply_hint_zh,
        },
        "provider_request_id": result.provider_request_id,
        # No audio retention: bytes die with this request.
        "audio_retained": False,
    }


@router.post("/transcribe:text")
async def transcribe_text(payload: "TextTranscriptInput", user: User = Depends(get_current_user)) -> dict:
    intent = classify_intent(payload.transcript)
    return {"transcript": payload.transcript, "intent": _intent_dict(intent)}


class TextTranscriptInput(BaseModel):
    transcript: str


def _intent_dict(intent) -> dict:
    return {
        "category": intent.category,
        "action": intent.action,
        "confidence": intent.confidence,
        "entities": intent.entities,
        "needs_confirmation": intent.needs_confirmation,
        "reply_hint_zh": intent.reply_hint_zh,
    }


class VoiceCommitInput(BaseModel):
    transcript: str
    idempotency_key: str = ""
    date: str = ""
    confirmed: bool = False


@router.post("/commit")
async def commit_voice_record(
    payload: VoiceCommitInput,
    user: User = Depends(get_current_user),
    client: HealthDomainClient = Depends(lambda: HealthDomainClient()),
) -> dict:
    """Commit a CONFIRMED record through the same domain commands as text/UI.

    Refuses to act on unknown intents and refuses plan modifications from this
    simplified path (those go through the interactive plan UI with diffs).
    """
    intent = classify_intent(payload.transcript)
    if intent.category == "unknown":
        raise HTTPException(status_code=422, detail="无法识别的意图，未执行任何写入")
    if intent.needs_confirmation and not payload.confirmed:
        return {"status": "needs_confirmation", "intent": _intent_dict(intent)}
    if intent.action == "log_meal" and intent.entities.get("food_description"):
        description = intent.entities["food_description"]
        downstream = await client.request(
            "POST",
            "/api/v1/diet/logs:commit",
            external_user_id=external_id_for_user(user.id),
            json_body={
                "date": payload.date,
                "mealType": _guess_meal_type(),
                "description": description,
                "idempotencyKey": payload.idempotency_key or f"voice:{uuid.uuid4().hex}",
                "source": "voice",
            },
        )
        body = downstream.json()
        if downstream.status_code >= 400 or body.get("error"):
            logger.info("voice meal commit rejected code=%s", body.get("error"))
            return {"status": "rejected", "domain_response": body}
        if body.get("status") == "needs_confirmation":
            # Domain refused an unresolved description (M05): surface candidates.
            return {"status": "needs_confirmation",
                    "needs_confirmation": body.get("needsConfirmation"),
                    "unmatched": body.get("unmatched")}
        log = body.get("log") or {}
        if not log.get("id"):
            return {"status": "rejected", "domain_response": body}
        return {"status": "committed", "log_id": log.get("id"), "kcal": log.get("caloriesKcal")}
    if intent.action == "report_pain":
        observed_on = payload.date
        downstream = await client.request(
            "POST",
            "/api/v1/observations",
            external_user_id=external_id_for_user(user.id),
            json_body={
                "observedOn": observed_on,
                "kind": "pain",
                "valueJson": {"bodyPart": intent.entities.get("body_part"), "transcript": payload.transcript},
            },
        )
        if downstream.status_code >= 400:
            return {"status": "rejected", "domain_response": downstream.json()}
        return {"status": "committed", "observation_event_id": downstream.json().get("eventId")}

    # Training sets / cardio / modifications need the richer session flow.
    return {
        "status": "unsupported_here",
        "hint": "该意图请使用对应页面：训练逐组记录或计划调整界面",
        "intent": _intent_dict(intent),
    }


def _guess_meal_type() -> str:
    from datetime import datetime

    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 15:
        return "lunch"
    if 15 <= hour < 18:
        return "snack"
    return "dinner"
