import hashlib
import json
import struct
from pathlib import Path

import pytest

from app.upstream_cad import STEP_PATH, foundation_metadata, original_step_bytes

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "public" / "assets"
MANIFEST = STEP_PATH.with_name("jubilee-c877bd2.provenance.json")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _bounds(path):
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    size = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + size])
    return gltf["accessors"][0]["min"], gltf["accessors"][0]["max"]


def test_pinned_source_and_previews_match_provenance():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert _digest(STEP_PATH.read_bytes()) == manifest["gzip_sha256"]
    assert _digest(original_step_bytes()) == manifest["original_step_sha256"]
    for name in ("static", "bed"):
        path = ASSETS / f"jubilee-c877bd2-{name}.glb"
        assert _digest(path.read_bytes()) == manifest[f"{name}_preview_glb_sha256"]


def test_bed_pose_is_bounded_and_maps_to_preview_coordinates():
    metadata = foundation_metadata(100)
    low, high = _bounds(ASSETS / "jubilee-c877bd2-bed.glb")
    assert high[1] - low[1] == pytest.approx(19, abs=0.001)
    assert metadata["deck_origin_app_mm"][1] == pytest.approx(
        high[1] - 272.216535584 - 100, abs=0.001
    )
    assert (foundation_metadata(0)["deck_origin_app_mm"][1]
            - metadata["deck_origin_app_mm"][1]) == 100
    for invalid in (-1, 151, float("nan"), True):
        with pytest.raises(ValueError):
            foundation_metadata(invalid)
