"""Focused checks for engineer-style platform discovery."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.engineering import (
    EngineeringOption,
    EngineeringRequirement,
    EngineeringUpdate,
    apply_engineering_update,
    state_for,
)


def project_with_options(ids=("jubilee", "opentrons-ot2")):
    options = [
        {"platform_id": pid, "reason": f"Reason for {pid}.", "tradeoffs": ["Tradeoff one."]}
        for pid in ids
    ]
    return {
        "id": "project-1",
        "revision": 3,
        "status": "confirmed",
        "engineering": {
            "schema_version": "1",
            "requirements": {
                "procurement": None,
                "budget": None,
                "throughput": None,
                "assembly": None,
                "priorities": None,
            },
            "options": options,
            "selected_platform_id": None,
            "selection_source": None,
        },
    }


def requirement(field, value, source):
    return EngineeringRequirement(field=field, value=value, source=source)


def test_state_for_defaults_and_ignores_source_cad():
    assert state_for({})["selected_platform_id"] is None
    project = project_with_options()
    project["design"] = {"foundation": {"id": "jubilee-v2.2.2-c877bd2"}}
    assert state_for(project)["selected_platform_id"] is None
    assert state_for(project)["requirements"].keys() == {
        "procurement",
        "budget",
        "throughput",
        "assembly",
        "priorities",
    }


def test_state_for_recovers_from_invalid_saved_state():
    project = {"engineering": {"requirements": {"budget": "x"}}}
    state = state_for(project)
    assert state["selected_platform_id"] is None and state["options"] == []


def test_staged_options_replace_only_when_nonempty():
    project = project_with_options()
    before = deepcopy(project)
    message = "Our budget is about 5000 EUR for the build."
    update = EngineeringUpdate(
        requirements=[requirement("budget", "about 5000 EUR", "budget is about 5000 EUR")],
    )
    result = apply_engineering_update(project, update, message)
    assert project == before
    assert result["revision"] == 4 and result["status"] == "draft"
    assert result["engineering"]["requirements"]["budget"] == "about 5000 EUR"
    assert [o["platform_id"] for o in result["engineering"]["options"]] == [
        "jubilee",
        "opentrons-ot2",
    ]
    assert result["engineering"]["selected_platform_id"] is None


def test_requirements_alone_never_select_platform():
    project = project_with_options()
    message = "We want the prebuilt route with 5000 EUR budget."
    update = EngineeringUpdate(
        requirements=[
            EngineeringRequirement(field="procurement", value="prebuilt", source="prebuilt route")
        ],
    )
    result = apply_engineering_update(project, update, message)
    assert result["engineering"]["requirements"]["procurement"] == "prebuilt"
    assert result["engineering"]["selected_platform_id"] is None


def test_literal_procurement_alias_repairs_format_without_selecting():
    literal = "buildable open-hardware route"
    update = EngineeringUpdate(requirements=[
        EngineeringRequirement(field="procurement", value=literal, source=literal)
    ])
    result = apply_engineering_update(project_with_options(), update, f"I prefer the {literal}.")
    assert result["engineering"]["requirements"]["procurement"] == "open_hardware"
    assert result["engineering"]["selected_platform_id"] is None
    with pytest.raises(ValueError):
        apply_engineering_update(project_with_options(), update, "Unrelated latest message")


@pytest.mark.parametrize("literal", ["something buildable", "not open-hardware", "invented route"])
def test_procurement_aliases_do_not_guess_arbitrary_or_negated_values(literal):
    update = EngineeringUpdate(requirements=[
        EngineeringRequirement(field="procurement", value=literal, source=literal)
    ])
    with pytest.raises(ValueError):
        apply_engineering_update(project_with_options(), update, literal)


def test_explicit_direct_choice_selects_jubilee():
    project = project_with_options()
    message = "Let's go with Jubilee for the build."
    update = EngineeringUpdate(platform_choice="jubilee", choice_source="go with Jubilee")
    result = apply_engineering_update(project, update, message)
    assert result["engineering"]["selected_platform_id"] == "jubilee"
    assert result["engineering"]["selection_source"] == "go with Jubilee"


def test_italian_prebuilt_route_choice():
    project = project_with_options(ids=("jubilee",))
    message = "Preferisco quella già assemblata, confermo la prima opzione."
    update = EngineeringUpdate(
        platform_choice="opentrons-ot2", choice_source="quella già assemblata"
    )
    # Single staged jubilee option cannot satisfy a prebuilt route request.
    with pytest.raises(ValueError):
        apply_engineering_update(project, update, message)
    single_prebuilt = project_with_options(ids=("opentrons-ot2",))
    ok = apply_engineering_update(single_prebuilt, update, message)
    assert ok["engineering"]["selected_platform_id"] == "opentrons-ot2"


def test_first_second_option_resolution():
    project = project_with_options()
    first = apply_engineering_update(
        project,
        EngineeringUpdate(platform_choice="jubilee", choice_source="first option"),
        "I will take the first option.",
    )
    assert first["engineering"]["selected_platform_id"] == "jubilee"
    second = apply_engineering_update(
        project,
        EngineeringUpdate(platform_choice="opentrons-ot2", choice_source="second option"),
        "I will take the second option.",
    )
    assert second["engineering"]["selected_platform_id"] == "opentrons-ot2"


def test_single_option_yes_confirms_but_two_option_yes_is_ambiguous():
    single = project_with_options(ids=("jubilee",))
    confirmed = apply_engineering_update(
        single,
        EngineeringUpdate(platform_choice="jubilee", choice_source="Yes"),
        "Yes, proceed with it.",
    )
    assert confirmed["engineering"]["selected_platform_id"] == "jubilee"
    two = project_with_options()
    with pytest.raises(ValueError):
        apply_engineering_update(
            two,
            EngineeringUpdate(platform_choice="jubilee", choice_source="Yes"),
            "Yes, proceed with it.",
        )


def test_noop_preserves_revision_and_design_artefacts():
    project = project_with_options()
    project["engineering_design"] = {"schema_version": "1"}
    project["geometry"] = {"key": "value"}
    message = "Our budget is about 5000 EUR for the build."
    update = EngineeringUpdate(
        requirements=[requirement("budget", "about 5000 EUR", "budget is about 5000 EUR")],
    )
    once = apply_engineering_update(project, update, message)
    again = apply_engineering_update(once, update, message)
    assert again == once
    assert again["revision"] == once["revision"]
    assert again["engineering_design"] == {"schema_version": "1"}
    assert again["geometry"] == {"key": "value"}


def test_bump_false_leaves_revision_but_marks_draft():
    project = project_with_options()
    project["status"] = "confirmed"
    message = "Our budget is about 5000 EUR for the build."
    update = EngineeringUpdate(
        requirements=[requirement("budget", "about 5000 EUR", "budget is about 5000 EUR")],
    )
    result = apply_engineering_update(project, update, message, bump=False)
    assert result["revision"] == project["revision"]
    assert result["status"] == "draft"


def test_source_failures_duplicates_and_unsupported():
    project = project_with_options()
    message = "Budget is about 5000 EUR."
    dup = EngineeringUpdate(
        requirements=[
            requirement("budget", "5000 EUR", "Budget is about 5000 EUR"),
            requirement("budget", "5000 EUR", "Budget is about 5000 EUR"),
        ]
    )
    with pytest.raises(ValueError):
        apply_engineering_update(project, dup, message)
    absent = EngineeringUpdate(
        requirements=[requirement("budget", "5000 EUR", "throughput 100/day")]
    )
    with pytest.raises(ValueError):
        apply_engineering_update(project, absent, message)
    ungrounded_value = EngineeringUpdate(
        requirements=[requirement("budget", "9000 EUR", "Budget is about 5000 EUR")]
    )
    with pytest.raises(ValueError):
        apply_engineering_update(project, ungrounded_value, message)


def test_negation_future_and_question_are_not_choices():
    project = project_with_options()
    with pytest.raises(ValueError):
        apply_engineering_update(
            project,
            EngineeringUpdate(platform_choice="jubilee", choice_source="Jubilee"),
            "We will not use Jubilee for now.",
        )
    with pytest.raises(ValueError):
        apply_engineering_update(
            project,
            EngineeringUpdate(platform_choice="jubilee", choice_source="Jubilee"),
            "Maybe later we will consider Jubilee.",
        )
    with pytest.raises(ValueError):
        apply_engineering_update(
            project,
            EngineeringUpdate(platform_choice="jubilee", choice_source="Jubilee"),
            "What is Jubilee and how does it work?",
        )


def test_bounds_and_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        EngineeringOption(platform_id="jubilee", reason="x" * 601, tradeoffs=["ok"])
    with pytest.raises(ValidationError):
        EngineeringOption(platform_id="jubilee", reason="ok", tradeoffs=["t"] * 5)
    empty_choice = EngineeringUpdate(platform_choice=None, choice_source="no choice this turn")
    assert empty_choice.platform_choice is None and empty_choice.choice_source is None
    with pytest.raises(ValidationError):
        EngineeringRequirement(field="budget", value="v", source="v", extra_field="no")
