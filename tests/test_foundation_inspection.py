"""Source inspection poses retain the foundation and use deck-relative heights."""

import pytest
from evolution_fixtures import inspection_proposal
from test_foundation_storage import source_project

from app.geometry import add_geometry
from app.inspection import apply_extension, clear_extension


def test_inspection_follows_source_deck_and_uses_external_sidecar():
    one = source_project(100)
    two = source_project(130)
    ext_one = apply_extension(one, inspection_proposal(), {})
    ext_two = apply_extension(two, inspection_proposal(), {})
    m1, m2 = ext_one["inspection_extension"], ext_two["inspection_extension"]
    y1 = m1["pose_frames"][0]["camera_mm"][1]
    y2 = m2["pose_frames"][0]["camera_mm"][1]
    assert y1 - y2 == pytest.approx(30)
    assert m1["proposal"]["mast_height_mm"] == 450
    frame = next(p for p in one["design"]["components"] if p["id"] == "foundation-jubilee")
    front = frame["position"][2] + frame["size"][2] / 2
    for component in m1["components"]:
        if component["id"] in ("inspection-mount", "inspection-mast", "inspection-shoulder"):
            assert component["position"][2] - component["size"][2] / 2 >= front + 10 - 1e-6
    rebuilt = add_geometry(ext_one)
    assert rebuilt["inspection_extension"]["components"] == m1["components"]
    camera = next(p for p in rebuilt["design"]["components"] if p["id"] == "inspection-camera")
    original = next(p for p in ext_one["design"]["components"] if p["id"] == "inspection-camera")
    assert camera == original


def test_clear_inspection_restores_source_sourcing_and_bounds():
    project = source_project()
    extended = apply_extension(project, inspection_proposal(), {})
    cleared = clear_extension(extended)
    assert cleared["design"]["foundation"] == project["design"]["foundation"]
    assert cleared["design"]["components"] == project["design"]["components"]
    assert cleared["design"]["assembly_bounds"] == project["design"]["assembly_bounds"]
    assert cleared["sourcing"] == project["sourcing"]
    assert not cleared.get("inspection_extension")
