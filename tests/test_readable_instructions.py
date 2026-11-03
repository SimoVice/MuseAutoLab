"""Readable presentation keeps canonical identities and download paths intact."""

import json
import re
from copy import deepcopy
from html.parser import HTMLParser

from test_foundation_storage import source_project
from test_microplates import before, select

from app.instructions import build_instruction_files, build_instruction_guide, readable_text


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)


def test_names_replace_codes_in_prose_without_rewriting_download_paths_or_matching_substrings():
    names = {"sample-rack": "Sample holder", "base": "Deck insert"}
    assert readable_text("sample-rack: review fit", names) == "Sample holder: review fit"
    assert readable_text("base: center [0, 2, 3] mm", names).startswith("Deck insert:")
    text = "Download cad/sample-rack.stl; preserve longer-sample-rack-name and sample-rack."
    # Terminal punctuation is preserved; actual filenames are not presentation labels.
    assert readable_text(text, names).startswith("Download cad/sample-rack.stl;")
    assert "longer-sample-rack-name" in readable_text(text, names)
    assert readable_text(text, names).endswith("and Sample holder.")


def test_liquid_guide_uses_human_names_and_preserves_machine_readable_source_fields():
    project = source_project()
    original = deepcopy(project)
    guide = build_instruction_guide(project)
    files = build_instruction_files(project)
    parser = VisibleText()
    parser.feed(files["assembly-guide.html"].decode())
    visible = " ".join(parser.text)
    assert not re.search(r"(?<![\w./-])foundation-jubilee(?![\w./-])", visible)
    assert not re.search(r"(?<![\w./-])source-cad(?![\w./-])", visible)
    assert "Review this revision and selected configuration" in visible
    assert "Software & protocols" in visible
    exported = json.loads(files["assembly.json"])
    assert exported["parts"][0]["component_id"] == guide["parts"][0]["component_id"]
    assert exported["steps"] == guide["steps"]
    assert project == original


def test_plate_file_paths_remain_usable_and_profile_code_is_not_visible():
    project = select(before())
    files = build_instruction_files(project)
    parser = VisibleText()
    parser.feed(files["assembly-guide.html"].decode())
    visible = " ".join(parser.text)
    assert "cad/plate-holder.stl" in visible
    assert "cad/plate-reference.step" in visible
    assert project["labware_plate"]["profile_id"] not in visible
