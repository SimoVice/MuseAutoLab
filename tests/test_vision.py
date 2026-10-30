"""Meaningful tests for app/vision.py (image prep, schema, mocked client)."""

import asyncio
import base64
import io
import json

import httpx
import pytest

from app.model_client import ModelSettings
from app.vision import (
    Box,
    CanonicalImage,
    RawDetection,
    RawInspection,
    VisionError,
    analyze_image,
    prepare_image,
)


def _make_image_bytes(fmt="PNG", size=(64, 48), color=(10, 120, 200)):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _valid_raw() -> dict:
    return {
        "image_quality": "clear",
        "coverage": "complete",
        "summary": "Two tubes visible.",
        "warnings": [],
        "detections": [
            {
                "kind": "tube",
                "label": "tube A",
                "box": {"x_min": 10, "y_min": 20, "x_max": 200, "y_max": 300},
                "confidence": 0.9,
                "uncertain": False,
                "reason": "capped tube",
                "tip_rack_contents": "not_applicable",
            }
        ],
    }


def test_prepare_png_ok_strips_metadata():
    raw = _make_image_bytes("PNG", (200, 100))
    canonical = prepare_image(_data_url(raw, "image/png"))
    assert isinstance(canonical, CanonicalImage)
    assert canonical.content.startswith(b"\xff\xd8\xff")
    assert canonical.data_url.startswith("data:image/jpeg;base64,")
    assert len(canonical.sha256) == 64
    assert (canonical.width, canonical.height) == (200, 100)
    from PIL import Image

    with Image.open(io.BytesIO(canonical.content)) as reopened:
        assert reopened.format == "JPEG"
        assert reopened.info.get("exif") is None


def test_prepare_jpeg_ok_and_downscales_longest_edge():
    raw = _make_image_bytes("JPEG", (2000, 1000))
    canonical = prepare_image(_data_url(raw, "image/jpeg"))
    assert max(canonical.width, canonical.height) == 1600
    assert (canonical.width, canonical.height) == (1600, 800)


def test_prepare_rejects_bool_non_string_and_bad_scheme():
    with pytest.raises(VisionError):
        prepare_image(True)  # type: ignore[arg-type]
    with pytest.raises(VisionError):
        prepare_image(123)  # type: ignore[arg-type]
    with pytest.raises(VisionError):
        prepare_image("data:image/gif;base64,AAAA")
    with pytest.raises(VisionError):
        prepare_image("not-a-data-url")


def test_prepare_rejects_mime_mismatch():
    png = _make_image_bytes("PNG", (64, 48))
    with pytest.raises(VisionError):
        prepare_image(_data_url(png, "image/jpeg"))


def test_prepare_rejects_truncated_and_too_small():
    with pytest.raises(VisionError):
        prepare_image("data:image/png;base64,!!!notbase64!!!")
    with pytest.raises(VisionError):
        prepare_image(_data_url(b"\xff\xd8\xff" + b"\x00" * 100, "image/jpeg"))
    tiny = _make_image_bytes("PNG", (16, 16))
    with pytest.raises(VisionError):
        prepare_image(_data_url(tiny, "image/png"))


def test_prepare_rejects_oversized_decoded():
    big_body = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * (4 * 1024 * 1024 + 1)).decode()
    with pytest.raises(VisionError):
        prepare_image("data:image/png;base64," + big_body)


def test_box_bounds_and_order():
    with pytest.raises(Exception):
        Box.model_validate({"x_min": 500, "y_min": 10, "x_max": 100, "y_max": 200})
    with pytest.raises(Exception):
        Box.model_validate({"x_min": -1, "y_min": 0, "x_max": 10, "y_max": 10})
    box = Box.model_validate({"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000})
    assert box.x_max == 1000


def test_raw_schema_requires_all_fields_forbids_extras():
    with pytest.raises(Exception):
        RawInspection.model_validate({})  # missing required
    bad = _valid_raw()
    bad["extra"] = 1
    with pytest.raises(Exception):
        RawInspection.model_validate(bad)
    bad_det = _valid_raw()
    bad_det["detections"][0]["confidence"] = 5.0
    with pytest.raises(Exception):
        RawInspection.model_validate(bad_det)
    many = _valid_raw()
    many["detections"] = [dict(_valid_raw()["detections"][0]) for _ in range(25)]
    with pytest.raises(Exception):
        RawInspection.model_validate(many)
    ok = RawInspection.model_validate(_valid_raw())
    assert ok.detections[0].kind == "tube"


def _mock_client(payload_content: str, usage=None, status=200) -> httpx.AsyncClient:
    body = {
        "choices": [{"finish_reason": "stop", "message": {"content": payload_content}}],
        "usage": usage or {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content.decode())
        assert sent["reasoning_effort"] == "minimal"
        assert sent["max_completion_tokens"] == 6000
        assert sent["response_format"]["json_schema"]["strict"] is True
        dev = sent["messages"][0]["content"]
        assert isinstance(dev, str) and "0..1000" in dev
        user = sent["messages"][1]["content"]
        blob = json.dumps(user)
        assert blob.count("data:image/jpeg;base64,") == 1
        assert "project" not in json.dumps(sent).lower() or "project" not in dev.lower()
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_analyze_success_returns_validated_raw_and_usage():
    canonical = prepare_image(_data_url(_make_image_bytes("PNG"), "image/png"))
    settings = ModelSettings(api_key="k", base_url="https://x.test/v1", model="m")
    client = _mock_client(json.dumps(_valid_raw()))

    async def run():
        async with client:
            return await analyze_image(canonical, client=client, settings=settings)

    raw, usage = asyncio.run(run())
    assert raw["summary"] == "Two tubes visible."
    assert usage == {"model": settings.model, "prompt_tokens": 5,
                     "completion_tokens": 7, "total_tokens": 12}


def test_analyze_invalid_model_json_raises_sanitized():
    canonical = prepare_image(_data_url(_make_image_bytes("PNG"), "image/png"))
    settings = ModelSettings(api_key="k", base_url="https://x.test/v1", model="m")
    client = _mock_client(json.dumps({"wrong": "shape"}))

    async def run():
        async with client:
            await analyze_image(canonical, client=client, settings=settings)

    with pytest.raises(VisionError):
        asyncio.run(run())


def test_detection_requires_tip_rack_contents():
    det = dict(_valid_raw()["detections"][0])
    del det["tip_rack_contents"]
    with pytest.raises(Exception):
        RawDetection.model_validate(det)


def test_exif_orientation_applies_and_metadata_is_removed():
    from PIL import Image

    source = Image.new("RGB", (100, 60), "green")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "PRIVATE-METADATA-PROBE"
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    result = prepare_image(_data_url(buffer.getvalue(), "image/jpeg"))
    assert (result.width, result.height) == (60, 100)
    assert b"PRIVATE-METADATA-PROBE" not in result.content
    with Image.open(io.BytesIO(result.content)) as reopened:
        assert len(reopened.getexif()) == 0


def test_pixel_limit_checked_before_decoding(monkeypatch):
    from PIL import Image

    raw = _make_image_bytes("PNG", (4001, 4000))

    def forbidden(*args, **kwargs):
        raise AssertionError("Pixel load must not happen above the cap")

    monkeypatch.setattr(Image.Image, "load", forbidden)
    with pytest.raises(VisionError, match="16 megapixel"):
        prepare_image(_data_url(raw, "image/png"))


@pytest.mark.parametrize("bad", [True, "2", float("inf"), float("nan")])
def test_box_rejects_nonfinite_and_coercion(bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Box.model_validate({"x_min": bad, "y_min": 1, "x_max": 500, "y_max": 500})
