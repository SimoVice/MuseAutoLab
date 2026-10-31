"""Source package scope; the full geometry roundtrip has a separate slow test."""

import asyncio
import json

from foundation_fixtures import liquid_project, source_proposal

import app.project_exports as exports
from app.assembly import build_document_files
from app.design_spec import apply_candidate
from app.domain import confirm_project
from app.foundation_design import adopt_foundation


def test_imported_foundation_has_no_legacy_physics_result(monkeypatch):
    project = confirm_project(
        apply_candidate(adopt_foundation(liquid_project()), source_proposal(), {"model": "offline"})
    )
    # Real CAD export/import is checked in test_foundation_exports. Stub it here
    # to isolate orchestration, documents and the physical-simulation guard.
    async def fixture_cad(_):
        return {"cad/test.txt": b"fixture"}

    monkeypatch.setattr(exports, "_execute_cad", fixture_cad)

    async def run():
        job = await exports.start_export(project)
        await exports._jobs[job["id"]]["task"]
        stored = exports._jobs[job["id"]]
        assert stored["status"] == "ready"
        files = stored["file_bytes"]
        result = json.loads(files["simulation/result.json"])
        assert result["status"] == "not_run"
        assert "simulation/model.xml" not in files and "simulation/run.py" not in files
        assert b"original source assembly" in files["assembly-guide.html"]
        assert b"not_run" in files["README.md"]
        assert b"not this machine's imported CAD" not in files["README.md"]

    try:
        asyncio.run(run())
    finally:
        exports._jobs.clear()


def test_source_documents_and_bom_identify_original_platform_and_custom_interfaces():
    project = apply_candidate(adopt_foundation(liquid_project()), source_proposal(), {})
    groups = {group["id"]: group for group in project["sourcing"]["groups"]}
    assert "upstream-platform" in groups
    assert not {"motors", "drivers", "frame", "controller"}.intersection(groups)
    files = build_document_files(project)
    steps = json.loads(files["assembly.json"])["steps"]
    source_step = next(step for step in steps if step["id"] == "frame")
    assert source_step["component_ids"] == ["foundation-jubilee", "base"]
    assert "unscaled" in " ".join(source_step["instructions"])
