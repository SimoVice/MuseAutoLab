"""Execute explicit conversational design operations against the same project."""

from copy import deepcopy

from app.design_agent import develop_design
from app.domain import confirm_project
from app.engineering import state_for
from app.foundation_design import adopt_foundation, is_source_based
from app.inspection import clear_extension, develop_inspection
from app.model_client import ModelClientError
from app.upstream_cad import foundation_metadata


def _rollback(project: dict, runs: list) -> tuple[dict, list]:
    for run in runs:
        if run["status"] in ("accepted", "ready"):
            run.update(
                status="rejected",
                message="This action was cancelled because another "
                "action in the same request failed. The previous project is preserved.",
            )
    return deepcopy(project), runs


def extension_only_patch(patch: dict, actions: list) -> dict:
    """Mentioning a new camera does not replace the workstation's original equipment."""
    kinds = {a.kind for a in actions}
    if (
        kinds.intersection({"add_inspection", "remove_inspection"})
        and "develop_layout" not in kinds
    ):
        return {
            k: v
            for k, v in patch.items()
            if k
            not in {
                "equipment",
                "brief_equipment",
                "workflow_kind",
                "brief_process",
            }
        }
    return patch


async def execute_chat_actions(project: dict, actions: list, instruction: str) -> tuple[dict, list]:
    result, runs = deepcopy(project), []
    for action in actions:
        kind = action.kind
        try:
            if kind == "develop_layout":
                selected = state_for(result)["selected_platform_id"]
                if selected is None:
                    runs.append({"kind": kind, "status": "ready", "message":
                        "Before developing the machine, would you prefer an assembled platform "
                        "or a buildable open-hardware system? We can compare the reviewed options "
                        "against your budget, equipment and assembly preferences first."})
                    continue
                if result["workflow"]["kind"] != "liquid_preparation":
                    raise ValueError(
                        "Describe the workflow first. This CAD adapter supports liquid preparation."
                    )
                if not (result["summary"].get("equipment") or result["brief"].get("equipment")):
                    raise ValueError(
                        "Describe the equipment in chat before developing the workstation."
                    )
                width = result["summary"].get("workspace_width_mm")
                commercial = selected == "opentrons-ot2"
                required = 1030 if commercial else foundation_metadata()["bbox_mm"][0]
                if width is not None and width < required:
                    raise ValueError(
                        f"The selected platform requires about {required:.1f} mm of width "
                        "including its known operating clearances. "
                        f"It cannot fit a {width:g} mm width without redesigning the frame. "
                        "The accepted machine is preserved; allow more space "
                        "or choose another base."
                    )
                if commercial:
                    from app.commercial_design import adopt_commercial
                    from app.platform_profiles import commercial_sourcing

                    base = (deepcopy(result) if result["design"].get("platform", {}).get("id")
                            == selected else adopt_commercial(result))
                    base["sourcing"] = commercial_sourcing()
                else:
                    base = deepcopy(result) if is_source_based(result) else adopt_foundation(result)
                result, run = await develop_design(base, instruction)
                if commercial:
                    result["sourcing"] = commercial_sourcing()
                runs.append({**run, "kind": kind})
                if run["status"] != "accepted":
                    return _rollback(project, runs)
            elif kind == "add_inspection":
                result, run = await develop_inspection(result, instruction)
                runs.append({**run, "kind": kind})
                if run["status"] != "accepted":
                    return _rollback(project, runs)
            elif kind == "remove_inspection":
                if result.get("inspection_extension"):
                    result = clear_extension(result)
                    result["revision"] += 1
                    result["status"] = "draft"
                runs.append(
                    {
                        "kind": kind,
                        "status": "accepted",
                        "message": "Inspection module removed; the existing platform is preserved.",
                    }
                )
            elif kind == "confirm":
                if not result.get("engineering_design"):
                    raise ValueError("Develop a machine in chat before confirming it.")
                result = confirm_project(result)
                runs.append(
                    {
                        "kind": kind,
                        "status": "accepted",
                        "message": "Current design and preparation requirements confirmed.",
                    }
                )
            else:
                if kind == "show_build_plan":
                    runs.append({"kind": kind, "status": "ready", "message":
                        "Open Build instructions for this revision's sourced build/setup steps, "
                        "required engineering tasks and immediate HTML, Markdown "
                        "or JSON downloads. "
                        "Parts & pricing shows US supplier prices, dates and unresolved items."
                        if state_for(result)[
                        "selected_platform_id"] else "Choose a proposed platform first so the "
                        "purchase and assembly steps match your needs."})
                    continue
                if kind == "show_files" and result["status"] != "confirmed":
                    raise ValueError("Complete the preparation plan and confirm this design "
                                     "before generating project files.")
                if kind != "show_sources" and not result.get("engineering_design"):
                    raise ValueError(
                        "Develop a machine first; its tools will appear when relevant."
                    )
                runs.append(
                    {
                        "kind": kind,
                        "status": "ready",
                        "message": {
                            "show_files": "Project files are available in Project details.",
                            "show_sources": "Reviewed sources are available in Project details.",
                            "show_components": "Current components and US price refresh are "
                            "in Parts & pricing.",
                            "show_photo_check": "Photo check is available in Project details.",
                        }[kind],
                    }
                )
        except ValueError as exc:
            runs.append({"kind": kind, "status": "rejected", "message": str(exc)})
            return _rollback(project, runs)
        except ModelClientError as exc:
            run = getattr(exc, "design_run", {})
            runs.append({**run, "kind": kind, "status": "failed", "message": str(exc)})
            return _rollback(project, runs)
    return result, runs
