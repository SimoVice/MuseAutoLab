"""Canonical guide coherence and immediate generation, without CAD or providers."""

import asyncio
import json
from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from test_commercial_design import proposal as ot2_proposal
from test_foundation_storage import source_project

from app.assembly import assembly_steps, build_document_files
from app.commercial_design import adopt_commercial, compile_commercial_layout
from app.domain import apply_update, confirm_project
from app.foundation_design import compile_source_layout
from app.inspection import apply_extension, clear_extension
from app.instructions import build_instruction_files, build_instruction_guide


def report_for(project):
    return {
        "report_id": "quote-one",
        "project_id": project["id"],
        "project_revision": project["revision"],
        "market": "US",
        "currency": "USD",
        "fetched_at": "2026-10-30T12:00:00Z",
        "rows": [
            {
                "group_id": "platform",
                "component_ids": ["foundation-jubilee"],
                "label": "Current platform offer",
                "selected_id": "source-cad",
                "quantity": 1,
                "unit_price": 1200,
                "line_total": 1200,
                "status": "priced",
                "freshness": "fresh",
                "availability": "In stock",
                "price_source_url": "https://example.com/quote",
                "fetched_at": "2026-10-30T12:00:00Z",
            }
        ],
        "known_partial_subtotal": 1200,
        "exclusions": ["Custom interfaces", "Tax and shipping"],
    }


def test_source_guide_keeps_geometry_variants_pose_and_upstream_separate():
    project = source_project(125)
    original = deepcopy(project)
    guide = build_instruction_guide(project)
    assert project == original
    assert guide["platform"] == "jubilee" and guide["bed_pose"]["bed_drop_mm"] == 125
    canonical = {p["id"]: p for p in project["design"]["components"]}
    for step in guide["steps"]:
        assert set(step["component_ids"]) <= canonical.keys()
        for part in step["parts"]:
            assert part["position_mm"] == canonical[part["component_id"]]["position"]
            assert part["size_mm"] == canonical[part["component_id"]]["size"]
        assert all(
            isinstance(item["acceptance_criteria"], str) for item in step["engineering_tasks"]
        )
    frame = next(step for step in guide["steps"] if step["id"] == "frame")
    upstream = next(step for step in guide["steps"] if step["id"] == "upstream-frame")
    assert frame["status"] == "needs_design" and frame["engineering_tasks"]
    assert upstream["status"] == "reference_only"
    assert "foundation-jubilee" in frame["component_ids"]
    assert (
        next(p for p in guide["parts"] if p["component_id"] == "foundation-jubilee")[
            "selected_variants"
        ][0]["variant_id"]
        == "source-cad"
    )
    assert any(
        "c877bd2e889560c83da2a68479641a4f7f0d9b83" in source["url"] for source in guide["sources"]
    )
    assert any(
        source["url"].endswith("instructions/outer_frame.html") for source in upstream["sources"]
    )
    assert not any(step["required_materials"] for step in guide["steps"])
    assert not any(step["required_tools"] for step in guide["steps"])


def test_ot2_guide_preserves_slots_and_uses_official_setup_not_custom_frame():
    project = compile_commercial_layout(adopt_commercial(layout_project()), ot2_proposal(), {})
    guide = build_instruction_guide(project)
    assert guide["platform"] == "opentrons-ot2"
    assert "frame" not in {step["id"] for step in guide["steps"]}
    racks = next(step for step in guide["steps"] if step["id"] == "racks")
    assert {p["component_id"]: p["slot_id"] for p in racks["parts"]} == {
        "source-rack": "1",
        "sample-rack": "5",
        "tip-rack": "11",
        "tip-waste": "12",
    }
    assert any("installation/instruments/" in source["url"] for source in guide["sources"])
    assert any(step["required_tools"] for step in guide["steps"])
    assert "inspection-extension" not in {step["id"] for step in guide["steps"]}


def test_optional_modules_follow_actual_accepted_revision():
    project = source_project()
    assert "cold-bay" not in {step["id"] for step in assembly_steps(project)}
    extended = apply_extension(project, inspection_proposal(), {})
    step = next(s for s in assembly_steps(extended) if s["id"] == "inspection-extension")
    assert step["component_ids"] == extended["inspection_extension"]["component_ids"]
    assert "inspection-extension" not in {
        s["id"] for s in assembly_steps(clear_extension(extended))
    }
    cooled = apply_update(project, {"cooling_enabled": True})
    proposal = deepcopy(project["engineering_design"]["proposal"])
    cooled = compile_source_layout(cooled, proposal, {})
    cold = next(s for s in assembly_steps(cooled) if s["id"] == "cold-bay")
    assert cold["component_ids"] == ["cold-storage"]
    assert cooled["design"]["cooling"]["variant_id"] in " ".join(cold["instructions"])


def test_immediate_files_match_package_and_do_not_need_confirmation_or_cad(monkeypatch):
    import app.cad_exports

    monkeypatch.setattr(
        app.cad_exports, "build_cad_files", lambda _: pytest.fail("No CAD call expected")
    )
    project = source_project()
    assert project["status"] == "draft"
    immediate = build_instruction_files(project)
    packaged = build_document_files(project)
    assert set(immediate) == {"assembly-guide.html", "assembly-guide.md", "assembly.json"}
    assert all(packaged[name] == payload for name, payload in immediate.items())
    guide = json.loads(immediate["assembly.json"])
    assert guide["steps"] == assembly_steps(project)
    edited = apply_update(project, {"final_volume": "200 uL"})
    assert (
        build_instruction_guide(edited)["project_revision"]
        == edited["revision"]
        > guide["project_revision"]
    )


def test_bound_procurement_preserves_original_and_rejects_stale_report():
    project = source_project()
    report = report_for(project)
    report["rows"][0].update(
        is_candidate=True,
        compatibility_note="Check kit revision before purchase.",
        source_bom_url="https://example.com/bom",
        source_bom_row=22,
        source_project_revision="pinned-fixture",
    )
    original = deepcopy(project)
    guide = build_instruction_guide(project, report)
    assert guide["procurement_report_id"] == "quote-one" and guide["procurement"] == report
    assert project == original
    files = build_instruction_files(project, report)
    assert b"1200" in files["assembly-guide.html"]
    assert b"quote-one" in files["assembly-guide.md"]
    assert b"Candidate offer; not adopted" in files["assembly-guide.html"]
    assert b"Candidate; not adopted" in files["assembly-guide.md"]
    assert b"Upstream BOM row 22" in files["assembly-guide.html"]
    report["project_revision"] += 1
    with pytest.raises(ValueError, match="does not match"):
        build_instruction_guide(project, report)


def test_html_and_markdown_escape_project_supplied_labels_and_links():
    project = source_project()
    group = project["sourcing"]["groups"][0]
    selected = next(o for o in group["options"] if o["id"] == group["selected_id"])
    selected["label"] = '<script>alert("x")</script>'
    selected["source_url"] = "javascript:alert(1)"
    report = report_for(project)
    report["rows"][0]["label"] = '<img src=x onerror="bad">'
    report["rows"][0]["price_source_url"] = 'https://example.com/?q=" onclick="bad'
    files = build_instruction_files(project, report)
    assert b"<script>" not in files["assembly-guide.html"]
    assert b"&lt;script&gt;" in files["assembly-guide.html"]
    assert b"javascript:" not in files["assembly-guide.html"]
    assert b"<img src=x" not in files["assembly-guide.html"]
    assert b"<script>" not in files["assembly-guide.md"]


def test_export_captures_report_and_refuses_replaced_or_removed_report(monkeypatch):
    import app.project_exports as exports

    exports._jobs.clear()
    monkeypatch.setattr(exports, "build_cad_files", lambda _: {"cad/concept.step": b"fixture CAD"})

    async def run():
        project = confirm_project(source_project())
        project["procurement_report"] = report_for(project)
        original = deepcopy(project)
        created = await exports.start_export(project)
        assert created["procurement_report_id"] == "quote-one"
        await exports._jobs[created["id"]]["task"]
        completed = await exports.export_status(project, created["id"])
        assert completed["status"] == "ready"
        guide = json.loads(await exports.export_file(project, created["id"], "assembly.json"))
        manifest = json.loads(await exports.export_file(project, created["id"], "manifest.json"))
        assert guide["procurement"] == original["procurement_report"]
        assert manifest["procurement_report_id"] == guide["procurement_report_id"] == "quote-one"
        assert project == original
        project["procurement_report"]["rows"][0]["freshness"] = "stale"
        with pytest.raises(exports.ExportError, match="procurement report is stale"):
            await exports.export_status(project, created["id"])
        project["procurement_report"] = deepcopy(original["procurement_report"])
        project["procurement_report"]["report_id"] = "quote-two"
        with pytest.raises(exports.ExportError, match="procurement report is stale"):
            await exports.export_status(project, created["id"])
        replacement = await exports.start_export(project)
        assert replacement["id"] != created["id"]
        await exports._jobs[replacement["id"]]["task"]
        project.pop("procurement_report")
        with pytest.raises(exports.ExportError, match="procurement report is stale"):
            await exports.export_archive(project, replacement["id"])

    try:
        asyncio.run(run())
    finally:
        exports._jobs.clear()
