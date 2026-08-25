"""WO-HS-08 / M22: server-side audio normalization.

Browsers (MediaRecorder) produce WebM/Opus or MP4 regardless of the
filename the client claims. We no longer trust extensions: detect the real
container by magic bytes, transcode through an ffmpeg pipe to 16 kHz mono
PCM WAV, and hand clean audio to MiMo. Raw input is processed in memory and
never persisted.
"""
from __future__ import annotations

import asyncio
import shutil

# Magic-byte sniffing (container, not extension).
_SNIFFERS: list[tuple[str, bytes]] = [
    ("audio/webm", b"\x1a\x45\xdf\xa3"),          # EBML header (WebM/Matroska)
    ("audio/mp4", b"ftyp"),                        # ISO-BMFF (MP4/M4A) at offset 4
    ("audio/mpeg", b"ID3"),                        # MP3 with ID3 tag
    ("audio/wav", b"RIFF"),                        # WAV (RIFF header)
]

MAX_UPLOAD_BYTES = 7_500_000       # ~10MB base64 budget upstream
MAX_DURATION_SECONDS = 120         # refuse absurdly long recordings


def detect_mime(data: bytes) -> str | None:
    for mime, magic in _SNIFFERS:
        if data[: len(magic)] == magic:
            return mime
    if len(data) > 4 and data[4:8] == b"ftyp":
        return "audio/mp4"
    return None


class AudioNormalizeError(Exception):
    """ffmpeg missing, timed out, or input undecodable."""


async def normalize_to_wav16k(data: bytes) -> bytes:
    """Transcode any ffmpeg-readable audio to 16kHz mono PCM WAV bytes."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AudioNormalizeError("ffmpeg is not installed on the server")

    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-ar", "16000", "-ac", "1",
        "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=30)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise AudioNormalizeError("ffmpeg timed out") from exc

    if proc.returncode != 0 or not out:
        detail = err.decode("utf-8", errors="replace").strip()[:200]
        raise AudioNormalizeError(f"ffmpeg failed to decode audio: {detail}")
    return out
