"""Editable context survives rewind/reopen independently of a machine revision."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient
from test_model_client import TEST_SETTINGS, valid_response

from app import api
from app.domain import new_project
from app.model_client import generate_turn
from app.project_storage import make_snapshot, restore_snapshot


def test_notes_follow_only_their_project_and_preserve_its_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEAUTOLAB_DATABASE_PATH", str(tmp_path / "notes.sqlite3"))
    monkeypatch.delenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", raising=False)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        key = project["id"]
        base = "/api/projects/" + key
        def save(previous, notes):
            return client.put(base + "/notes", json={"previous": previous, "notes": notes})

        assert save("", "Share a single printer.").is_success
        assert save("", "Share a single printer.").is_success
        conflict = save("", "Replace the note from an old browser.")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["notes"] == "Share a single printer."
        assert save("Share a single printer.", "x" * 2401).status_code == 422
        assert client.post(base + "/save", json={"title": "Shared bench", "revision": 0}).is_success
        api._sessions.pop(key)
        reopened = client.post("/api/library/" + key + "/open").json()["project"]
        assert reopened["project_notes"] == "Share a single printer."
        assert reopened["revision"] == project["revision"]
        snapshot = client.get(base + "/snapshot?revision=0").json()
        restored, _ = restore_snapshot(snapshot)
        assert restored["project_notes"] == reopened["project_notes"]
        assert not client.post("/api/projects").json()["project"].get("project_notes")
        assert save("Share a single printer.", "").is_success
        assert "project_notes" not in client.get(base + "/snapshot?revision=0").json()["inputs"]


def test_notes_are_user_context_after_history_rotates():
    project = new_project()
    project["project_notes"] = "Prefer holders that fit a 180 mm print bed."
    history = [{"role": "user", "content": f"Previous turn {n}"} for n in range(12)]
    project, recent = restore_snapshot(make_snapshot(project, history))
    captured = {}
    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=valid_response())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await generate_turn(project, "Tell me about the holder.", recent,
                                client=client, settings=TEST_SETTINGS)
    asyncio.run(run())
    messages = captured["messages"]
    matches = [message for message in messages if project["project_notes"] in message["content"]]
    assert len(matches) == 1 and matches[0]["role"] == "user"
    assert messages[-1]["content"] == "Tell me about the holder."
    assert all("Previous turn 0" not in message["content"] for message in messages)
