"""Extract bounded design requirements with the Meta Model API."""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.quantities import normalize_concentration, normalize_targets, normalize_volume

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("museautolab.model")
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_BASE_URL = "https://api.meta.ai/v1"

SYSTEM_INSTRUCTIONS = """You are MuseAutoLab's laboratory workstation design assistant.
The user is refining an early, simplified digital concept for dilution and aliquot preparation.
Respond in concise, conversational English. Answer the user's actual question first. Gather stock
concentration, target concentrations, final volume, equipment and optionally workspace width.
Use the recorded state and history: do not ask again for information already supplied. Ask one
focused question when something necessary is missing or ambiguous. A brief correction updates only
the named parameter; preserve the rest. Explain supported alternatives when a request cannot work.
Workspace width is optional. Never repeat an unanswered optional question. Do not end every reply
with a question: when the four required fields are present, invite review/confirmation instead.
When the user asks why, explain the current plan using the dilution relation C1*V1 = C2*V2 and
the remaining diluent volume. Answer that question without restarting the requirements interview.
Use only facts explicitly supplied by the user; never invent values, prices, validated hardware,
liquid-handling performance, or simulation results. Report concentrations and volumes exactly as
given with their units; do not calculate dilution recipes yourself. Common equivalent notations
such as mg/ml, ul, decimal commas and shared-unit target lists are accepted by the program; do not
ask the user to change their capitalization, spacing or micro symbol.
A deterministic direct-dilution plan (one separate tube per target and no serial dilutions) is
computed separately. You may explain the supplied current plan and its actual calculated volumes.
For new parameter changes the program recomputes the plan after your response; do not predict its
result or claim laboratory validation, hardware feasibility or protocol execution.

Return the required JSON. For each field, extract a new value only if it was specified or corrected
in the current user message. Use null for every field that should remain unchanged. Extract a
workspace width only when the user states a specific maximum width, converting cm or m to mm.
For every non-null field also return its paired source field: a short exact substring copied from
the current user message that supports this value. Prefer copying quantity values verbatim.
For quantities use the exact quantity or list as source, without surrounding prose. Canonical
notation is allowed only when it is equivalent to that literal source; never invent a number or
an unstated unit. Equipment values must occur in their source.
Width source must contain number and unit.
For target lists copy the entire list, including a shared trailing unit (e.g. '1, 2 and 3 mg/ml').
Preserve decimal commas in extracted text if copying the user's original quantity.
Use null for the source of an unchanged field. Do not copy supporting text from previous turns.
Do not infer dimensions from words like small, narrow, less, or from a machine's current dimensions;
ask for a number instead. Do not treat depth, height, a tube dimension, or a volume as width.
The program handles updates separately: do not claim that a requested change has already happened.
If the user requests
capabilities outside this early prototype (including cooling, ordering, hardware operation, saved
files, or simulation), say that they are not yet implemented instead of claiming success.
Keep the assistant_message brief and constructive."""

REQUIREMENT_KEYS = (
    "stock_concentration",
    "target_concentrations",
    "final_volume",
    "equipment",
    "workspace_width_mm",
)

WIDTH_PATTERN = re.compile(
    r"(?<![\w.+-])(\d+(?:[.,]\d+)?)\s*"
    r"(millimeters?|millimetres?|millimetr(?:o|i)|mm|centimeters?|centimetres?|"
    r"centimetr(?:o|i)|cm|meters?|metres?|metr(?:o|i)|m)\b",
    re.IGNORECASE,
)


class ModelClientError(Exception):
    """A sanitized, user-facing model integration failure."""


class ExtractedTurn(BaseModel):
    """Strict envelope for the model's single-turn response."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    assistant_message: Annotated[str, Field(min_length=1, max_length=1200)]
    stock_concentration: Annotated[str | None, Field(max_length=500)]
    target_concentrations: Annotated[str | None, Field(max_length=500)]
    final_volume: Annotated[str | None, Field(max_length=500)]
    equipment: Annotated[str | None, Field(max_length=500)]
    workspace_width_mm: Annotated[float | None, Field(strict=True, gt=0, le=5000)]
    source_stock_concentration: Annotated[str | None, Field(max_length=500)]
    source_target_concentrations: Annotated[str | None, Field(max_length=500)]
    source_final_volume: Annotated[str | None, Field(max_length=500)]
    source_equipment: Annotated[str | None, Field(max_length=500)]
    source_workspace_width_mm: Annotated[str | None, Field(max_length=500)]

    @field_validator(
        "assistant_message",
        "stock_concentration",
        "target_concentrations",
        "final_volume",
        "equipment",
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be empty")
        return value

    def patch(self) -> dict:
        """Return only explicitly extracted updates, not null placeholders."""
        return {
            key: getattr(self, key) for key in REQUIREMENT_KEYS if getattr(self, key) is not None
        }

    def verify_sources(self, user_message: str) -> None:
        """Verify each change against a literal span from the latest user message."""
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
            elif not re.search(r"(?<![\w.,+\-])" + re.escape(value) + r"(?![\w/])", source):
                normalizer = {
                    "stock_concentration": normalize_concentration,
                    "target_concentrations": normalize_targets,
                    "final_volume": normalize_volume,
                }[key]
                if normalizer(value) != normalizer(source):
                    raise ValueError("Quantity must be equivalent to its literal source")


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


async def generate_turn(
    project: dict,
    user_message: str,
    history: list[dict[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
    settings: ModelSettings | None = None,
) -> tuple[ExtractedTurn, dict[str, int]]:
    """Call Meta once and validate its structured result before any project changes.

    Only the current project summary and a small history window are sent. The API key stays on the
    backend, and provider errors are sanitized. The caller controls project storage and retries.
    """
    settings = settings or ModelSettings.load()
    state = {
        "summary": project["summary"],
        "current_footprint_mm": project["design"]["footprint"],
        "constraint_status": project["design"]["constraint_status"],
        "current_plan": project.get("plan"),
    }
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
        "max_completion_tokens": 900,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "requirement_turn",
                "strict": True,
                "schema": ExtractedTurn.model_json_schema(),
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

    try:
        body = response.json()
        choice = body["choices"][0]
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise ValueError("incomplete model response")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("invalid message content")
        result = ExtractedTurn.model_validate_json(content)
        result.verify_sources(user_message)
    except (ValueError, TypeError, KeyError, IndexError, ValidationError):
        raise ModelClientError(
            "Meta returned an incomplete or invalid response. The project was not changed."
        ) from None

    usage = _safe_usage(body)
    # Only counts/model ID are logged; prompts, responses and authentication are omitted.
    LOGGER.info("Meta model=%s token_usage=%s", settings.model, usage)
    return result, usage
