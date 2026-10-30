"""Bounded Meta layout-design loop for the liquid preparation workstation.

The geometry contract lives in app.design_spec (owned by the geometry worker).
This module only drives the model, validates candidates through check_candidate,
and compiles accepted candidates through apply_candidate. No silent fixes here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from copy import deepcopy
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx

from app.design_sources import project_source_basis, reference_context
from app.design_spec import apply_candidate, check_candidate, proposal_schema
from app.model_client import ModelClientError, ModelSettings, _safe_usage

LOGGER = logging.getLogger("museautolab.design")

DESIGN_MODEL_TIMEOUT_S = 45.0
DESIGN_MAX_COMPLETION_TOKENS = 2400
DESIGN_MAX_ATTEMPTS = 2
DESIGN_TOTAL_BUDGET_S = 90.0

_SEMAPHORES: WeakKeyDictionary = WeakKeyDictionary()


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _SEMAPHORES:
        _SEMAPHORES[loop] = asyncio.Semaphore(2)
    return _SEMAPHORES[loop]


def _actual_model(body: Any, fallback: str) -> str:
    if isinstance(body, dict):
        model = body.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return fallback


def _safe_design_usage(body: dict, settings: ModelSettings) -> dict:
    raw = _safe_usage(body)
    usage: dict[str, Any] = {"model": _actual_model(body, settings.model)}
    if isinstance(raw.get("prompt_tokens"), int):
        usage["input_tokens"] = raw["prompt_tokens"]
    if isinstance(raw.get("completion_tokens"), int):
        usage["output_tokens"] = raw["completion_tokens"]
    return usage


def _summarize_project(project: dict) -> dict:
    summary = project.get("summary", {}) if isinstance(project, dict) else {}
    design = project.get("design", {}) if isinstance(project, dict) else {}
    footprint = design.get("footprint", {}) if isinstance(design, dict) else {}
    cooling = design.get("cooling", {}) if isinstance(design, dict) else {}
    components: list[dict] = []
    raw_components = design.get("components", []) if isinstance(design, dict) else []
    if isinstance(raw_components, list):
        for item in raw_components:
            if not isinstance(item, dict):
                continue
            components.append(
                {
                    "id": item.get("id"),
                    "position": item.get("position"),
                    "size": item.get("size"),
                    "slot_id": item.get("slot_id"),
                }
            )
    insert_layout = None
    if design.get("foundation"):
        parts = {part["id"]: part for part in components}
        try:
            deck = parts["base"]
            insert_layout = {
                "deck_width_mm": deck["size"][0],
                "deck_depth_mm": deck["size"][2],
                "bed_drop_mm": design["foundation"]["bed_drop_mm"],
                "placements": [
                    {"component_id": cid,
                     "x_mm": round(parts[cid]["position"][0] - deck["position"][0], 6),
                     "z_mm": round(parts[cid]["position"][2] - deck["position"][2], 6)}
                    for cid in ("source-rack", "sample-rack", "tip-rack", "tip-waste", "controller")
                ],
            }
        except (KeyError, TypeError, IndexError):
            insert_layout = None
    return {
        "revision": project.get("revision") if isinstance(project, dict) else None,
        "workspace_width_mm": summary.get("workspace_width_mm"),
        "cooling_enabled": summary.get("cooling_enabled"),
        "cooling_target_c": summary.get("cooling_target_c"),
        "constraint_status": design.get("constraint_status"),
        "footprint_mm": {
            "width_mm": footprint.get("width_mm"),
            "depth_mm": footprint.get("depth_mm"),
            "height_mm": footprint.get("height_mm"),
        },
        "cooling": {"enabled": cooling.get("enabled"), "target_c": cooling.get("target_c")},
        "components": components,
        "current_insert_layout": insert_layout,
    }


def _developer_instructions(project: dict) -> str:
    state = _summarize_project(project)
    platform = project.get("design", {}).get("platform")
    if platform and platform.get("id") == "opentrons-ot2":
        return (
            "Propose the requested labware arrangement on the explicitly selected, assembled "
            "Opentrons OT-2 platform. Strict JSON: schema_version '1', slot_assignments "
            "for exactly source-rack/sample-rack/tip-rack, each a distinct string slot_id "
            "from '1' to '11', rationale and assumptions. Slot12 is fixed trash. Retain "
            "existing assignments unless the user's request needs a change. Do not alter "
            "the body, invent pipette compatibility, rescale labware or claim vendor CAD. "
            "Only the manufacturer outer envelope and pinned software deck grid are sourced; "
            "internal parts and deck height are schematic. This is a setup/layout proposal, "
            "not hardware control, a certified protocol or fabrication design. Cooling and "
            "custom inspection integration are not supported on this profile. "
            f"Platform: {json.dumps(platform)}; current state: {json.dumps(state)}"
        )
    foundation = project.get("design", {}).get("foundation")
    if foundation:
        return (
            "Design a custom liquid-preparation insert on the actual imported Jubilee CAD. "
            "Return strict JSON: schema_version '1', deck_width_mm240..300, "
            "deck_depth_mm260..300, bed_drop_mm95..150, placements for exactly source-rack, "
            "sample-rack, tip-rack, tip-waste, controller, rationale and assumptions. "
            "Coordinates x_mm/z_mm are relative to the insert centre. Keep fixed component "
            "sizes, 10mm to every insert edge and5mm separation between footprints. "
            "There is no legacy rear85mm exclusion on this insert. Use two rows/columns "
            "rather than placing three95mm racks across a300mm bed. "
            "For revisions, retain the current insert dimensions, placements and bed pose "
            "unless the user's requested change needs them changed. Use actual current "
            "positions below, not an assumed starter layout. "
            "Use current_insert_layout as the authoritative insert-relative parameters; "
            "do not recompute or guess offsets from absolute component centres. Copy its "
            "placements verbatim when the request preserves the arrangement. The source frame and "
            "native fixed parts are immutable. bed_drop_mm translates only the original "
            "build-plate subassembly downward; it is an illustrative unverified travel pose. "
            "The300mm workspace is a conservative placement hypothesis, not measured mounting "
            "or calibrated travel. Changes must keep the original frame width fixed; an "
            "overall width below the imported frame is impossible. Do not claim physical "
            "operation, mounting or collision validation. "
            f"Foundation: {json.dumps(foundation)}. State: {json.dumps(state)}"
        )
    return (
        "You propose a liquid preparation workstation deck layout as strict JSON only. "
        "Millimetres; y is vertical, z is depth; placements are component centres (x_mm, z_mm). "
        "Required JSON fields: schema_version '1', deck_width_mm between 400 and 900, "
        "deck_depth_mm between 320 and 650 for the operating deck WITHOUT the appended cold bay, "
        "placements with exactly the five movable parts "
        "source-rack, sample-rack, tip-rack, tip-waste and controller, "
        "rationale (max 1200 chars), assumptions (max 6 items, each max 300 chars). "
        "Rules: keep at least 10 mm clearance from every deck edge, at least 5 mm edge-to-edge gap "
        "between movable footprints, and keep every movable part out of the rear gantry strip "
        "(z_min >= -deck_depth/2 + 85). Fixed purchased and concept equipment sizes are immutable; "
        "you choose deck size and placements and the compiler only validates. "
        "Never exceed workspace_width_mm when a limit is supplied. Dimensions you introduce "
        "are proposed design choices, not user-confirmed or supplier specifications. "
        "Do not claim hardware, cooling or collision validation. "
        f"Current project state: {json.dumps(state, ensure_ascii=False)} "
        f"Reviewed design references: {json.dumps(reference_context(project), ensure_ascii=False)}"
    )


async def propose_layout(
    project: dict,
    instruction: str,
    feedback: str,
    *,
    client: httpx.AsyncClient | None = None,
    settings: ModelSettings | None = None,
) -> tuple[dict, dict]:
    """Call the configured Meta endpoint once and return the raw candidate plus usage.

    The candidate is NOT validated here; semantic and schema diagnostics belong
    to check_candidate so the caller can run one bounded correction.
    """
    return await request_design_proposal(
        _developer_instructions(project), proposal_schema(project), "layout_proposal", instruction,
        feedback, client=client, settings=settings,
    )


async def request_design_proposal(
    instructions: str, schema: dict, schema_name: str, instruction: str, feedback: str,
    *, client: httpx.AsyncClient | None = None, settings: ModelSettings | None = None,
) -> tuple[dict, dict]:
    """Shared bounded transport for supported declarative design proposals."""
    resolved = settings or ModelSettings.load()
    user_content = instruction.strip()
    if feedback and feedback.strip():
        user_content += (
            "\n\nPrevious proposal failed geometry checks; correct it:\n" + feedback.strip()
        )
    messages = [
        {"role": "developer", "content": instructions},
        {"role": "user", "content": user_content},
    ]
    payload = {
        "model": resolved.model,
        "messages": messages,
        "reasoning_effort": "minimal",
        "max_completion_tokens": DESIGN_MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    headers = {"Authorization": f"Bearer {resolved.api_key}"}

    async def send(active: httpx.AsyncClient) -> httpx.Response:
        return await active.post(
            f"{resolved.base_url}/chat/completions", headers=headers, json=payload
        )

    try:
        if client is None:
            timeout = httpx.Timeout(DESIGN_MODEL_TIMEOUT_S, connect=15)
            async with httpx.AsyncClient(timeout=timeout) as active:
                response = await asyncio.wait_for(
                    send(active), timeout=DESIGN_MODEL_TIMEOUT_S
                )
        else:
            response = await asyncio.wait_for(send(client), timeout=DESIGN_MODEL_TIMEOUT_S)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ModelClientError(
            f"Meta design request failed (HTTP {exc.response.status_code}). Try again."
        ) from None
    except (httpx.RequestError, asyncio.TimeoutError):
        raise ModelClientError(
            "Could not reach Meta for the design request. Try again."
        ) from None

    body = None
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("invalid response envelope")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("missing choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError("invalid choice")
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise ValueError("incomplete model response")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise TypeError("invalid message envelope")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise TypeError("invalid message content")
        candidate = json.loads(content)
        if not isinstance(candidate, dict):
            raise TypeError("candidate must be a JSON object")
    except (ValueError, TypeError, AttributeError):
        error = ModelClientError(
            "Meta returned an incomplete or invalid design response. The project was not changed."
        )
        error.usage = _safe_design_usage(body, resolved) if isinstance(body, dict) else {}
        raise error from None

    usage = _safe_design_usage(body, resolved)
    LOGGER.info("Meta design model=%s token_usage=%s", usage.get("model"), usage)
    return candidate, usage


def _format_checks(checks: list[dict]) -> str:
    failures = [c for c in checks if isinstance(c, dict) and not c.get("passed")]
    if not failures:
        return "all geometry checks passed"
    parts = []
    for item in failures:
        label = item.get("label") or item.get("id") or "check"
        detail = item.get("detail") or "failed"
        parts.append(f"{label}: {detail}")
    return "; ".join(parts)


def _attempt_record(
    number: int, proposal: dict, checks: list[dict], usage: dict
) -> dict:
    return {
        "number": number,
        "proposal": deepcopy(proposal),
        "checks": deepcopy(checks),
        "usage": deepcopy(usage),
    }


def _preservation_checks(project: dict, candidate: dict, instruction: str) -> list[dict]:
    """Check a bounded English preservation vocabulary, not arbitrary user intent.

    Recognized keep/retain/preserve/leave clauses can lock the existing insert
    layout, insert dimensions, or bed pose. Negated clauses do not create locks.
    A violation becomes ordinary model-correction feedback, never a silent edit.
    """
    current = _summarize_project(project)["current_insert_layout"]
    if current is None or not isinstance(candidate, dict):
        return []
    locks = set()
    for clause in re.split(r"[.!?;]", instruction.casefold()):
        verb = re.search(r"\b(?:keep|retain|retaining|preserve|preserving|leave)\b", clause)
        if not verb:
            continue
        prefix = clause[:verb.start()]
        if re.search(r"(?:\bnot|\bnever|n't|\bno need to)\s*(?:\w+\s+){0,2}$", prefix):
            continue
        subject = re.split(
            r"\b(?:but|then|while)\b|\band\s+(?:(?:please|also)\s+)?"
            r"(?:change|move|resize|rearrange|redesign|lower|raise|increase|decrease|shrink|expand)\b",
            clause[verb.end():], maxsplit=1,
        )[0]
        if re.search(r"\b(?:component|rack|insert) arrangement\b", subject):
            locks.add("placements")
        if re.search(r"\blayout\b", subject):
            locks.update(("placements", "deck_width_mm", "deck_depth_mm"))
        if re.search(r"\b(?:insert|deck) (?:dimensions|size|width|depth)\b", subject):
            locks.update(("deck_width_mm", "deck_depth_mm"))
        if re.search(r"\bbed (?:pose|position)\b", subject):
            locks.add("bed_drop_mm")

    def same_number(a, b):
        try:
            return (isinstance(a, (int, float)) and not isinstance(a, bool)
                    and math.isclose(a, b, rel_tol=0, abs_tol=1e-5))
        except (OverflowError, TypeError, ValueError):
            return False

    checks = []
    for field in sorted(locks):
        if field == "placements":
            proposed = candidate.get(field)
            valid_records = (
                isinstance(proposed, list)
                and all(isinstance(p, dict) and isinstance(p.get("component_id"), str)
                        for p in proposed)
            )
            by_id = {part["component_id"]: part for part in proposed} if valid_records else {}
            expected = {p["component_id"]: p for p in current[field]}
            passed = set(by_id) == set(expected) and all(
                same_number(by_id[cid].get(axis), expected[cid][axis])
                for cid in expected for axis in ("x_mm", "z_mm")
            )
        else:
            passed = same_number(candidate.get(field), current[field])
        checks.append({
            "id": f"preserve_{field}", "label": f"Preserve requested {field}",
            "passed": passed,
            "detail": ("Requested existing parameter retained." if passed else
                       f"The user requested preserving {field}; copy current value "
                       f"{json.dumps(current[field])} without changing it."),
        })
    return checks


async def develop_design(project: dict, instruction: str) -> tuple[dict, dict]:
    """Run at most two model attempts and compile the first valid candidate.

    Returns (project, run). Accepted runs commit via apply_candidate; rejected
    runs return an unchanged deep copy. Transport errors raise ModelClientError.
    """
    source = deepcopy(project)
    source_revision = source.get("revision")
    try:
        requested_model = ModelSettings.load().model
    except ModelClientError:
        # Allows offline injected proposers; the real proposer still requires credentials.
        requested_model = "not recorded"
    run_id = f"design-{uuid4().hex[:8]}"
    attempts: list[dict] = []
    feedback = ""
    started = time.monotonic()
    async with _semaphore():
        for number in range(1, DESIGN_MAX_ATTEMPTS + 1):
            if number > 1 and (time.monotonic() - started) >= DESIGN_TOTAL_BUDGET_S:
                break
            remaining = DESIGN_TOTAL_BUDGET_S - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                candidate, usage = await asyncio.wait_for(
                    propose_layout(source, instruction, feedback), timeout=remaining
                )
            except (ModelClientError, asyncio.TimeoutError) as exc:
                message = (
                    str(exc) if isinstance(exc, ModelClientError)
                    else "The Meta design request timed out. The project was not changed."
                )
                usage = getattr(exc, "usage", {})
                error = ModelClientError(message)
                error.design_run = {
                    "id": run_id, "source_revision": source_revision, "status": "failed",
                    "model": usage.get("model", requested_model), "instruction": instruction,
                    "attempts": attempts + [{
                        "number": number, "proposal": None, "checks": [], "usage": usage,
                        "error": message,
                    }], "message": message,
                }
                raise error from None
            model = usage.get("model") or requested_model
            checks = check_candidate(source, candidate)
            checks.extend(_preservation_checks(source, candidate, instruction))
            attempts.append(_attempt_record(number, candidate, checks, usage))
            if all(isinstance(c, dict) and c.get("passed") for c in checks):
                provenance = {
                    "run_id": run_id,
                    "model": model,
                    "source_revision": source_revision,
                    "attempt_count": number,
                    "instruction": instruction,
                    "attempts": deepcopy(attempts),
                    "checks": deepcopy(checks),
                    "usage": deepcopy(usage),
                    "source_library_sha256": project_source_basis(source)["library_sha256"],
                }
                updated = apply_candidate(source, candidate, provenance)
                message = (
                    f"Meta layout accepted using {model} after {number} attempt(s). "
                    f"All {len(checks)} geometry checks passed."
                )
                run = {
                    "id": run_id,
                    "source_revision": source_revision,
                    "status": "accepted",
                    "model": model,
                    "instruction": instruction,
                    "attempts": attempts,
                    "message": message,
                }
                return updated, run
            feedback = (
                f"Previous candidate: {json.dumps(candidate, ensure_ascii=False)} "
                f"Diagnostics: {_format_checks(checks)}"
            )
    run = {
        "id": run_id,
        "source_revision": source_revision,
        "status": "rejected",
        "model": (
            attempts[-1]["usage"].get("model", requested_model) if attempts else requested_model
        ),
        "instruction": instruction,
        "attempts": attempts,
        "message": (
            f"Meta layout rejected after {len(attempts)} attempt(s). "
            f"{_format_checks(attempts[-1]['checks']) if attempts else 'No attempt completed.'} "
            "The project was not changed."
        ),
    }
    return deepcopy(source), run
