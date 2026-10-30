"""Bounded recorded dictation through the official Meta speech-to-text endpoint."""

import asyncio
import io
import json
import logging
import struct
import wave
from uuid import uuid4

import httpx

from app.model_catalog import VOICE_MODEL
from app.model_client import DEFAULT_BASE_URL, ModelClientError, ModelSettings

LOGGER = logging.getLogger("museautolab.transcription")
MAX_DURATION_SECONDS = 60
MAX_AUDIO_BYTES = MAX_DURATION_SECONDS * 24000 * 2 + 65536
TRANSCRIPTION_TIMEOUT_SECONDS = 45
_active_requests = 0


class TranscriptionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def validate_audio(content: bytes) -> tuple[bytes, int]:
    """Validate the complete RIFF structure and remove all non-audio metadata."""
    if len(content) > MAX_AUDIO_BYTES:
        raise TranscriptionError(413, "Record at most 60 seconds of audio.")
    invalid = "Use a mono, 16-bit PCM WAV recording at 16 or 24 kHz."
    if (
        len(content) < 44
        or content[:4] != b"RIFF"
        or content[8:12] != b"WAVE"
        or struct.unpack_from("<I", content, 4)[0] + 8 != len(content)
    ):
        raise TranscriptionError(422, invalid)
    offset, fmt, pcm = 12, None, None
    while offset < len(content):
        if offset + 8 > len(content):
            raise TranscriptionError(422, "The WAV recording is truncated.")
        kind = content[offset : offset + 4]
        size = struct.unpack_from("<I", content, offset + 4)[0]
        start, end = offset + 8, offset + 8 + size
        if end + size % 2 > len(content):
            raise TranscriptionError(422, "The WAV recording is truncated.")
        if kind == b"fmt ":
            if fmt is not None or size not in (16, 18):
                raise TranscriptionError(422, invalid)
            fmt = struct.unpack_from("<HHIIHH", content, start)
            if size == 18 and content[start + 16 : end] != b"\0\0":
                raise TranscriptionError(422, invalid)
        elif kind == b"data":
            if pcm is not None:
                raise TranscriptionError(422, "Use a WAV file with one audio data segment.")
            pcm = content[start:end]
        offset = end + size % 2
    if fmt is None or pcm is None or not pcm or len(pcm) % 2:
        raise TranscriptionError(422, invalid)
    encoding, channels, rate, byte_rate, block_align, bits = fmt
    if (
        encoding != 1
        or channels != 1
        or rate not in (16000, 24000)
        or bits != 16
        or block_align != 2
        or byte_rate != rate * 2
    ):
        raise TranscriptionError(422, invalid)
    frames = len(pcm) // 2
    if frames > rate * MAX_DURATION_SECONDS:
        raise TranscriptionError(413, "Record at most 60 seconds of audio.")
    sanitized = io.BytesIO()
    with wave.open(sanitized, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    return sanitized.getvalue(), round(frames * 1000 / rate)


async def transcribe_audio(
    content: bytes,
    *,
    settings: ModelSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Send one request, without retries, project writes, audio files or text logging."""
    global _active_requests
    audio, duration_ms = validate_audio(content)
    try:
        settings = settings or ModelSettings.load()
    except ModelClientError:
        raise TranscriptionError(503, "Configure MODEL_API_KEY on the server to use dictation.")
    if settings.base_url != DEFAULT_BASE_URL:
        raise TranscriptionError(503, "Voice requires the official Meta Model API endpoint.")
    if _active_requests >= 2:
        raise TranscriptionError(
            429, "Dictation is busy. Try again when the current clip finishes."
        )
    _active_requests += 1
    request_id = f"dictation-{uuid4().hex}"
    try:

        async def send(active: httpx.AsyncClient) -> dict:
            files = {
                "request": (
                    None,
                    json.dumps(
                        {"model": VOICE_MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
                    ),
                    "application/json",
                ),
                "audio": ("recording.wav", audio, "audio/wav"),
            }
            async with active.stream(
                "POST",
                f"{DEFAULT_BASE_URL}/asr/transcribe",
                params={"sessionId": request_id},
                headers={
                    "Authorization": f"Bearer {settings.api_key}",
                    "Accept": "application/json",
                },
                files=files,
                timeout=httpx.Timeout(40, connect=10),
            ) as response:
                response.raise_for_status()
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 65536:
                        raise TranscriptionError(502, "The transcription response was too large.")
                return json.loads(payload)

        async with asyncio.timeout(TRANSCRIPTION_TIMEOUT_SECONDS):
            if client is None:
                async with httpx.AsyncClient(follow_redirects=False) as active:
                    body = await send(active)
            else:
                body = await send(client)
        if not isinstance(body, dict) or not isinstance(body.get("transcript"), str):
            raise ValueError("Invalid transcription")
        text = body["transcript"].strip()
        if len(text) > 12000:
            raise ValueError("Invalid transcription")
        LOGGER.info(
            "Dictation model=%s duration_ms=%s request_id=%s", VOICE_MODEL, duration_ms, request_id
        )
        return {
            "text": text,
            "model": VOICE_MODEL,
            "duration_ms": duration_ms,
            "request_id": request_id,
        }
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403, 404):
            raise TranscriptionError(
                503, "Muse Voice is unavailable for the configured API account."
            )
        if code == 429:
            raise TranscriptionError(429, "Meta's dictation limit was reached. Try again later.")
        raise TranscriptionError(
            502, f"Meta transcription failed (HTTP {code}). Your draft is intact."
        )
    except (httpx.TimeoutException, TimeoutError):
        raise TranscriptionError(504, "Transcription timed out. Your draft is intact; try again.")
    except httpx.RequestError:
        raise TranscriptionError(502, "Could not reach Meta transcription. Check the connection.")
    except (ValueError, TypeError):
        raise TranscriptionError(
            502, "Meta returned an invalid transcription. Your draft is intact."
        )
    finally:
        _active_requests -= 1
