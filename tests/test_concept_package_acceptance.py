"""Accepted project entrypoints and downloaded standalone software, without inference."""

import asyncio
import io
import json
import subprocess
import sys
import zipfile
from copy import deepcopy
from urllib.parse import unquote, urlsplit

import httpx
from test_concept_guide import Links
from test_concept_guide import gateway as gateway
from test_custom_project_routes import client as client
from test_custom_project_routes import install, project_fixture, proposal

import app.api as api
import app.concept_agent as agent
from app.model_client import ExtractedTurn


def download_bundle(client, url, revision, folder):
    response = client.get(url + "/concept/package.zip", params={"revision": revision})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            path = folder / name
            assert path.resolve().is_relative_to(folder.resolve())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
    data = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert data["revision"] == revision
    parser = Links()
    parser.feed((folder / "guide.html").read_text(encoding="utf-8"))
    for link in parser.links:
        if link.startswith("./"):
            assert (folder / unquote(urlsplit(link).path)).is_file(), link
    return data


def test_chat_creation_revision_download_reopen_and_workflow_boundary(
    client, monkeypatch, tmp_path
):
    calls = []

    async def model_turn(project, message, history):
        calls.append(message)
        if message == "Use a 590 mm bench.":
            return ExtractedTurn(
                assistant_message="Review the narrower bench.", workspace_width_mm=590
            ), {}
        if message == "Replace this with a liquid-handling project.":
            return ExtractedTurn(
                assistant_message="Consider liquid handling.", workflow_kind="liquid_preparation"
            ), {}
        return ExtractedTurn(
            assistant_message="Developing the tray mechanism.",
            workflow_kind="general",
            brief_objective="Photograph trays.",
            brief_process="Slide trays to a camera.",
            actions=[{"kind": "develop_concept", "source": message}],
        ), {}

    async def design_reply(*args, **kwargs):
        return {"proposal": proposal(), "question": None}, {"total_tokens": 1}

    monkeypatch.setattr(api, "generate_turn", model_turn)
    monkeypatch.setattr(agent, "request_design_proposal", design_reply)
    created = client.post("/api/projects")
    assert created.status_code == 201
    original = created.json()["project"]
    url = "/api/projects/" + original["id"]
    response = client.post(
        url + "/messages",
        json={
            "message": "Design a tray photography mechanism.",
            "project_revision": original["revision"],
        },
    )
    assert response.status_code == 200, response.text
    accepted = response.json()["project"]
    assert accepted["concept_design"]["title"] == proposal()["title"]
    assert accepted["revision"] > original["revision"]
    data = download_bundle(client, url, accepted["revision"], tmp_path)
    assert data["design"] == accepted["concept_design"]
    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "controller.py"),
            str(tmp_path / "project.json"),
            "--simulate",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["mode"] == "simulation"
    changed = client.post(
        url + "/messages",
        json={"message": "Use a 590 mm bench.", "project_revision": accepted["revision"]},
    )
    assert changed.status_code == 200, changed.text
    current = changed.json()["project"]
    assert current["revision"] > accepted["revision"]
    assert (
        client.get(
            url + "/concept/project.json", params={"revision": accepted["revision"]}
        ).status_code
        == 409
    )
    count = len(calls)
    assert (
        client.post(
            url + "/messages",
            json={
                "message": "Design a tray photography mechanism.",
                "project_revision": accepted["revision"],
            },
        ).status_code
        == 409
    )
    assert len(calls) == count
    blocked = client.post(
        url + "/messages",
        json={
            "message": "Replace this with a liquid-handling project.",
            "project_revision": current["revision"],
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["project"] == current
    assert "new project" in blocked.json()["assistant_message"]
    saved = client.get(url + "/snapshot", params={"revision": current["revision"]})
    assert saved.status_code == 200
    reopened = client.post("/api/projects/open", content=saved.content)
    assert reopened.status_code == 201, reopened.text
    restored = reopened.json()["project"]
    assert restored["id"] != current["id"]
    assert restored["concept_design"] == current["concept_design"]
    assert restored["revision"] == current["revision"]


def test_two_clients_cannot_publish_over_a_changed_revision(monkeypatch):
    project = project_fixture()
    url = install(project)
    calls = []

    async def turn(*args, **kwargs):
        calls.append(args[1])
        await asyncio.sleep(0.02)
        return ExtractedTurn(
            assistant_message="Review the changed bench width.", workspace_width_mm=590
        ), {}

    monkeypatch.setattr(api, "generate_turn", turn)

    async def requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://testserver"
        ) as first:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api.app), base_url="http://testserver"
            ) as second:
                payload = {
                    "message": "Use a 590 mm bench.",
                    "project_revision": project["revision"],
                }
                return await asyncio.gather(
                    first.post(url + "/messages", json=payload),
                    second.post(url + "/messages", json=payload),
                )

    responses = asyncio.run(requests())
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(calls) == 1
    accepted = next(
        response.json()["project"] for response in responses if response.status_code == 200
    )
    assert api._sessions[project["id"]].project == accepted
    assert accepted["revision"] == project["revision"] + 1
    api._sessions.pop(project["id"])


def test_actual_downloaded_controller_runs_configured_gateway_cli(client, gateway, tmp_path):
    project = project_fixture()
    url = install(project)
    data = download_bundle(client, url, project["revision"], tmp_path)
    config, records, faults = gateway
    configured = deepcopy(config)
    configured.update(project_id=data["project_id"], revision=data["revision"])
    configured["actions"] = {
        step["name"]: {"action": "test_record_only", "parameters": {"index": index}}
        for index, step in enumerate(data["design"]["steps"])
    }
    path = tmp_path / "reviewed-test-gateway.json"
    path.write_text(json.dumps(configured), encoding="utf-8")
    command = [
        sys.executable,
        str(tmp_path / "controller.py"),
        str(tmp_path / "project.json"),
        "--gateway-config",
        str(path),
        "--arm-hardware",
    ]
    phrase = f"ARM {data['project_id']} r{data['revision']}\n"
    result = subprocess.run(
        command, input=phrase, cwd=tmp_path, capture_output=True, text=True, check=True
    )
    output = json.loads(result.stdout[result.stdout.index("{") :])
    assert output["mode"] == "external_device_adapter"
    assert len(output["events"]) == len(data["design"]["steps"])
    assert [endpoint for endpoint, _ in records] == ["/prepare", "/execute", "/stop"]
    assert records[1][1]["action"] == "test_record_only"
    records.clear()
    faults["/execute"] = {"device_id": "wrong-device"}
    failed = subprocess.run(command, input=phrase, cwd=tmp_path, capture_output=True, text=True)
    assert failed.returncode == 2
    assert "acknowledgement" in failed.stderr
    assert [endpoint for endpoint, _ in records] == ["/prepare", "/execute", "/stop"]
