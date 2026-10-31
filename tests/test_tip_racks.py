"""Offline coherent product choices; no supplier, model, printer or hardware calls."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_microplates import before

import app.api as api
from app.domain import apply_update
from app.engineering import state_for
from app.instructions import build_instruction_guide
from app.model_client import ChatAction, ExtractedTurn
from app.procurement import report_for_project
from app.project_storage import make_snapshot, restore_snapshot
from app.tip_racks import (
    PRINTED_ID,
    TipRackUpdate,
    declared_printer,
    select_tip_rack,
    show_tip_options,
    tip_rack_options,
    update_tip_request,
)

TIPONE = "tipone_96_tiprack_200ul"
OPENTRONS = "opentrons_96_tiprack_300ul"
SPEC = {
    "body_diameter_max_mm": 6.0,
    "rim_diameter_min_mm": 9.0,
    "rim_diameter_max_mm": 10.0,
    "below_rim_height_mm": 45.0,
    "count": 12,
    "columns": 4,
}


def selected(project=None, profile=TIPONE):
    project = project or before(arm=True)
    update = TipRackUpdate(profile_id=profile, source=profile)
    pending = update_tip_request(project, update, profile)
    return select_tip_rack(pending, update, profile, accept_placement=True)[0]


def test_actual_profiles_change_holes_and_size_preserving_all_other_components_and_recipe():
    original = before(arm=True)
    snapshot = deepcopy(original)
    first = selected(original)
    second = selected(first, OPENTRONS)
    assert first["tip_rack"]["size_mm"] == [127.76, 63.9, 85.48]
    assert second["tip_rack"]["size_mm"] == [127.76, 64.49, 85.48]
    for result in (first, second):
        assert result["summary"] == original["summary"]
        assert result["plan"] == original["plan"]
        assert result["engineering_design"] == original["engineering_design"]
        assert result["inspection_extension"] == original["inspection_extension"]
        assert result["labware_rack"] == original["labware_rack"]
        assert result["status"] == "draft"
        index = {p["id"]: p for p in result["design"]["components"]}
        assert all(
            index[p["id"]] == p for p in original["design"]["components"] if p["id"] != "tip-rack"
        )
    first_holes = first["tip_rack"]["geometry"]["primitives"][1]["holes"]
    second_holes = second["tip_rack"]["geometry"]["primitives"][1]["holes"]
    assert first_holes != second_holes
    assert first_holes[0]["radius_mm"] == 3.2
    assert second_holes[0]["radius_mm"] == 2.615
    assert original == snapshot


def test_preview_exposes_closest_shift_and_chat_requires_confirmation_before_moving():
    original = before()
    preview = tip_rack_options(original)["options"][0]["geometry"]["placement"]
    assert preview["status"] == "requires_shift"
    assert preview["shift_mm"] == pytest.approx(3.88)
    update = TipRackUpdate(profile_id=TIPONE, source=TIPONE)
    pending = update_tip_request(original, update, TIPONE)
    pending, run = select_tip_rack(pending, update, TIPONE)
    assert run["status"] == "ready" and "Confirm" in run["message"]
    assert pending["design"] == original["design"]
    accepted, run = select_tip_rack(pending, TipRackUpdate(), "yes")
    assert run["status"] == "accepted"
    assert accepted["tip_rack"]["placement_proposal"]["shift_mm"] == pytest.approx(3.88)
    with pytest.raises(ValueError, match="preserved"):
        select_tip_rack(
            pending, update, "Use TipOne but do not move the tip rack", accept_placement=True
        )


def test_printer_unknown_questions_first_no_has_only_commercial_yes_requires_dimensions():
    project = before()
    assert PRINTED_ID not in [o["id"] for o in tip_rack_options(project)["options"]]
    project, run = show_tip_options(project)
    assert "Do you have access" in run["message"]
    assert project["tip_rack_request"]["awaiting_printer"]
    no = update_tip_request(project, TipRackUpdate(), "No")
    assert no["fabrication_capabilities"]["printer_available"] == "no"
    assert PRINTED_ID not in [o["id"] for o in tip_rack_options(no)["options"]]
    yes = update_tip_request(project, TipRackUpdate(), "Sì")
    assert PRINTED_ID in [o["id"] for o in tip_rack_options(yes)["options"]]
    yes = update_tip_request(
        yes, TipRackUpdate(profile_id=PRINTED_ID, source=PRINTED_ID), PRINTED_ID
    )
    result, run = select_tip_rack(yes, TipRackUpdate(), "Print the holder")
    assert run["status"] == "ready" and "rim_diameter_max_mm" in run["message"]
    assert result["design"] == project["design"]


@pytest.mark.parametrize(
    "text",
    [
        "I don't have a pipette",
        "non ho la pipetta",
        "yes",
        "I will buy a 3D printer later",
        "If I had a 3D printer?",
        "Do I need a 3D printer?",
    ],
)
def test_unrelated_future_or_hypothetical_printer_statement_never_sets_access(text):
    assert declared_printer(text) is None
    if text != "yes":
        assert declared_printer(text, contextual=True) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I don't have a 3D printer", "no"),
        ("Non ho una stampante 3D", "no"),
        ("Ho una stampante 3D", "yes"),
    ],
)
def test_explicit_present_printer_statement(text, expected):
    assert declared_printer(text) == expected


def test_bare_capability_source_needs_real_pending_context_and_hypothetical_choice_rejected():
    update = TipRackUpdate(printer_available="yes", printer_source="yes")
    with pytest.raises(ValueError):
        update.verify_sources("yes")
    update.verify_sources("yes", printer_context=True)
    for text in (
        "Compare TipOne",
        "Would TipOne be compatible?",
        "Use TipOne later",
        "Do not use TipOne",
    ):
        with pytest.raises(ValueError):
            TipRackUpdate(profile_id=TIPONE, source=text).verify_sources(text)


def test_printed_holder_uses_declared_dimensions_and_exports_actionable_revision_guide():
    project = before()
    project["fabrication_capabilities"] = {
        "printer_available": "yes",
        "source": "I have a 3D printer",
    }
    project["tip_rack_request"] = {
        "profile_id": PRINTED_ID,
        "spec": SPEC,
        "spec_sources": {key: "synthetic test fixture" for key in SPEC},
    }
    result, run = select_tip_rack(
        project, TipRackUpdate(), "Use the printed holder", accept_placement=True
    )
    assert run["status"] == "accepted"
    assert result["tip_rack"]["derived"]["count"] == 12
    guide = build_instruction_guide(result)
    assert guide["project_revision"] == result["revision"]
    steps = {step["id"]: step for step in guide["steps"]}
    assert "tip-rack-coupon" in steps and "printed-tip-rack" in steps
    assert "Never print disposable" in " ".join(steps["tip-rack-coupon"]["instructions"])


def test_portable_rebuild_preserves_profile_binding_and_quantities_and_return_is_reversible():
    original = before(arm=True)
    result = selected(original)
    snapshot = make_snapshot(result, [])
    assert snapshot["compiler_version"] == "7"
    assert "geometry" not in snapshot["tip_rack"]
    restored, _ = restore_snapshot(snapshot)
    assert restored["tip_rack"] == result["tip_rack"]
    assert restored["summary"] == original["summary"]
    changed = apply_update(restored, {"final_volume": "150 uL"})
    assert changed["tip_rack"] == restored["tip_rack"]
    assert (
        next(g for g in changed["sourcing"]["groups"] if g["id"] == "tip-rack-options")[
            "selected_id"
        ]
        == TIPONE
    )
    returned, _ = select_tip_rack(
        changed, TipRackUpdate(profile_id="previous_tip_rack"), "Restore previous tip rack"
    )
    old = next(c for c in original["design"]["components"] if c["id"] == "tip-rack")
    assert next(c for c in returned["design"]["components"] if c["id"] == "tip-rack") == old
    tampered = deepcopy(snapshot)
    tampered["tip_rack"]["profile_binding"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        restore_snapshot(tampered)


def test_snapshot_retains_printer_question_and_reply_context():
    pending, _ = show_tip_options(before())
    reopened, _ = restore_snapshot(make_snapshot(pending, []))
    assert reopened["tip_rack_request"]["awaiting_printer"]
    reopened = update_tip_request(reopened, TipRackUpdate(), "No")
    assert reopened["fabrication_capabilities"]["printer_available"] == "no"


def test_unsupported_route_or_collision_rejects_without_mutating_project():
    project = before()
    original = deepcopy(project)
    invalid = deepcopy(original)
    next(c for c in invalid["design"]["components"] if c["id"] == "base")["size"] = [60, 12, 60]
    with pytest.raises(ValueError, match="cannot fit"):
        selected(invalid)
    unsupported = deepcopy(original)
    unsupported["engineering"] = {**state_for(unsupported), "selected_platform_id": "opentrons-ot2"}
    with pytest.raises(ValueError, match="Jubilee"):
        selected(unsupported)
    assert "tip_rack" not in original


@pytest.mark.parametrize(
    "message,source",
    [
        ("I don't own a 3D printer", "own a 3D printer"),
        ("If I had a 3D printer", "a 3D printer"),
        ("I will have a 3D printer later", "have a 3D printer"),
    ],
)
def test_printer_source_cannot_strip_surrounding_negative_or_hypothetical_intent(message, source):
    update = TipRackUpdate(printer_available="yes", printer_source=source)
    with pytest.raises(ValueError):
        update.verify_sources(message, printer_context=True)


@pytest.mark.parametrize(
    "message",
    [
        "Don't select TipOne",
        "Non voglio TipOne",
        "If I chose TipOne",
        "Compare TipOne",
        "Is TipOne compatible?",
        "I may select TipOne later",
    ],
)
def test_product_alias_source_cannot_strip_surrounding_nonchoice_context(message):
    with pytest.raises(ValueError):
        TipRackUpdate(profile_id=TIPONE, source="TipOne").verify_sources(message)


@pytest.mark.parametrize(
    "key,literal,value",
    [
        ("rim_diameter_min_mm", "minimum rim diameter 9 mm", 9.0),
        ("rim_diameter_min_mm", "diametro minimo del bordo 9 mm", 9.0),
        ("rim_diameter_max_mm", "diametro massimo del bordo 10 mm", 10.0),
    ],
)
def test_dimension_sources_accept_explicit_role_in_both_word_orders(key, literal, value):
    update = TipRackUpdate(spec={key: value}, spec_sources={key: literal})
    update.verify_sources(literal)
    with pytest.raises(ValueError):
        update.verify_sources("Do not use " + literal)


def test_chat_alternatives_then_contextual_yes_uses_declared_capability(monkeypatch):
    api._sessions.clear()
    project = before()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    url = f"/api/projects/{project['id']}"

    async def model(project, message, history):
        if message == "Show tip-rack alternatives":
            return ExtractedTurn(
                assistant_message="Compare options",
                actions=[ChatAction(kind="show_tip_rack_options", source=message)],
            ), {}
        return ExtractedTurn(
            assistant_message="Recorded",
            tip_rack=TipRackUpdate(printer_available="yes", printer_source="Sì"),
        ), {}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        asked = client.post(url + "/messages", json={"message": "Show tip-rack alternatives"})
        assert asked.status_code == 200
        assert "Do you have access" in asked.json()["assistant_message"]
        answered = client.post(url + "/messages", json={"message": "Sì"})
        assert answered.status_code == 200
        assert answered.json()["project"]["fabrication_capabilities"]["printer_available"] == "yes"
        assert "printed holder" in answered.json()["assistant_message"]
        assert answered.json()["project"]["design"] == project["design"]


def test_api_choices_stale_revision_and_atomic_chat_rejection(monkeypatch):
    api._sessions.clear()
    project = before()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    url = f"/api/projects/{project['id']}"
    with TestClient(api.app) as client:
        options = client.get(
            url + "/tip-rack-options", params={"revision": project["revision"]}
        ).json()
        assert options["options"][0]["geometry"]["placement"]["status"] == "requires_shift"
        response = client.post(
            url + "/tip-rack-options", json={"revision": project["revision"], "profile_id": TIPONE}
        )
        assert response.status_code == 200
        current = response.json()["project"]
        assert current["tip_rack"]["profile_id"] == TIPONE
        assert (
            client.get(url + "/instructions", params={"revision": project["revision"]}).status_code
            == 409
        )
        assert (
            client.post(
                url + "/tip-rack-options",
                json={"revision": project["revision"], "profile_id": OPENTRONS},
            ).status_code
            == 409
        )
        assert (
            report_for_project(
                current, {"project_id": project["id"], "project_revision": project["revision"]}
            )
            is None
        )

        async def model(project, message, history):
            return ExtractedTurn(
                assistant_message="Select another rack",
                final_volume="150 uL",
                source_final_volume="150 uL",
                tip_rack=TipRackUpdate(profile_id="not-reviewed", source=message),
                actions=[ChatAction(kind="select_tip_rack", source=message)],
            ), {}

        monkeypatch.setattr(api, "generate_turn", model)
        rejected = client.post(
            url + "/messages", json={"message": "Use an unknown rack and 150 uL"}
        )
        assert rejected.status_code == 422
        assert api._sessions[project["id"]].project == current
    api._sessions.clear()
