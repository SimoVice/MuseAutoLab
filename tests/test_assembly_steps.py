from test_design_workflow import hardware
from test_microplates import select

from app.cold_transfer import apply_cold_transfer
from app.instructions import build_instruction_files, build_instruction_guide


def test_checklist_and_downloads_follow_labware_and_added_hardware():
    plate = select(hardware())
    guide = build_instruction_guide(plate)
    titles = [step["title"] for step in guide["assembly_steps"]]
    assert titles[0] == "Assemble the Jubilee frame and motion system"
    assert "Fit the plate and its holder" in titles
    assert not any("refrigerator" in title for title in titles)
    enriched = apply_cold_transfer(plate)
    guide = build_instruction_guide(enriched)
    fridge = next(s for s in guide["assembly_steps"] if "refrigerator" in s["title"])
    assert "empty rigid plate" in " ".join(fridge["instructions"])
    holder = next(s for s in guide["assembly_steps"] if "holder" in s["title"])
    assert any(s["url"].endswith(f"model.step?revision={enriched['revision']}")
               for s in holder["sources"])
    files = build_instruction_files(enriched)
    markdown = files["assembly-guide.md"].decode()
    html = files["assembly-guide.html"].decode()
    for body in (markdown, html):
        assert titles[0] in body and fridge["title"] in body
        assert "Line total" in body
        total = guide["parts_proposal"]["summary"]["total_high_usd"]
        assert f"${total:,.2f}".removesuffix(".00") in body
