"""M09 / P6: voice routes — transcribe → preview intent → (confirm) commit.

POST /api/voice/transcribe       multipart audio → transcript + intent preview
POST /api/voice/transcribe:text  transcript only → intent preview (text fallback)
POST /api/voice/commit           confirmed record: routes to diet v2 / observations

Privacy (plan §15/M14): audio is processed in memory and never persisted by
default; logs carry ids and stage codes only, never audio or full transcripts.
"""
from __future__ import annotations

import logging
from typing import Optional
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_current_user
from models import User
from services.asr.audio_normalizer import (
    MAX_UPLOAD_BYTES,
    AudioNormalizeError,
    detect_mime,
    normalize_to_wav16k,
)
from services.asr.mimo import AsrUnavailableError, MiMoTranscriber, default_language
from services.domain_identity import external_id_for_user
from services.health_domain_client import DomainUnavailableError, HealthDomainClient
from datetime import datetime

from services.voice_dispatcher import DispatchError, dispatch
from services.voice_intent import VoiceIntent, classify_intent

logger = logging.getLogger("compass.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _transcriber() -> MiMoTranscriber:
    return MiMoTranscriber()


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form(""),
    user: User = Depends(get_current_user),
) -> dict:
    data = await audio.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="音频过大（编码后上限约 10MB）")

    # WO-HS-08: browsers lie about extensions (MediaRecorder -> webm named .wav).
    # Sniff the real container, then normalize to 16k mono WAV server-side.
    real_mime = detect_mime(data)
    if real_mime is None:
        raise HTTPException(status_code=400, detail="无法识别的音频格式（支持 webm/mp4/wav/mp3）")

    try:
        normalized = await normalize_to_wav16k(data)
        result = await _transcriber().transcribe(
            normalized, "audio/wav", language or default_language(),
        )
    except AudioNormalizeError as exc:
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
    chosen_items: Optional[list[dict]] = None  # confirmed food candidates


@router.post("/commit")
async def commit_voice_record(
    payload: VoiceCommitInput,
    user: User = Depends(get_current_user),
    client: HealthDomainClient = Depends(lambda: HealthDomainClient()),
) -> dict:
    """Execute one CONFIRMED voice intent through the canonical domain commands.

    Unknown intents refuse to write anything; plan modifications return a hint
    to use the interactive UI (diff confirmation lives there).
    """
    intent = classify_intent(payload.transcript)
    if intent.category == "unknown":
        raise HTTPException(status_code=422, detail="无法识别的意图，未执行任何写入")
    if intent.needs_confirmation and not payload.confirmed:
        return {"status": "needs_confirmation", "intent": _intent_dict(intent)}

    key = payload.idempotency_key or f"voice:{uuid.uuid4().hex}"
    date = payload.date or datetime.now().strftime("%Y-%m-%d")

    try:
        result = await dispatch(
            intent,
            user_id=user.id,
            token_actor="voice",
            date=date,
            idempotency_key=key,
            client=client,
            chosen_items=getattr(payload, "chosen_items", None),
        )
        logger.info("voice dispatch ok user=%s action=%s", user.id, intent.action)
        return result
    except DispatchError as exc:
        if exc.status >= 500:
            logger.warning("voice dispatch domain failure user=%s: %s", user.id, exc.code)
        raise HTTPException(
            status_code=exc.status,
            detail={"error": exc.code, "message": str(exc)},
        ) from exc


def _intent_dict(intent) -> dict:
    return {
        "category": intent.category,
        "action": intent.action,
        "confidence": intent.confidence,
        "entities": intent.entities,
        "needs_confirmation": intent.needs_confirmation,
        "reply_hint_zh": intent.reply_hint_zh,
    }


