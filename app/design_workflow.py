"""Machine approval is separate from preparation recipe readiness."""

import hashlib
import json
import re
from copy import deepcopy

RECIPE_FIELDS = ("stock_concentration", "target_concentrations", "final_volume")


def machine_signature(project: dict) -> str:
    design = deepcopy(project.get("design", {}))
    design.pop("estimated_cost", None)
    payload = {"design": design, "engineering_design": project.get("engineering_design"),
               "selections": project.get("selections"),
               "concept_design": (project.get("concept_design") or {}).get("proposal"),
               "bench_station": (project.get("bench_station") or {}).get("proposal"),
               "inspection_extension": project.get("inspection_extension"),
               "cold_transfer_extension": project.get("cold_transfer_extension")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def workflow_state(project: dict) -> dict:
    approval = project.get("machine_approval")
    approved = bool(approval and approval.get("machine_signature") == machine_signature(project)
                    and has_machine(project))
    return {"phase": "software" if approved else "hardware_design",
            "machine_approved": approved, "approval": deepcopy(approval) if approved else None,
            "recipe_started": any(project.get("summary", {}).get(k) for k in RECIPE_FIELDS)}


def refresh_workflow(project: dict) -> dict:
    project["design_workflow"] = workflow_state(project)
    return project


def has_machine(project: dict) -> bool:
    return bool(project.get("engineering_design") or project.get("concept_design")
                or project.get("bench_station"))


def approve_machine(project: dict) -> dict:
    if not has_machine(project):
        raise ValueError("Develop a machine design before approving it.")
    if project.get("design", {}).get("constraint_status") == "infeasible":
        raise ValueError("Resolve the machine workspace constraint before approval.")
    result = deepcopy(project)
    if not workflow_state(result)["machine_approved"]:
        result["revision"] += 1
    result["machine_approval"] = {"machine_signature": machine_signature(result),
                                  "revision": result["revision"]}
    if result.get("plan", {}).get("status") == "ready":
        result["status"] = "confirmed"
    return refresh_workflow(result)


def require_approval_request(message: str) -> None:
    """Require affirmative approval, never a question or a hardware revision."""
    text = message.casefold().replace("’", "'")
    agreement = re.search(
        r"\b(?:approv(?:e|ed)|confirm(?:ed)?|accept(?:ed)?|confermo|approvo|accetto|"
        r"(?:this|that)(?: is|'s) (?:the (?:machine|design|setup|one) (?:i|we) want|"
        r"what (?:i|we) want)|(?:this|that) works for (?:me|us)|"
        r"(?:let's|let us) (?:program (?:it|this)|write the (?:software|program))|"
        r"(?:design|machine|setup) looks (?:good|right)|looks good to me)\b", text
    ) or re.fullmatch(r"\s*(?:ok(?:ay)?|yes|perfect|perfetto|bene|sì)[.!\s]*", text)
    if ("?" in text or re.search(
            r"\b(?:not|never|don't|haven't|if|could|should|non|forse|se)\b", text)
            or re.search(r"\b(?:add|remove|replace|change|modify|move|resize|redesign|revise|"
                         r"aggiungi|rimuovi|sostituisci|cambia|modifica|sposta)\b", text)
            or not agreement):
        raise ValueError("Please explicitly approve the current machine after reviewing it. "
                         "Questions and hardware changes do not approve a design.")
