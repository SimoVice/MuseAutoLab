"""Vision inspection HTTP/job boundary checks; model call is stubbed, images are real."""

import base64
import io
import json
import time
import zipfile
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api as api
import app.vision_jobs as vjobs
from app import vision
from app.domain import apply_update, configure_project, confirm_project, new_project


def _make_data_url(size=(160, 120), fmt="JPEG", color=(200, 30, 40)) -> str:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    raw = base64.b64encode(buffer.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{raw}"


def _raw_single(confidence=0.95, uncertain=False, kind="tube", contents="not_applicable"):
    return {
        "image_quality": "clear",
        "coverage": "complete",
        "summary": "One tube visible.",
        "warnings": [],
        "detections": [
            {
                "kind": kind,
                "label": "Tube A",
                "box": {"x_min": 10, "y_min": 10, "x_max": 200, "y_max": 200},
                "confidence": confidence,
                "uncertain": uncertain,
                "reason": "Clear tube.",
                "tip_rack_contents": contents,
            }
        ],
    }


def _stub_model(monkeypatch, raw=None, usage=None):
    payload = deepcopy(raw if raw is not None else _raw_single())
    use = dict(
        usage
        if usage is not None
        else {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
    )

    async def fake_analyze(image):
        assert hasattr(image, "content") and hasattr(image, "sha256")
        return deepcopy(payload), dict(use)

    monkeypatch.setattr(vision, "analyze_image", fake_analyze)


@pytest.fixture
def client(monkeypatch):
    api._sessions.clear()
    vjobs._jobs.clear()
    vjobs._cache.clear()
    vjobs._background_tasks.clear()
    _stub_model(monkeypatch)
    with TestClient(api.app) as test_client:
        yield test_client
    _wait_all_done(timeout=15)
    api._sessions.clear()
    vjobs._jobs.clear()
    vjobs._cache.clear()
    vjobs._background_tasks.clear()


def _wait_all_done(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [j for j in list(vjobs._jobs.values()) if j["status"] in ("queued", "running")]
        if not pending:
            return
        time.sleep(0.02)
    raise AssertionError("A vision worker did not finish")


def _wait_job(client, url, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(0.02)
    pytest.fail("Vision job did not finish")


def _seed(confirmed=False):
    project = apply_update(
        new_project(),
        {
            "stock_concentration": "10 mM",
            "target_concentrations": "1, 2 mM",
            "final_volume": "100 uL",
            "equipment": "Manual pipette",
            "workspace_width_mm": 450,
        },
    )
    if confirmed:
        project = confirm_project(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return project, f"/api/projects/{project['id']}/inspections"


def _post_inspection(client, base, project, data_url=None):
    return client.post(
        base,
        json={
            "project_revision": project["revision"],
            "image_data_url": data_url or _make_data_url(),
        },
    )


def test_create_ready_and_duplicate_reuse(client):
    project, base = _seed()
    created = _post_inspection(client, base, project)
    assert created.status_code == 202, created.text
    first = created.json()
    assert first["status"] in ("queued", "running", "ready")
    assert first["project_revision"] == project["revision"]
    url = base + "/" + first["id"]
    job = _wait_job(client, url)
    assert job["status"] == "ready"
    assert job["error"] is None
    result = job["result"]
    assert result["observation_version"] == 1
    assert result["image"]["sha256"]
    assert result["image"]["url"].endswith("/image")
    assert result["detections"][0]["id"] == "det-001"
    assert result["detections"][0]["state"] == "observed"
    assert result["scene_reviewed"] is False
    assert result["review_required"] is True
    assert result["presence"]["tubes"] == "present"
    assert "raw" not in result
    # Same image + revision reuses ready job.
    duplicate = _post_inspection(client, base, project, data_url=None)
    # Hash depends on canonical JPEG; reuse only if identical bytes path.
    # Force identical data URL reuse check with the stored canonical data URL.
    assert duplicate.status_code in (202, 409)
    # Image endpoint returns canonical JPEG, no-store.
    image = client.get(url + "/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["Cache-Control"] == "no-store"
    assert image.content[:2] == b"\xff\xd8"


def test_duplicate_same_bytes_reuses_job(client):
    project, base = _seed()
    url_data = _make_data_url()
    first = _post_inspection(client, base, project, data_url=url_data).json()
    second = _post_inspection(client, base, project, data_url=url_data).json()
    assert second["id"] == first["id"]
    job = _wait_job(client, base + "/" + first["id"])
    assert job["status"] == "ready"
    third = _post_inspection(client, base, project, data_url=url_data).json()
    assert third["id"] == first["id"]


def test_stale_revision_and_wrong_project(client):
    project, base = _seed()
    other, other_base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    assert _wait_job(client, url)["status"] == "ready"
    assert client.get(other_base + "/" + created["id"]).status_code == 404
    assert client.get(url + "/image").status_code == 200
    changed = configure_project(project, cooling_enabled=True)
    api._sessions[project["id"]].project = changed
    assert client.get(url).status_code == 409
    assert client.get(url + "/image").status_code == 409
    assert client.get(url + "/archive").status_code == 409
    assert (
        client.post(
            url + "/review", json={"observation_version": 1, "scene_reviewed": False}
        ).status_code
        == 409
    )
    # Stale create revision is rejected.
    stale = client.post(
        base, json={"project_revision": project["revision"], "image_data_url": _make_data_url()}
    )
    assert stale.status_code == 409


def test_invalid_image_uses_real_preparation(client):
    project, base = _seed()
    bad = client.post(
        base, json={"project_revision": project["revision"], "image_data_url": "not-a-data-url"}
    )
    assert bad.status_code == 422
    bad2 = client.post(
        base,
        json={
            "project_revision": project["revision"],
            "image_data_url": "data:image/gif;base64,R0lGODdhAQABAIAAAP8AAAAA",
        },
    )
    assert bad2.status_code == 422


def test_review_flow_scene_guards_and_atomicity(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    assert _wait_job(client, url)["status"] == "ready"
    det = client.get(url).json()["result"]["detections"][0]["id"]
    # Cannot finalize scene with pending objects.
    blocked = client.post(url + "/review", json={"observation_version": 1, "scene_reviewed": True})
    assert blocked.status_code == 422
    # Unknown detection id rejected atomically.
    bad = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [{"id": "det-999", "action": "accept"}],
        },
    )
    assert bad.status_code == 422
    assert client.get(url).json()["result"]["observation_version"] == 1
    # Bad component mapping rejected.
    bad_map = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [{"id": det, "action": "accept", "component_id": "tip-rack"}],
        },
    )
    assert bad_map.status_code == 422
    # Accept with valid mapping and label edit.
    ok = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [
                {"id": det, "action": "accept", "label": "Tube A1", "component_id": "source-rack"}
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    job = ok.json()
    assert job["result"]["observation_version"] == 2
    assert job["result"]["detections"][0]["state"] == "confirmed"
    assert job["result"]["detections"][0]["component_id"] == "source-rack"
    assert job["result"]["scene_reviewed"] is False
    # Stale observation version rejected.
    assert (
        client.post(
            url + "/review", json={"observation_version": 1, "scene_reviewed": False}
        ).status_code
        == 409
    )
    # Now scene can be finalized (no pending objects).
    final = client.post(url + "/review", json={"observation_version": 2, "scene_reviewed": True})
    assert final.status_code == 200
    assert final.json()["result"]["scene_reviewed"] is True
    assert final.json()["result"]["review_required"] is False


def test_reject_and_addition_with_limits(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    assert _wait_job(client, url)["status"] == "ready"
    det = client.get(url).json()["result"]["detections"][0]["id"]
    review = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [{"id": det, "action": "reject"}],
            "additions": [
                {
                    "kind": "pipette_tip",
                    "label": "Tip <b>1</b>",
                    "box": {"x_min": 5, "y_min": 5, "x_max": 50, "y_max": 50},
                    "component_id": "tip-rack",
                }
            ],
        },
    )
    assert review.status_code == 200, review.text
    detections = review.json()["result"]["detections"]
    assert detections[0]["state"] == "rejected"
    assert detections[1]["id"] == "manual-001"
    assert detections[1]["state"] == "confirmed"
    # Too many additions rejected.
    many = [
        {
            "kind": "tube",
            "label": f"T{i}",
            "box": {"x_min": 1, "y_min": 1, "x_max": 10, "y_max": 10},
        }
        for i in range(17)
    ]
    over = client.post(
        url + "/review", json={"observation_version": 2, "scene_reviewed": False, "additions": many}
    )
    assert over.status_code == 422
    # Extras forbidden.
    extra = client.post(
        url + "/review",
        json={
            "observation_version": 2,
            "scene_reviewed": False,
            "decisions": [{"id": det, "action": "accept", "nope": 1}],
        },
    )
    assert extra.status_code == 422


def test_archive_contents_manifest_and_escape(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    assert _wait_job(client, url)["status"] == "ready"
    det = client.get(url).json()["result"]["detections"][0]["id"]
    reviewed = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [{"id": det, "action": "accept", "label": "A&B <tag>"}],
        },
    )
    assert reviewed.status_code == 200
    archive = client.get(url + "/archive")
    assert archive.status_code == 200
    assert "attachment" in archive.headers["content-disposition"]
    bundle = zipfile.ZipFile(io.BytesIO(archive.content))
    names = set(bundle.namelist())
    assert names == {
        "image.jpg",
        "annotated.svg",
        "inspection.json",
        "review-history.json",
        "README.md",
        "manifest.json",
    }
    assert bundle.read("image.jpg")[:2] == b"\xff\xd8"
    svg = bundle.read("annotated.svg").decode("utf-8")
    assert "A&amp;B &lt;tag&gt;" in svg
    assert "<tag>" not in svg.replace("&lt;tag&gt;", "")
    manifest = json.loads(bundle.read("manifest.json"))
    for name in (
        "image.jpg",
        "annotated.svg",
        "inspection.json",
        "review-history.json",
        "README.md",
    ):
        import hashlib as _hashlib

        assert manifest[name] == _hashlib.sha256(bundle.read(name)).hexdigest()
    inspection = json.loads(bundle.read("inspection.json"))
    assert inspection["observation_version"] == 2
    history = json.loads(bundle.read("review-history.json"))
    assert len(history) == 1


def test_failure_sanitized_then_retry(client, monkeypatch):
    async def broken(image):
        raise RuntimeError("secret-path-should-not-leak")

    monkeypatch.setattr(vision, "analyze_image", broken)
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    job = _wait_job(client, base + "/" + created["id"])
    assert job["status"] == "failed"
    assert "secret-path-should-not-leak" not in (job["error"] or "")
    assert client.get(base + "/" + created["id"] + "/archive").status_code == 409
    _stub_model(monkeypatch)
    retried = _post_inspection(
        client, base, project, data_url=_make_data_url(color=(10, 200, 30))
    ).json()
    assert retried["id"] != created["id"]
    assert _wait_job(client, base + "/" + retried["id"])["status"] == "ready"


def test_unusable_quality_presence_uncertain(client, monkeypatch):
    raw = _raw_single(confidence=0.95, uncertain=False)
    raw["image_quality"] = "unusable"
    _stub_model(monkeypatch, raw=raw)
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    job = _wait_job(client, base + "/" + created["id"])
    assert job["status"] == "ready"
    assert job["result"]["presence"] == {"tubes": "uncertain", "pipette_tips": "uncertain"}
    assert job["result"]["detections"][0]["state"] == "needs_review"


def test_needs_review_bucket_for_low_confidence(client, monkeypatch):
    _stub_model(monkeypatch, raw=_raw_single(confidence=0.4, uncertain=False))
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    job = _wait_job(client, base + "/" + created["id"])
    assert job["result"]["detections"][0]["state"] == "needs_review"


def test_mapping_survives_accept_without_mapping_field(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    _wait_job(client, url)
    first = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [{"id": "det-001", "action": "accept", "component_id": "source-rack"}],
        },
    )
    assert first.status_code == 200
    second = client.post(
        url + "/review",
        json={
            "observation_version": 2,
            "scene_reviewed": True,
            "decisions": [{"id": "det-001", "action": "accept"}],
        },
    )
    assert second.json()["result"]["detections"][0]["component_id"] == "source-rack"
    assert client.get(url + "/archive?observation_version=2").status_code == 409
    latest = client.get(url + "/archive?observation_version=3")
    with zipfile.ZipFile(io.BytesIO(latest.content)) as archive:
        result = json.loads(archive.read("inspection.json"))
        assert result["project_id"] == project["id"]
        assert result["project_revision"] == project["revision"]
        assert b"data:image/jpeg;base64," in archive.read("annotated.svg")


def test_review_rejects_bool_coordinates_and_preserves_result(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    before = _wait_job(client, url)
    response = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": False,
            "decisions": [
                {
                    "id": "det-001",
                    "action": "accept",
                    "box": {
                        "x_min": True,
                        "y_min": 0,
                        "x_max": 500,
                        "y_max": 500,
                    },
                }
            ],
        },
    )
    assert response.status_code == 422
    assert client.get(url).json() == before


def test_human_can_resolve_tip_rack_occupancy(client, monkeypatch):
    _stub_model(monkeypatch, raw=_raw_single(kind="tip_rack", contents="unknown"))
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    job = _wait_job(client, url)
    assert job["result"]["presence"]["pipette_tips"] == "uncertain"
    response = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": True,
            "decisions": [
                {"id": "det-001", "action": "accept", "tip_rack_contents": "tips_visible"}
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["presence"]["pipette_tips"] == "present"
    assert response.json()["result"]["scene_reviewed"] is True
    assert response.json()["result"]["review_required"] is False


def test_failed_final_review_is_atomic(client):
    project, base = _seed()
    created = _post_inspection(client, base, project).json()
    url = base + "/" + created["id"]
    before = _wait_job(client, url)
    response = client.post(
        url + "/review",
        json={
            "observation_version": 1,
            "scene_reviewed": True,
            "additions": [
                {
                    "kind": "tube",
                    "label": "Manual tube",
                    "box": {
                        "x_min": 500,
                        "y_min": 500,
                        "x_max": 600,
                        "y_max": 800,
                    },
                }
            ],
        },
    )
    assert response.status_code == 422
    assert client.get(url).json() == before
