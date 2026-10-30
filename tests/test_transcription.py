"""Strict local audio bounds and single-request, sanitized Meta dictation."""

import asyncio
import io
import struct
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api as api
import app.transcription as voice
from app.model_client import ModelSettings

SETTINGS = ModelSettings("synthetic-test-key", "https://api.meta.ai/v1", "muse-wonder-1.0")


def wav(*, rate=16000, channels=1, width=2, seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        writer.writeframes(b"\0" * (int(rate * seconds) * channels * width))
    return output.getvalue()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"https://example.test/audio.wav",
        b"not audio",
        wav(rate=44100),
        wav(channels=2),
        wav(width=1),
        wav()[:-2],
    ],
    ids=["empty", "url", "text", "sample-rate", "stereo", "bit-depth", "truncated"],
)
def test_invalid_audio_never_reaches_provider(content):
    with pytest.raises(voice.TranscriptionError) as caught:
        voice.validate_audio(content)
    assert caught.value.status_code == 422


def test_duration_bytes_and_container_consistency():
    voice.validate_audio(wav(rate=24000, seconds=60))
    for content in (wav(seconds=60.01), b"x" * (voice.MAX_AUDIO_BYTES + 1)):
        with pytest.raises(voice.TranscriptionError) as caught:
            voice.validate_audio(content)
        assert caught.value.status_code == 413
    with pytest.raises(voice.TranscriptionError):
        voice.validate_audio(wav() + b"hidden trailing data")


def test_extra_metadata_is_removed():
    original = wav()
    extra = b"LIST" + struct.pack("<I", 10) + b"private123"
    modified = original[:4] + struct.pack("<I", len(original) + len(extra) - 8)
    modified += original[8:] + extra
    clean, duration = voice.validate_audio(modified)
    assert clean == original
    assert duration == 100
    assert b"private" not in clean


def test_official_request_and_transcript_response(caplog):
    requests = []

    async def respond(request):
        requests.append(request)
        body = await request.aread()
        assert request.url.path == "/v1/asr/transcribe"
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        assert b'"model": "muse-voice-transcribe-1.0"' in body
        assert b'"mode": "PUSH_TO_TALK"' in body
        assert b'name="audio"' in body
        return httpx.Response(
            200, json={"transcript": "  Private test words  ", "audioDurationMs": 100, "turns": []}
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await voice.transcribe_audio(wav(), settings=SETTINGS, client=client)
        assert result["text"] == "Private test words"
        assert result["model"] == "muse-voice-transcribe-1.0"
        assert result["duration_ms"] == 100
        assert result["request_id"].startswith("dictation-")

    asyncio.run(run())
    assert len(requests) == 1
    assert "Private test words" not in caplog.text
    assert "synthetic-test-key" not in caplog.text
    assert voice._active_requests == 0


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (403, {"error": "secret provider details"}, 503),
        (429, {"error": "secret provider details"}, 429),
        (500, {"error": "secret provider details"}, 502),
        (200, {"transcript": {"bad": "schema"}}, 502),
        (200, ["bad schema"], 502),
    ],
)
def test_provider_errors_are_sanitized_without_retries(status, body, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(voice.TranscriptionError) as caught:
                await voice.transcribe_audio(wav(), settings=SETTINGS, client=client)
        assert caught.value.status_code == expected
        assert "secret provider details" not in str(caught.value)
        assert voice._active_requests == 0

    asyncio.run(run())
    assert len(calls) == 1


def test_timeout_and_cancellation_release_capacity():
    async def timeout(request):
        raise httpx.ReadTimeout("private details")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(voice.TranscriptionError) as caught:
                await voice.transcribe_audio(wav(), settings=SETTINGS, client=client)
        assert caught.value.status_code == 504
        entered = asyncio.Event()

        async def hang(request):
            entered.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(hang)) as client:
            task = asyncio.create_task(
                voice.transcribe_audio(wav(), settings=SETTINGS, client=client)
            )
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert voice._active_requests == 0

    asyncio.run(run())


def test_route_does_not_send_message_or_change_project(monkeypatch):
    async def transcribe(content):
        voice.validate_audio(content)
        return {
            "text": "Editable dictation",
            "model": voice.VOICE_MODEL,
            "duration_ms": 100,
            "request_id": "synthetic",
        }

    monkeypatch.setattr(api, "transcribe_audio", transcribe)
    api._sessions.clear()
    with TestClient(api.app) as client:
        original = client.post("/api/projects").json()["project"]
        response = client.post(
            "/api/transcribe", content=wav(), headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 200
        assert response.json()["text"] == "Editable dictation"
        assert api._sessions[original["id"]].project == original
        assert api._sessions[original["id"]].history == []
        assert (
            client.post("/api/transcribe", json={"url": "https://example.test/a.wav"}).status_code
            == 415
        )
        assert (
            client.post(
                "/api/transcribe", content=b"bad", headers={"Content-Type": "audio/wav"}
            ).status_code
            == 422
        )
    api._sessions.clear()
