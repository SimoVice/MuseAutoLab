"""Source identity, factual geometry scope and model-advice boundaries."""

import json
import re
from copy import deepcopy
from urllib.parse import urlparse

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api as api
from app.assembly import build_document_files
from app.design_sources import project_source_basis, reference_context, reference_library
from app.domain import confirm_project, new_project
from app.inspection import apply_extension
from app.model_client import ExtractedTurn, SourceRecommendation
from app.project_storage import make_snapshot, restore_snapshot


def test_source_library_has_primary_urls_pins_and_scoped_rights():
    library = reference_library()
    assert re.fullmatch("[a-f0-9]{64}", library["sha256"])
    ids = {ref["id"] for ref in library["references"]}
    assert ids == set(
        SourceRecommendation.model_json_schema()["properties"]["reference_id"]["enum"]
    )
    for ref in library["references"]:
        assert urlparse(ref["url"]).hostname in {
            "github.com",
            "www.pololu.com",
            "www.raspberrypi.com",
            "docs.opentrons.com",
            "opentrons.com",
        }
        assert ref["checked_on"] == ("2026-10-29" if ref["id"] == "opentrons-ot2"
                                     else "2026-10-28")
        assert ref["use"] and ref["limits"] and ref["license"]
        if ref["kind"] in ("open_hardware", "open_source"):
            assert re.fullmatch("[a-f0-9]{40}", ref["revision"])
            assert ref["revision"] in ref["url"] and ref["revision"] in ref["license_url"]
    library["references"][0]["title"] = "changed"
    assert reference_library()["references"][0]["title"] != "changed"


def test_basis_does_not_turn_custom_parts_into_verified_hardware():
    project = apply_extension(layout_project(), inspection_proposal(), {"model": "offline"})
    basis = project_source_basis(project)
    assert basis == project["design_basis"]
    bindings = {item["component_id"]: item for item in basis["bindings"]}
    assert bindings["carriage"]["primitive_id"] == "motor"
    assert bindings["inspection-camera"]["reference_id"] == "rpi-camera-module-3"
    for cid in (
        "base",
        "pipette",
        "sample-rack",
        "inspection-upper-link",
        "inspection-camera-mount",
    ):
        assert bindings[cid]["basis"] == "custom_concept"
        assert bindings[cid]["reference_id"] is None
    context = reference_context(new_project())
    assert context["geometry_bindings"] == []
    assert "no machine adapter" in context["architecture"]


def test_unknown_model_reference_is_rejected_and_advice_is_not_a_requirement():
    with pytest.raises(ValidationError):
        ExtractedTurn.model_validate(
            {
                "assistant_message": "Try a made-up brand",
                "recommendations": [
                    {"reference_id": "invented-product", "reason": "No source"},
                ],
            }
        )
    turn = ExtractedTurn.model_validate(
        {
            "assistant_message": "Review a documented foundation.",
            "recommendations": [
                {"reference_id": "science-jubilee", "reason": "Documented tool workflow."}
            ],
        }
    )
    assert turn.patch() == {}


def test_advice_api_returns_resolved_sources_and_preserves_inputs(monkeypatch):
    async def fake(*args):
        return ExtractedTurn.model_validate(
            {
                "assistant_message": "Consider this documented foundation.",
                "recommendations": [
                    {"reference_id": "science-jubilee", "reason": "Pipette/camera reference."}
                ],
            }
        ), {}

    monkeypatch.setattr(api, "generate_turn", fake)
    api._sessions.clear()
    with TestClient(api.app) as client:
        original = client.post("/api/projects").json()["project"]
        root = f"/api/projects/{original['id']}"
        result = client.post(
            root + "/messages", json={"message": "Which documented project could help?"}
        )
        assert result.status_code == 200
        data = result.json()
        assert data["project"] == original
        ref = data["recommendations"][0]["reference"]
        assert ref["id"] == "science-jubilee" and "bb918fa" in ref["url"]
        assert "[science-jubilee]" not in data["assistant_message"]
        assert "[science-jubilee]" in api._sessions[original["id"]].history[-1]["content"]
        assert client.get(root + "/sources?revision=10").status_code == 409
        sources = client.get(root + "/sources?revision=0")
        assert sources.status_code == 200
        assert "attachment" in sources.headers["content-disposition"]
        assert sources.json()["source_basis"]["bindings"] == []
        assert len(client.get("/api/references").json()["references"]) == 7
    api._sessions.clear()


def test_legacy_saved_project_requires_reconfirmation_after_geometry_upgrade():
    original = confirm_project(layout_project())
    saved = make_snapshot(original, [])
    assert saved["compiler_version"] == "4"
    saved["compiler_version"] = "1"
    before = deepcopy(saved)
    restored, _ = restore_snapshot(saved)
    assert saved == before
    assert restored["revision"] == original["revision"] + 1
    assert restored["status"] == "draft"
    assert "chat" in restored["rebuild_notice"]
    assert not restored.get("engineering_design")
    reopened, _ = restore_snapshot(make_snapshot(restored, []))
    assert reopened["revision"] == restored["revision"]
    assert reopened["design"] == restored["design"]


def test_source_records_are_present_in_real_assembly_documents():
    project = apply_extension(layout_project(), inspection_proposal(), {"model": "offline"})
    files = build_document_files(project)
    guide = files["assembly-guide.html"]
    assert b"Design sources and geometry basis" in guide
    assert b"CC-BY-4.0" in guide and b"bb918fa" in guide
    module = json.loads(files["inspection-module.json"])["module"]
    assert module["source_binding"]["camera"]["size_mm"] == [25, 11.5, 24]
