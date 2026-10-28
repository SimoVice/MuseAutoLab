"""Checks for shared, illustrative component primitives."""

from copy import deepcopy

import pytest

from app.domain import apply_update, new_project
from app.geometry import add_geometry


def test_primitives_are_deterministic_and_contained():
    base = new_project()
    assert add_geometry(base) == base
    assert add_geometry(base) is not base
    for project in (
        base,
        apply_update(base, {"workspace_width_mm": 450}),
        apply_update(base, {"cooling_enabled": True}),
        apply_update(base, {"cooling_enabled": True, "selections": {"cooling": "opentrons-gen2"}}),
    ):
        for comp in project["design"]["components"]:
            geom = comp["geometry"]
            assert geom["schema_version"] == "1"
            assert len({p["id"] for p in geom["primitives"]}) == len(geom["primitives"])
            for p in geom["primitives"]:
                assert p["kind"] in {"box", "cylinder", "frustum", "tube", "plate"}
                assert p["appearance"]
                for pos, size, bound in zip(p["position"], p["size"], comp["size"]):
                    assert size > 0 and abs(pos) + size / 2 <= bound / 2 + 1e-8
                if p["kind"] == "plate":
                    for hole in p["holes"]:
                        assert abs(hole["x_mm"]) + hole["radius_mm"] < p["size"][0] / 2
                        assert abs(hole["z_mm"]) + hole["radius_mm"] < p["size"][2] / 2


def test_fixed_component_geometry_survives_layout_changes():
    initial = new_project()
    compact = apply_update(initial, {"workspace_width_mm": 450})
    cold = apply_update(compact, {"cooling_enabled": True})
    versions = [{c["id"]: c for c in p["design"]["components"]} for p in (initial, compact, cold)]
    for component_id in set(versions[0]) - {"base", "crossbar"}:
        assert (
            versions[0][component_id]["size"]
            == versions[1][component_id]["size"]
            == versions[2][component_id]["size"]
        )
        assert (
            versions[0][component_id]["geometry"]
            == versions[1][component_id]["geometry"]
            == versions[2][component_id]["geometry"]
        )
    before = deepcopy(initial)
    apply_update(initial, {"workspace_width_mm": 450})
    assert initial == before


def test_rack_holes_match_fixed_source_and_tip_proxies():
    parts = {c["id"]: c for c in new_project()["design"]["components"]}

    def holes(cid):
        return [
            h["x_mm"]
            for p in parts[cid]["geometry"]["primitives"]
            if p["kind"] == "plate"
            for h in p["holes"]
        ]

    assert {-10, 10} <= set(holes("source-rack"))
    assert holes("tip-rack") == [-28.5, -9.5, 9.5, 28.5]


def test_sample_pattern_tracks_target_count_without_overlap():
    project = new_project()
    for count in range(1, 7):
        project["plan"]["steps"] = [{}] * count
        result = add_geometry(project)
        rack = next(c for c in result["design"]["components"] if c["id"] == "sample-rack")
        holes = next(p["holes"] for p in rack["geometry"]["primitives"] if p["kind"] == "plate")
        spacing = min(20, rack["size"][0] / (count + 1))
        assert rack["rack_slot_count"] == count
        assert [h["x_mm"] for h in holes] == pytest.approx(
            [(i - (count - 1) / 2) * spacing for i in range(count)]
        )
        assert all(
            b["x_mm"] - a["x_mm"] > a["radius_mm"] + b["radius_mm"]
            for a, b in zip(holes, holes[1:])
        )
