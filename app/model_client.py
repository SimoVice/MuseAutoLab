"""Extract bounded design requirements with the Meta Model API."""

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.design_sources import reference_context, resolve_reference
from app.engineering import EngineeringUpdate, state_for
from app.quantities import normalize_concentration, normalize_targets, normalize_volume
from app.workflows import describe_workflow

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("museautolab.model")
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_BASE_URL = "https://api.meta.ai/v1"

SYSTEM_INSTRUCTIONS = """You are MuseAutoLab's general laboratory automation assistant.
Act like a practical engineer interviewing the user, not a fixed machine configurator.
Use the recorded engineering requirements and reviewed_platforms. Ask the next useful
missing question about process/throughput, existing equipment, bench space, budget,
assembly skills/time or priorities. Do not repeat known facts or demand every optional
field before helping. Propose suitable alternatives with reasons and concrete tradeoffs.
Explain the buy-assembled route versus building open hardware before choosing a base.
Never automatically choose Jubilee. No 3D design runs until a platform is explicitly
selected. 'Prebuilt dock' normally means an assembled automation base; if the context
could mean a pipette holder instead, ask one short clarifying question.
Return engineering.requirements only for facts supplied in this message, with literal
supporting sources; fields: procurement (prebuilt/open_hardware), budget, throughput,
assembly, priorities. Free text values must occur literally in their sources. Suggestions
are not requirements. engineering.options are your actual proposals, using only the
reviewed platform IDs, with a reason and tradeoffs tailored to known needs. They are
not predefined user choices. Discuss missing fit/budget evidence explicitly. The first
supported options are buildable Jubilee and an assembled Opentrons OT-2. State their
different implementation scopes; this bounded catalogue is not universal robot synthesis.
Set engineering.platform_choice and choice_source only for a clear choice now: a named
platform, one previously offered procurement route, a numbered option, or unambiguous
confirmation of one proposed option. A question, hypothetical future example, negation,
or yes after two alternatives is not a selection. Keep options=[] when not proposing.
If platform_choice is null, choice_source must also be null, without an explanation there.
When selected_platform_id is already recorded, keep platform_choice and choice_source null
unless the latest message explicitly selects a platform again. Never repeat the stored
selection_source or a selection from an earlier turn as a new choice.
After the user's clear selection and recorded liquid/equipment context, return
develop_layout so the selected architecture is actually developed. A recipe is optional
at this stage. Explain what needs buying/fabricating and link only reviewed references.
Use show_build_plan for purchase/assembly guidance. Never imply orders were placed.
For an OT-2, specify compatible instrument pipettes/racks and official configuration/
quotation/setup/calibration. Manual pipettes are not assumed compatible.
Requested throughput is a need, not proven capacity: exact rack capacity, supported
labware, pipette range and cycle time still need checking before claiming the workflow fits.
No manufacturer's machine CAD is imported; its view is schematic with an official deck-slot
grid. The 630 mm
body needs 200 mm clearance around it, including 1030 mm total width. Price/availability
are unconfirmed, not zero. Custom inspection/cooling integration is unsupported on OT-2.
For Jubilee, describe sourcing the upstream BOM, fabrication and assembly plus unresolved
custom tool interfaces. Retain source attribution. Hardware control is not implemented.
The interface already displays the opening welcome/question before the user's first message.
Do not repeat it, introduce yourself again, or ask what the user wants to automate when the
current message already states the task. Continue directly with the next missing fact.
Do not paraphrase the whole request before every follow-up; the brief already records it.
Record every applicable brief field when the user supplies it. In particular, preserve concrete
materials, equipment and constraints rather than mentioning them only in your reply. Copy literal
spans into the brief fields and their paired sources; leave only genuinely unknown fields null.
Start with broad problem discovery before task-specific quantities. First find out what process,
materials, equipment and constraints matter, asking one focused question at a time.
Do not ask for stock concentration, target concentrations or final volume until liquid
preparation is actually the task and the process context is understood. If the user already
gives quantities, use them immediately without forcing an interview.
Other workflows such as inspection, transport, mixing or labeling get relevant planning
questions, not liquid parameters.
Users do not need a complete preparation recipe to begin. If they have not chosen target
concentrations or final volumes, help define them rather than repeatedly demanding finished
values. Explain the difference between stock, target and final volume briefly when useful;
ask about the desired concentration range or comparison goal, then available volume per tube.
Keep one focused next question. The user chooses their concentrations in later turns; there
is no preset target, number of dilutions or final volume. Do not record a suggestion as a
user requirement or calculate a completed recipe before the needed choices are supplied.
Choose liquid_preparation only for aliquoting, dilution or pipette-based preparation. Moving or
inspecting tubes, mixing with a stirrer, and mentioning a pipette alone do not establish that
workflow. Classify the operation, not merely its objects.
For non-liquid tasks record available space, temperature and equipment in the generic brief
fields; keep module-specific quantity and cooling fields null.
General concept planning may reason about candidate approaches but never claim 3D models, costs,
simulation results, build files or validated hardware already exist. 3D simulation and build
packages are only available for the liquid preparation workflow.
For a liquid preparation task with an accepted selected-platform design, once stock, targets,
final volume and equipment are supplied, invite review and confirmation. If no platform is
selected, discuss the needs and platform options first. If stock is missing after targets and
volume, ask specifically for the stock concentration; never invent it from your suggestions.
The supported demonstrator uses one independent tube per target; do not block completion
by asking for replicates, batch size or targets that the user has already specified.
Use direct wording and skip generic praise such as 'great fit' or 'perfect'.
Keep capability limits short and only mention them when actually relevant, not as an apology
every turn. Never promise arbitrary CAD or hardware capability.
Respond in concise, conversational English. Use the recorded state and history: do not ask again
for information already supplied.
A brief correction updates only the named parameter; preserve the rest. Workspace width is
optional. Never repeat an unanswered optional question.
When the user asks why, explain the current plan in plain terms. Answer that question without
restarting the requirements interview.
Use only facts explicitly supplied by the user; never invent values, prices, validated hardware,
liquid-handling performance, or simulation results.
For liquid preparation tasks, report concentrations and volumes exactly as given with their
units; do not calculate dilution recipes yourself. Common equivalent notations such as mg/ml,
ul, decimal commas and shared-unit target lists are accepted by the program; do not ask the user
to change their capitalization, spacing or micro symbol.
A deterministic direct-dilution plan (one separate tube per target and no serial dilutions) is
computed separately for liquid preparation. You may explain the supplied current plan and its
actual calculated volumes. For new parameter changes the program recomputes the plan after your
response; do not predict its result or claim laboratory validation, hardware feasibility or
protocol execution.
Refrigerated sample storage (cold-storage bay) is a liquid preparation concept option with
MANUAL sample transfer; the operating animation remains the liquid preparation cycle, not a
gripper or cold transfer. The supported storage Target range is 2 to 20 C. If the user enables
cooling without stating a target, the program proposes 4 C as the assumed Target; display it as
'Target', never as a measured temperature. Never promise an achieved temperature, validated
dimensions, ventilation clearance, or physical buildability. Prices are a dated curated
snapshot, not live feeds; do not claim live pricing, ordering, or supplier availability.
Return the required JSON. For each field, extract a new value only if it was specified or
corrected in the current user message. Use null for every field that should remain unchanged.
Extract a workspace width only when the user states a specific maximum width, converting cm or m
to mm.
For every non-null field also return its paired source field: a short exact substring copied
from the current user message that supports this value. Prefer copying quantity values verbatim.
For quantities use the exact quantity or list as source, without surrounding prose. Extract
final_volume as just the quantity, e.g. '1 mL'; 'per tube' describes each target container,
not a unit. An exact supporting span '1 mL per tube' is accepted. Distinguish batch totals
and rates, which this direct per-target calculator does not support. Canonical
notation is allowed only when it is equivalent to that literal source; never invent a number or
an unstated unit. Equipment values must occur in their source. Generic brief values must occur
in their literal source. Workflow kind classification is semantic inference, but its source must
still be a literal substring of the current user message. Never route from equipment or width
wording alone and never assume liquid preparation for all lab work. Do not extract legacy
quantities from non-liquid tasks.
Width source must contain number and unit. For target lists copy the entire list, including a
shared trailing unit (e.g. '1, 2 and 3 mg/ml'). Preserve decimal commas in extracted text if
copying the user's original quantity. Use null for the source of an unchanged field. Do not copy
supporting text from previous turns.
Do not infer dimensions from words like small, narrow, less, or from a machine's current
dimensions; ask for a number instead. Do not treat depth, height, a tube dimension, or a volume
as width.
The program handles updates separately: do not claim that a requested change has already
happened.
If the user requests capabilities outside this early prototype (including ordering, hardware
operation, fluid simulation or temperature control), say that they
are not yet implemented instead of claiming success. 'Run physics' after confirmation computes
an ideal XYZ head model in MuJoCo with assumed masses, gains, force limits and obstacle
envelopes. It checks modeled motion and contacts; no liquid accuracy, real motor capability or
hardware validation is established. Do not claim a run has passed until the interface reports
that result.
The Labware photo check panel can analyze an uploaded photo or a captured camera frame using
Meta vision. Only Analyze photo sends the image. It identifies visible tube/tip regions in image
coordinates with human correction/review. It does not provide calibrated world coordinates,
measure volumes/concentrations, verify absence or control hardware. Direct users to the panel;
do not claim you have analyzed an image from chat alone.
Project packages can be generated with the 'Generate project files' control after confirmation.
They contain a concept assembly guide, selected components, preparation data and concept CAD; do
not claim a package exists until the interface reports it ready.
Before layout generation the interface shows the project brief only. Liquid preparation does
not imply that a machine exists. All design and expansion instructions are given in this chat.
Return actions=[] for discovery, advice, hypothetical future examples and parameter collection.
When the user explicitly asks to develop, generate, modify or rearrange the machine, return a
develop_layout action. Equipment and a liquid workflow are required; a dilution recipe is not.
For a geometric change to an existing design also return develop_layout. It runs a separate
bounded Meta proposal and geometric screening; never claim success before that action returns.
Use add_inspection only when the user asks to add an arm/camera module NOW to an accepted
design. A future example or possibility is not an instruction to add it. Use remove_inspection
for an explicit removal, confirm for an explicit approval, and show_files, show_sources,
show_components or show_photo_check when the user asks for those existing tools.
Every action has kind and source; source must be an exact span of this user's latest message.
At most two actions, in dependency order. Do not invent executable code, URLs or CAD file paths.
Only after Jubilee has been selected, its development path imports the pinned STEP, preserving
frame dimensions and permits a custom 240..300 by 260..300 mm insert, five fixed-size part
positions, and a proposed vertical pose of its original build-plate assembly. A roughly
483 mm wide frame cannot fit a smaller width without a different mechanical design. No
arbitrary remeshing, source-part rescaling or hardware-ready interface is supported.
Save project downloads a portable file; Open project rebuilds it without a Meta call. The last
project is also remembered in this browser. Prior simulation/image jobs are not restored.
After an accepted layout, add_inspection proposes a bounded two-link arm/camera concept and
checks planar reach and recorded-pose width on the same project. Its sweep is kinematic,
not captured imagery or validated hardware. A new layout clears that extension for redesign.
Quantity-only changes preserve the accepted geometry. Existing tools are under Project details;
there are no dedicated future-module fields. Physics is unavailable for Jubilee and OT-2:
the old ideal XYZ simulation must not be represented as validation of either platform.
Ground component/project advice in the reviewed_reference_library supplied below. It is a
dated curated library, not a live web search. Return recommendations as reference_id/reason
objects using only the supplied IDs; use an empty list for ordinary discovery questions.
Do not invent products, licenses, URLs, dimensions, ready-to-build interfaces or compatibility.
Use the supplied current foundation and geometry bindings to distinguish actual imported
Jubilee CAD from legacy custom geometry. Science Jubilee control code is not installed.
Manufacturer envelopes support only explicitly bound parts; the custom insert, pipette, racks,
arm and mounts remain concept geometry. A source review or imported CAD is not laboratory
validation. Do not set user requirements from a source or your own recommendation.
Keep the assistant_message brief and constructive."""

REQUIREMENT_KEYS = (
    "stock_concentration",
    "target_concentrations",
    "final_volume",
    "equipment",
    "workspace_width_mm",
    "cooling_enabled",
    "cooling_target_c",
)

BRIEF_KEYS = (
    "brief_objective",
    "brief_process",
    "brief_materials",
    "brief_equipment",
    "brief_constraints",
)

WORKFLOW_KEYS = ("workflow_kind",)

ALL_UPDATE_KEYS = REQUIREMENT_KEYS + WORKFLOW_KEYS + BRIEF_KEYS

WIDTH_PATTERN = re.compile(
    r"(?<![\w.+-])(\d+(?:[.,]\d+)?)\s*"
    r"(millimeters?|millimetres?|millimetr(?:o|i)|mm|centimeters?|centimetres?|"
    r"centimetr(?:o|i)|cm|meters?|metres?|metr(?:o|i)|m)\b",
    re.IGNORECASE,
)

COOLING_TERM_PATTERN = re.compile(
    r"cold[\s-]?storage|refrigerat\w*|fridge|frigorifer\w*|frigo\b|raffredd\w*|freezer|cooling|cold[\s-]?bay",
    re.IGNORECASE,
)

TARGET_TEMP_PATTERN = re.compile(
    r"(?<![\w.+-])(-?\d+(?:[.,]\d+)?)\s*(?:°\s*)?(?:degrees?\s*)?(?:celsius|c)\b",
    re.IGNORECASE,
)

ALLOWED_WORKFLOW_KINDS = ("general", "liquid_preparation")


class ModelClientError(Exception):
    """A sanitized, user-facing model integration failure."""


class SourceRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: Literal["jubilee-hardware", "science-jubilee", "pololu-1209", "pololu-1208",
                          "rpi-camera-module-3", "opentrons-temp-module-gen2", "opentrons-ot2"]
    reason: Annotated[str, Field(min_length=1, max_length=350)]

    @field_validator("reference_id")
    @classmethod
    def reviewed_reference(cls, value: str) -> str:
        resolve_reference(value)
        return value


class ChatAction(BaseModel):
    """A bounded user-requested product operation, never executable model code."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["develop_layout", "add_inspection", "remove_inspection", "confirm",
                  "show_files", "show_sources", "show_components", "show_photo_check",
                  "show_build_plan"]
    source: Annotated[str, Field(min_length=1, max_length=1000)]


class ExtractedTurn(BaseModel):
    """Strict envelope for the model's single-turn response."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    assistant_message: Annotated[str, Field(min_length=1, max_length=1200)]
    recommendations: Annotated[list[SourceRecommendation], Field(max_length=3)] = Field(
        default_factory=list
    )
    actions: Annotated[list[ChatAction], Field(max_length=2)] = Field(default_factory=list)
    engineering: EngineeringUpdate = Field(default_factory=EngineeringUpdate)
    stock_concentration: Annotated[str | None, Field(max_length=500)] = None
    target_concentrations: Annotated[str | None, Field(max_length=500)] = None
    final_volume: Annotated[str | None, Field(max_length=500)] = None
    equipment: Annotated[str | None, Field(max_length=500)] = None
    workspace_width_mm: Annotated[float | None, Field(strict=True, gt=0, le=5000)] = None
    cooling_enabled: Annotated[bool | None, Field(strict=True)] = None
    cooling_target_c: Annotated[float | None, Field(strict=True, ge=2, le=20)] = None
    workflow_kind: Literal["general", "liquid_preparation"] | None = None
    brief_objective: Annotated[str | None, Field(max_length=1000)] = None
    brief_process: Annotated[str | None, Field(max_length=1000)] = None
    brief_materials: Annotated[str | None, Field(max_length=1000)] = None
    brief_equipment: Annotated[str | None, Field(max_length=1000)] = None
    brief_constraints: Annotated[str | None, Field(max_length=1000)] = None
    source_stock_concentration: Annotated[str | None, Field(max_length=500)] = None
    source_target_concentrations: Annotated[str | None, Field(max_length=500)] = None
    source_final_volume: Annotated[str | None, Field(max_length=500)] = None
    source_equipment: Annotated[str | None, Field(max_length=500)] = None
    source_workspace_width_mm: Annotated[str | None, Field(max_length=500)] = None
    source_cooling_enabled: Annotated[str | None, Field(max_length=500)] = None
    source_cooling_target_c: Annotated[str | None, Field(max_length=500)] = None
    source_workflow_kind: Annotated[str | None, Field(max_length=1000)] = None
    source_brief_objective: Annotated[str | None, Field(max_length=1000)] = None
    source_brief_process: Annotated[str | None, Field(max_length=1000)] = None
    source_brief_materials: Annotated[str | None, Field(max_length=1000)] = None
    source_brief_equipment: Annotated[str | None, Field(max_length=1000)] = None
    source_brief_constraints: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator(
        "assistant_message",
        "stock_concentration",
        "target_concentrations",
        "final_volume",
        "equipment",
        "brief_objective",
        "brief_process",
        "brief_materials",
        "brief_equipment",
        "brief_constraints",
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be empty")
        return value

    @field_validator("workflow_kind", "source_workflow_kind", mode="before")
    @classmethod
    def _trim_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Text cannot be empty")
            return value
        return value

    @field_validator("workflow_kind")
    @classmethod
    def _check_workflow_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ALLOWED_WORKFLOW_KINDS:
            raise ValueError("workflow_kind must be 'general' or 'liquid_preparation'")
        return value

    def patch(self) -> dict:
        """Return only explicitly extracted updates, not null placeholders."""
        return {
            key: getattr(self, key) for key in ALL_UPDATE_KEYS if getattr(self, key) is not None
        }

    def verify_sources(self, user_message: str) -> None:
        """Verify each change against a literal span from the latest user message."""
        for action in self.actions:
            if action.source not in user_message:
                raise ValueError("Action source must occur literally in this message")
        if len({action.kind for action in self.actions}) != len(self.actions):
            raise ValueError("Do not repeat an action within one turn")
        for key in REQUIREMENT_KEYS:
            value = getattr(self, key)
            source = getattr(self, f"source_{key}")
            if value is None:
                if source is not None:
                    raise ValueError("A source without a value is not a valid change")
                continue
            if not source or source not in user_message:
                raise ValueError("Update source must be a literal span from this message")
            if key == "workspace_width_mm":
                found_values = []
                for match in WIDTH_PATTERN.finditer(source):
                    number = float(match.group(1).replace(",", "."))
                    unit = match.group(2).lower()
                    factor = 1 if unit.startswith(("mm", "milli")) else 10
                    if unit in {"m", "meter", "meters", "metre", "metres", "metro", "metri"}:
                        factor = 1000
                    found_values.append(number * factor)
                if not any(abs(candidate - value) < 1e-6 for candidate in found_values):
                    raise ValueError("Workspace width must match a source measurement and unit")
            elif key == "equipment":
                if value.casefold() not in source.casefold():
                    raise ValueError("Equipment must occur in its supporting source")
            elif key == "cooling_enabled":
                if not isinstance(value, bool):
                    raise ValueError("Cooling choice must be boolean")
                if not COOLING_TERM_PATTERN.search(source):
                    raise ValueError("Cooling choice must cite explicit cold-storage wording")
            elif key == "cooling_target_c":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError("Cooling target must be a number")
                candidate = float(value)
                if not math.isfinite(candidate) or candidate < 2 or candidate > 20:
                    raise ValueError("Cooling target must be within 2..20 C")
                found: list[float] = []
                for match in TARGET_TEMP_PATTERN.finditer(source):
                    try:
                        found.append(float(match.group(1).replace(",", ".")))
                    except ValueError:
                        continue
                if not any(abs(item - candidate) < 1e-6 for item in found):
                    raise ValueError(
                        "Cooling target must match a literal temperature in its source"
                    )
            elif not re.search(r"(?<![\w.,+\-])" + re.escape(value) + r"(?![\w/])", source):
                normalizer = {
                    "stock_concentration": normalize_concentration,
                    "target_concentrations": normalize_targets,
                    "final_volume": normalize_volume,
                }[key]
                if normalizer(value) != normalizer(source):
                    raise ValueError("Quantity must be equivalent to its literal source")
        for key in BRIEF_KEYS:
            value = getattr(self, key)
            source = getattr(self, f"source_{key}")
            if value is None:
                if source is not None:
                    raise ValueError("A source without a value is not a valid change")
                continue
            if not source or source not in user_message:
                raise ValueError("Update source must be a literal span from this message")
            if value.casefold() not in source.casefold():
                raise ValueError("Brief value must occur in its supporting source")
        value = self.workflow_kind
        source = self.source_workflow_kind
        if value is None:
            if source is not None:
                raise ValueError("A source without a value is not a valid change")
        else:
            if not source or source not in user_message:
                raise ValueError("Update source must be a literal span from this message")
        if self.workflow_kind == "general":
            for legacy in ("stock_concentration", "target_concentrations", "final_volume"):
                if getattr(self, legacy) is not None:
                    raise ValueError("Legacy quantities require a liquid preparation task")


@dataclass(frozen=True, repr=False)
class ModelSettings:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def load(cls) -> "ModelSettings":
        """Load local credentials without modifying the process environment or printing them."""
        local = dotenv_values(ROOT / ".env")

        def get_value(key: str, fallback: str = "") -> str:
            value = os.environ.get(key)
            if value is None:
                value = local.get(key)
            return str(value or fallback).strip()

        settings = cls(
            api_key=get_value("MODEL_API_KEY"),
            base_url=get_value("META_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=get_value("META_MODEL", DEFAULT_MODEL),
        )
        if not settings.api_key:
            raise ModelClientError("Set MODEL_API_KEY in the local .env file before using chat.")
        return settings


def _safe_usage(response: dict) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        key: value
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((value := usage.get(key)), int) and not isinstance(value, bool) and value >= 0
    }


def _strict_schema() -> dict:
    schema = ExtractedTurn.model_json_schema()
    def require_all(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if "properties" in node:
                node["required"] = sorted(node["properties"])
                node["additionalProperties"] = False
            for item in node.values():
                require_all(item)
        elif isinstance(node, list):
            for item in node:
                require_all(item)
    require_all(schema)
    return schema


def _catalogue_facts(project: dict) -> dict:
    sourcing = project["sourcing"]
    items = []
    for group in sourcing["groups"]:
        selected = next(
            option for option in group["options"] if option["id"] == group["selected_id"]
        )
        if selected["unit_price"] is not None:
            items.append(
                {
                    "label": selected["label"],
                    "quantity": group["quantity"],
                    "unit_price_usd": selected["unit_price"],
                    "price_kind": selected["price_kind"],
                }
            )
    return {
        "checked_on": sourcing["checked_on"],
        "subtotal_usd": sourcing["subtotal"],
        "is_lower_bound": sourcing["is_lower_bound"],
        "incomplete": True,
        "unpriced_groups": sourcing["unpriced_count"],
        "selected_items": items,
        "exclusions": sourcing["exclusions"],
    }


async def generate_turn(
    project: dict,
    user_message: str,
    history: list[dict[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
    settings: ModelSettings | None = None,
) -> tuple[ExtractedTurn, dict[str, int]]:
    """Call Meta once and validate its structured result before any project storage.

    Only the current project state and a small history window are sent. The API key stays on the
    backend, and provider errors are sanitized. The caller controls project storage and retries.
    """
    settings = settings or ModelSettings.load()
    workflow = (
        describe_workflow(project) if isinstance(project, dict) else {"design_available": False}
    )
    design_available = (
        bool(workflow.get("design_available")) if isinstance(workflow, dict) else False
    )
    state: dict = {
        "brief": project.get("brief", {}) if isinstance(project, dict) else {},
        "workflow": workflow,
        "reviewed_reference_library": reference_context(project),
        "engineering": state_for(project),
    }
    from app.platform_profiles import platform_profiles

    state["reviewed_platforms"] = platform_profiles()
    accepted_layout = bool(project.get("engineering_design"))
    if not accepted_layout:
        state["reviewed_reference_library"]["geometry_bindings"] = []
        state["reviewed_reference_library"]["architecture"] = (
            "Workflow discovery; no accepted machine design"
        )
    if design_available:
        design = project.get("design", {}) if isinstance(project, dict) else {}
        state.update(
            {
                "summary": project.get("summary"),
                "current_footprint_mm": design.get("footprint") if accepted_layout else None,
                "constraint_status": design.get("constraint_status"),
                "current_plan": project.get("plan"),
                "cooling": design.get("cooling"),
                "catalogue": _catalogue_facts(project) if accepted_layout else None,
                "foundation": design.get("foundation"),
                "platform": design.get("platform"),
                "has_accepted_layout": bool(project.get("engineering_design")),
                "inspection_extension": ({
                    "status": "digital_concept",
                    "proposal": project["inspection_extension"]["proposal"],
                    "limitations": project["inspection_extension"]["limitations"],
                } if project.get("inspection_extension") else None),
            }
        )
    messages = [
        {"role": "developer", "content": SYSTEM_INSTRUCTIONS},
        {
            "role": "developer",
            "content": "Current recorded project state: " + json.dumps(state, ensure_ascii=False),
        },
        *history[-8:],
        {"role": "user", "content": user_message},
    ]
    payload = {
        "model": settings.model,
        "messages": messages,
        "reasoning_effort": "minimal",
        "max_completion_tokens": 2400,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "requirement_turn",
                "strict": True,
                "schema": _strict_schema(),
            },
        },
    }
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    async def send(active_client: httpx.AsyncClient) -> httpx.Response:
        return await active_client.post(
            f"{settings.base_url}/chat/completions", headers=headers, json=payload
        )

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as active_client:
                response = await send(active_client)
        else:
            response = await send(client)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ModelClientError(
            f"Meta request failed (HTTP {status}). Check model access or try again."
        ) from None
    except httpx.RequestError:
        raise ModelClientError(
            "Could not reach Meta. Check the network connection and try again."
        ) from None

    body = None
    failure_kind = "response_format"
    try:
        body = response.json()
        choice = body["choices"][0]
        if choice.get("finish_reason") in {"length", "content_filter"}:
            failure_kind = (
                "token_limit" if choice["finish_reason"] == "length" else "content_filter"
            )
            raise ValueError("incomplete model response")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("invalid message content")
        result = ExtractedTurn.model_validate_json(content)
        failure_kind = "source_validation"
        for key in BRIEF_KEYS:
            value = getattr(result, key)
            source = getattr(result, f"source_{key}")
            if (isinstance(value, str) and isinstance(source, str)
                    and value in user_message and source in user_message
                    and value.casefold() not in source.casefold()):
                # Correct only an undersized citation of text already copied verbatim.
                # No new brief value or semantic inference is introduced.
                setattr(result, f"source_{key}", value)
        result.verify_sources(user_message)
        recorded = state_for(project)
        if (
            result.engineering.platform_choice is not None
            and result.engineering.platform_choice == recorded["selected_platform_id"]
            and isinstance(result.engineering.choice_source, str)
            and result.engineering.choice_source == recorded["selection_source"]
            and result.engineering.choice_source not in user_message
        ):
            # A verbatim echo of the accepted choice cannot select or change anything.
            # Drop this inert repetition; new/different choices still need current evidence.
            result.engineering.platform_choice = None
            result.engineering.choice_source = None
        result.engineering.verify_sources(user_message, project)
        effective_kind = result.workflow_kind or workflow["kind"]
        if effective_kind == "general" and any(
            getattr(result, key) is not None
            for key in ("stock_concentration", "target_concentrations", "final_volume")
        ):
            raise ValueError("Liquid parameters do not belong to this workflow")
    except (ValueError, TypeError, KeyError, IndexError, ValidationError):
        error = ModelClientError(
            "Meta returned an incomplete or invalid response. The project was not changed."
        )
        error.failure_kind = failure_kind
        error.usage = _safe_usage(body) if isinstance(body, dict) else {}
        LOGGER.warning(
            "Meta model=%s failure_kind=%s token_usage=%s",
            settings.model, failure_kind, error.usage,
        )
        raise error from None

    usage = _safe_usage(body)
    # Only counts/model ID are logged; prompts, responses and authentication are omitted.
    LOGGER.info("Meta model=%s token_usage=%s", settings.model, usage)
    return result, usage
