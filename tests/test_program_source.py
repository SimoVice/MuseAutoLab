"""The displayed Python program is the executable source for this approved revision."""

import subprocess
import sys

from fastapi.testclient import TestClient
from test_design_workflow import hardware
from test_microplates import select

import app.api as api


def test_program_tracks_the_bound_plate_and_runs_offline(tmp_path):
    project = select(hardware())
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    base = "/api/projects/" + project["id"]
    client = TestClient(api.app)

    def program(revision):
        return client.get(base + "/instructions/download",
                          params={"format": "program", "revision": revision})

    assert program(project["revision"]).status_code == 409
    approved = client.post(base + "/approve-machine", json={
        "project_revision": project["revision"]
    }).json()["project"]
    assert program(approved["revision"]).status_code == 409
    recipe = client.post(base + "/program-recipe", json={
        "project_revision": approved["revision"], "stock_concentration": "5 mg/mL",
        "target_concentrations": "0.5 and 0.25 mg/mL", "final_volume": "200 uL",
    }).json()["project"]
    assert program(approved["revision"]).status_code == 409
    response = program(recipe["revision"])
    assert response.status_code == 200 and 'filename="program.py"' in response.headers[
        "Content-Disposition"]
    path = tmp_path / "program.py"
    path.write_bytes(response.content)
    result = subprocess.run([sys.executable, "-I", str(path)], cwd=tmp_path, check=True,
                            capture_output=True, text=True)
    assert "Transfer 20 uL from stock to A1" in result.stdout
    assert "Transfer 190 uL from diluent to B1" in result.stdout
    assert "B1: 200 uL total at planned 0.25 mg/mL" in result.stdout
    assert "Pick up tip 4 and aspirate 190 uL from diluent" in result.stdout
    assert "Total stock 30 uL, diluent 370 uL, 4 tips" in result.stdout
