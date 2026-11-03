"""Visible chat retention must not expand model or product-choice authorization."""

import json

import httpx
from fastapi.testclient import TestClient
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
from app.conversation_history import DISPLAY_HISTORY_LIMIT, MODEL_HISTORY_LIMIT
from app.domain import new_project
from app.labware_choice import choice_clarification
from app.model_client import ExtractedTurn, generate_turn
from app.project_storage import MAX_SNAPSHOT_BYTES, make_snapshot, restore_snapshot


def test_six_turn_chat_survives_hosted_and_portable_reopen_with_bounded_model_context(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("MUSEAUTOLAB_DATABASE_PATH", str(tmp_path / "projects.sqlite3"))
    monkeypatch.delenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", raising=False)
    monkeypatch.delenv("MUSEAUTOLAB_MODAL_VOLUME_NAME", raising=False)
    api._sessions.clear()
    captured = []

    async def normal_model(project, message, history):
        assert len(history) <= MODEL_HISTORY_LIMIT

        def handler(request):
            captured.append(json.loads(request.content)["messages"])
            return httpx.Response(200, json=valid_response(
                assistant_message="Initial build/buy comparison" if message == "Discuss turn 0"
                else "Contextual explanation " + message))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model_client:
            return await generate_turn(project, message, history, client=model_client,
                                       settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", normal_model)
    try:
        with TestClient(api.app) as client:
            project = client.post("/api/projects").json()["project"]
            project_id = project["id"]
            api._sessions[project_id].project["project_notes"] = "Remember the Rowan station name."
            for index in range(6):
                response = client.post(f"/api/projects/{project_id}/messages", json={
                    "message": f"Discuss turn {index}"})
                assert response.status_code == 200, response.text
            history = api._sessions[project_id].history
            assert len(history) == 12
            assert history[1]["content"] == "Initial build/buy comparison"
            assert not any("Initial build/buy comparison" in item["content"]
                           for item in captured[-1])
            assert any("Remember the Rowan station name." in item["content"]
                       for item in captured[-1])
            saved = client.get(f"/api/projects/{project_id}/snapshot", params={
                "revision": project["revision"]})
            assert saved.status_code == 200
            portable = client.post("/api/projects/open", content=saved.content)
            assert portable.status_code == 201, portable.text
            assert portable.json()["conversation"] == history
            assert client.post(f"/api/projects/{project_id}/save", json={
                "title": "Chat history test", "revision": project["revision"]}).status_code == 200
            api._sessions.clear()
            hosted = client.post(f"/api/library/{project_id}/open")
            assert hosted.status_code == 200, hosted.text
            assert hosted.json()["conversation"] == history
    finally:
        api._sessions.clear()


def test_archive_limit_is_distinct_from_model_window_and_old_snapshots_still_open():
    history = [{"role": "user", "content": f"Turn {index}"}
               for index in range(DISPLAY_HISTORY_LIMIT + 5)]
    snapshot = make_snapshot(new_project(), history)
    assert len(snapshot["history"]) == DISPLAY_HISTORY_LIMIT
    _, restored = restore_snapshot(snapshot)
    assert restored == history[-DISPLAY_HISTORY_LIMIT:]
    snapshot["history"] = snapshot["history"][-MODEL_HISTORY_LIMIT:]
    _, historical = restore_snapshot(snapshot)
    assert historical == history[-MODEL_HISTORY_LIMIT:]


def test_archived_plate_offer_cannot_authorize_a_current_choice():
    history = [{"role": "assistant", "content":
                "I can use the Corning 96-well 360 µL flat-bottom reference."}]
    history += [{"role": "user", "content": f"Unrelated turn {index}"}
                for index in range(MODEL_HISTORY_LIMIT)]
    turn = ExtractedTurn(assistant_message="Using it.", labware_selection={
        "profile_id": "corning_96_wellplate_360ul_flat", "source": "use the Corning one"})
    assert choice_clarification(turn, "use the Corning one", {}, history)



def test_portable_archive_trims_oldest_pairs_to_existing_byte_limit():
    from test_design_workflow import hardware

    project = hardware()
    history = [{"role": "user" if index % 2 == 0 else "assistant",
                "content": f"Turn {index}: " + "λ" * 6000}
               for index in range(DISPLAY_HISTORY_LIMIT)]
    full_machine = make_snapshot(project, [])
    snapshot = make_snapshot(project, history)
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    assert len(raw) <= MAX_SNAPSHOT_BYTES
    assert MODEL_HISTORY_LIMIT <= len(snapshot["history"]) < DISPLAY_HISTORY_LIMIT
    assert len(snapshot["history"]) % 2 == 0
    assert snapshot["history"] == history[-len(snapshot["history"]):]
    saved_machine = {key: value for key, value in snapshot.items()
                     if key not in ("history", "saved_at")}
    assert saved_machine == {key: value for key, value in full_machine.items()
                             if key not in ("history", "saved_at")}
    _, restored = restore_snapshot(snapshot)
    assert restored == snapshot["history"]
    # Adding one more complete old turn would exceed the same limit.
    older = dict(snapshot)
    older["history"] = history[-len(snapshot["history"]) - 2:]
    assert len(json.dumps(older, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_SNAPSHOT_BYTES
