"""Ordinary API semantic cold-transfer tests; synthetic model responses only."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_cold_transfer import plate_project

from app import api
from app.cold_transfer import apply_cold_transfer
from app.model_client import ChatAction, ColdTransferGrounding, ExtractedTurn


def post_message(project_id, message):
    """Post to the same endpoint as the composer and release the test session."""
    try:
        with TestClient(api.app) as client:
            return client.post(f"/api/projects/{project_id}/messages", json={"message": message})
    finally:
        api._sessions.pop(project_id, None)


@pytest.mark.parametrize(
    "message,kind,payload,destination,accepted",
    [
        (
            "Give the prepared plate its own fridge.",
            "add_cold_transfer",
            "prepared plate",
            "its own fridge",
            True,
        ),
        (
            "When the run is over, park the finished plate in its own chilled cabinet.",
            "add_cold_transfer",
            "finished plate",
            "its own chilled cabinet",
            True,
        ),
        (
            "Give the finished plate its own refrigerated compartment.",
            "add_cold_transfer",
            "finished plate",
            "its own refrigerated compartment",
            True,
        ),
        (
            "Have the finished plate put away in a dedicated refrigerated cabinet.",
            "add_cold_transfer",
            "finished plate",
            "dedicated refrigerated cabinet",
            True,
        ),
        (
            "Alongside the inspection camera, give the finished plate its own fridge.",
            "add_cold_transfer",
            "finished plate",
            "its own fridge",
            True,
        ),
        (
            "How would the prepared plate reach its own fridge?",
            "add_cold_transfer",
            "prepared plate",
            "its own fridge",
            False,
        ),
        (
            "Maybe give the prepared plate its own fridge later.",
            "add_cold_transfer",
            "prepared plate",
            "its own fridge",
            False,
        ),
        (
            "Give the prepared plate its own fridge at 4 C.",
            "add_cold_transfer",
            "prepared plate",
            "its own fridge",
            False,
        ),
        (
            "Give the camera its own fridge; leave the plate alone.",
            "add_cold_transfer",
            "plate",
            "its own fridge",
            False,
        ),
        (
            "Give the prepared plate a shared fridge.",
            "add_cold_transfer",
            "prepared plate",
            "shared fridge",
            False,
        ),
        (
            "Give the tubes their own fridge.",
            "add_cold_transfer",
            "tubes",
            "their own fridge",
            False,
        ),
        ("Give it its own fridge.", "add_cold_transfer", "prepared plate", "its own fridge", False),
        (
            "Give the prepared plate its own fridge and add an inspection camera.",
            "add_cold_transfer",
            "prepared plate",
            "its own fridge",
            False,
        ),
        (
            "Can you add a refrigerator and maybe an arm to store completed samples in it?",
            "add_cold_transfer", "completed samples", "refrigerator", True,
        ),
        (
            "Can you add a refrigerator and maybe an arm to store completed tubes in it?",
            "add_cold_transfer", "completed tubes", "refrigerator", False,
        ),
        (
            "Maybe add an arm to transfer the prepared plate to its own fridge later.",
            "add_cold_transfer", "prepared plate", "its own fridge", False,
        ),
        ("Could this work for plates and a fridge?", "discuss_cold_transfer", None, None, False),
    ],
)
def test_semantic_api(monkeypatch, message, kind, payload, destination, accepted):
    project = plate_project()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    calls = []

    async def model(current, latest, history):
        calls.append(latest)
        return ExtractedTurn(
            assistant_message="Synthetic response",
            actions=[
                ChatAction(
                    kind=kind,
                    source=latest,
                    cold_transfer=ColdTransferGrounding(
                        payload="selected_rigid_plate",
                        destination="dedicated_refrigerated",
                        payload_source=payload,
                        destination_source=destination,
                    )
                    if payload and destination
                    else None,
                )
            ],
        ), {"total_tokens": 12}

    monkeypatch.setattr(api, "generate_turn", model)
    response = post_message(project["id"], message)
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == [message]
    assert body["usage"] == {"total_tokens": 12}
    assert bool(body["project"].get("cold_transfer_extension")) is accepted
    if not accepted:
        assert body["project"] == original
    else:
        assert body["project"]["revision"] == original["revision"] + 1
        assert body["project"]["summary"] == original["summary"]


@pytest.mark.parametrize(
    "source,extra,accepted",
    [(None, False, True), ("old request", False, False), (None, True, False)],
)
@pytest.mark.parametrize(
    "message",
    [
        "Take the cold-transfer module out of this design.",
        "I no longer need the cold-transfer module.",
    ],
)
def test_semantic_removal_is_grounded_and_atomic(monkeypatch, source, extra, accepted, message):
    project = apply_cold_transfer(plate_project())
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def model(*args):
        return ExtractedTurn(
            assistant_message="Synthetic response",
            actions=[ChatAction(kind="remove_cold_transfer", source=source or message)],
            workspace_width_mm=1300 if extra else None,
            source_workspace_width_mm=message if extra else None,
        ), {}

    monkeypatch.setattr(api, "generate_turn", model)
    response = post_message(project["id"], message)
    assert response.status_code == 200, response.text
    body = response.json()
    assert bool(body["project"].get("cold_transfer_extension")) is not accepted
    if not accepted:
        assert body["project"] == original


@pytest.mark.parametrize(
    "installed,message,kind",
    [
        (False, "Move the plate from the refrigerator to the deck", "add_cold_transfer"),
        (True, "Remove just the lid from the refrigerator transfer cell", "remove_cold_transfer"),
    ],
)
def test_wrong_model_direction_or_partial_scope_never_changes_module(
    monkeypatch, installed, message, kind
):
    project = plate_project()
    if installed:
        project = apply_cold_transfer(project)
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    calls = []

    async def model(*args):
        calls.append(True)
        return ExtractedTurn(
            assistant_message="Synthetic mistaken classifier",
            actions=[
                ChatAction(
                    kind=kind,
                    source=message,
                    cold_transfer=ColdTransferGrounding(
                        payload="selected_rigid_plate",
                        destination="dedicated_refrigerated",
                        payload_source="plate" if not installed else "lid",
                        destination_source="refrigerator",
                    ),
                )
            ],
        ), {}

    monkeypatch.setattr(api, "generate_turn", model)
    body = post_message(project["id"], message).json()
    assert calls == [True]
    assert body["project"] == original


@pytest.mark.parametrize(
    "failure_kind,changed",
    [
        ("provider_unavailable", True),
        ("source_validation", False),
        ("refusal", False),
    ],
)
def test_offline_fallback_requires_actual_provider_unavailability(
    monkeypatch, failure_kind, changed
):
    from app.model_client import ModelClientError

    project = plate_project()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def unavailable(*args):
        raise ModelClientError("Synthetic failure", failure_kind=failure_kind)

    monkeypatch.setattr(api, "generate_turn", unavailable)
    session = api._sessions[project["id"]]
    response = post_message(
        project["id"], "Add a gripper to transfer the prepared plate to a dedicated refrigerator"
    )
    assert response.status_code == (200 if changed else 502)
    assert bool(session.project.get("cold_transfer_extension")) is changed
    if not changed:
        assert session.project == original
