"""Grounded chat integration for the deterministic non-liquid concept compiler."""
import re

_OPERATION_WORDS = {
    "weigh": r"weigh|mass|balance",
    "print_label": r"print|label printer",
    "read_barcode": r"barcode|bar code|scan",
    "inspect": r"inspect|camera|visual|image",
}
_UNSUPPORTED = re.compile(
    r"pipett|dispens|steril|filter|centrifuge samples|mixing|incubat|refrigerat|cold transfer|"
    r"laser[- ]etch|engrave|weld|cap(?:ping)? samples|"
    r"automatic(?:ally)?\s+(?:apply|applicat|label)|label\s+applicator|"
    r"apply\s+(?:the\s+)?labels?\s+automatic", re.I)


def validate_action(action, message, project, workflow_kind=None):
    """Validate new operation citations while retaining canonical prior operations."""
    if (project.get("workflow", {}).get("kind") == "liquid_preparation"
            and (project.get("engineering_design") or project.get("cold_transfer_extension"))):
        raise ValueError("Start a new project for this different station; the accepted liquid "
                         "machine is preserved")
    if (workflow_kind or project.get("workflow", {}).get("kind")) != "general":
        raise ValueError("A bench station requires an explicitly general workflow")
    if action.source not in message:
        raise ValueError("Station design must cite a literal design request")
    if _UNSUPPORTED.search(message):
        raise ValueError("Clarify all unsupported operations before designing a station")
    if (re.search(r"\b(?:what if|could this|can this|would it|might|someday|in future)\b",
                  message, re.I)
            or re.search(r"\b(?:do not|don't|not yet)\s+(?:design|build|create|add)",
                         message, re.I)):
        raise ValueError("Discuss this question without changing the station")
    old = (project.get("bench_station") or {}).get("proposal", {}).get("operations", [])
    if not (re.search(r"\b(?:design|build|create|develop|revise|reorder|add|remove|change|"
                      r"update|make|arrange|put|move|start)\b", message, re.I)
            or old and re.search(r"\b(?:first|before|after|then|last)\b", message, re.I)):
        raise ValueError("Station generation needs an explicit design or revision request")
    operations = action.operations
    if not operations or len(set(operations)) != len(operations):
        raise ValueError("Specify the complete ordered unique station operations")
    if set(old) - set(operations) and not re.search(
            r"\b(?:remove|drop|without|omit|no longer)\b", message, re.I):
        raise ValueError("Retain existing operations unless explicitly removed")
    sources = (action.operation_sources.model_dump(exclude_none=True)
               if action.operation_sources else {})
    if set(sources) - set(operations):
        raise ValueError("Operation citations must belong to requested operations")
    for operation in operations:
        source = sources.get(operation)
        if operation in old and source is None:
            continue
        if (not source or source not in message
                or not re.search(_OPERATION_WORDS[operation], source, re.I)):
            raise ValueError("Each new operation needs a literal relevant request citation")


def update_station(current, updated, actions, message, workflow_kind=None):
    """Compile atomically from authored operations; no generated geometry is accepted."""
    from app.bench_station import StationProposal, compile_station
    requested = [a for a in actions if a.kind == "develop_bench_station"]
    if updated["workflow"]["kind"] != "general":
        updated.pop("bench_station", None)
        return updated, None
    if (current.get("bench_station") and not requested
            and any(current.get("brief", {}).get(key) != updated.get("brief", {}).get(key)
                    for key in ("objective", "process", "materials", "equipment"))):
        updated.pop("bench_station", None)
        return updated, {"kind": "develop_bench_station", "status": "ready",
                         "message": ("The process brief changed. Please clarify the full operation "
                                     "sequence before a replacement station is designed.")}
    if requested:
        if len(actions) != 1:
            raise ValueError("Please request the station design separately from other actions")
        action = requested[0]
        validate_action(action, message, current, workflow_kind)
        proposal = StationProposal(schema_version="1", operations=action.operations)
    elif current.get("bench_station"):
        proposal = StationProposal.model_validate(current["bench_station"]["proposal"])
    else:
        return updated, None
    station = compile_station(proposal, workspace_width_mm=updated["summary"]["workspace_width_mm"])
    previous = current.get("bench_station")
    if (previous and previous["proposal"]["operations"] != station["proposal"]["operations"]
            and updated["brief"]["process"] == current["brief"]["process"]):
        updated["brief"]["process"] = " → ".join(module["label"] for module in station["modules"])
    changed = station != current.get("bench_station")
    updated["bench_station"] = station
    if changed and updated["revision"] == current["revision"]:
        updated["revision"] += 1
        updated["status"] = "draft"
    run = ({"kind": "develop_bench_station", "status": "accepted",
            "message": "The station layout, parts list and operating steps are ready to review."}
           if requested or changed else None)
    return updated, run


def clarification_turn(turn, message, project):
    """A refused station mutation becomes an ordinary explanation without side effects."""
    from app.model_client import ExtractedTurn
    for action in turn.actions:
        if action.kind == "develop_bench_station":
            try:
                validate_action(action, message, project, turn.workflow_kind)
            except ValueError as exc:
                return ExtractedTurn(assistant_message=str(exc) + ". "
                    "Please clarify the full operation sequence; the project is unchanged.")
    return turn
