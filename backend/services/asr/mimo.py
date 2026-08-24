"""M09 / P6: Xiaomi MiMo ASR provider adapter.

OpenAI-compatible chat-completions contract (verified live):
POST {base_url}/chat/completions with model mimo-v2.5-asr, base64 audio
(data URL), optional language hint. The API key lives server-side only —
the browser never sees it (plan §15.1). Audio is transcribed in-memory and
NOT persisted by default (ASR_RAW_AUDIO_RETENTION_HOURS=0).
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx


class AsrUnavailableError(Exception):
    """Provider unreachable / timeout / non-200."""


@dataclass
class TranscriptionResult:
    text: str
    provider_request_id: Optional[str] = None
    model: Optional[str] = None
    audio_seconds: Optional[float] = None
    raw_content: str = ""


class VoiceTranscriber(Protocol):
    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str) -> TranscriptionResult: ...


class MiMoTranscriber:
    """Default production transcriber; swap via config, never via browser input."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("MIMO_API_KEY", "")
        self._base_url = (base_url or os.environ.get("MIMO_BASE_URL") or "https://api.xiaomimimo.com/v1").rstrip("/")
        self._model = model or os.environ.get("MIMO_ASR_MODEL") or "mimo-v2.5-asr"
        self._timeout = timeout_seconds
        self._transport = transport

    async def transcribe(self, audio_bytes: bytes, mime_type: str, language: str) -> TranscriptionResult:
        if not self._api_key:
            raise AsrUnavailableError("MIMO_API_KEY is not configured")
        if len(audio_bytes) > 7_500_000:
            raise ValueError("audio too large for base64 transport (limit ~10MB encoded)")
        # Only wav/mp3 accepted upstream; ffmpeg on the client normalizes.
        if mime_type not in ("audio/wav", "audio/mpeg", "audio/mp3"):
            # Normalize common aliases instead of failing (provider is strict).
            mime_type = {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav",
                         "audio/mp3": "audio/mpeg"}.get(mime_type)
            if mime_type not in ("audio/wav", "audio/mpeg"):
                raise ValueError("unsupported audio format: expected wav or mp3")

        encoded = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": f"data:{mime_type};base64,{encoded}"},
                }],
            }],
            "extra_body": {"asr_options": {"language": language}},
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    content=json.dumps(payload).encode(),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise AsrUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            detail = response.text[:200]
            raise AsrUnavailableError(f"provider returned {response.status_code}: {detail}")

        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AsrUnavailableError("unparseable provider response") from exc

        usage = body.get("usage") or {}
        return TranscriptionResult(
            text=text.strip(),
            provider_request_id=body.get("id"),
            model=body.get("model"),
            audio_seconds=usage.get("seconds"),
            raw_content=text,
        )


def default_language() -> str:
    return os.environ.get("MIMO_ASR_LANGUAGE", "auto")
