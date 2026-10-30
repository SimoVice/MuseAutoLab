"""Engineer-style platform discovery for ordinary chat.

Ordinary chat collects needs, proposes sourced alternatives, receives the user
platform choice, then designs. No automatic Jubilee adoption happens here.

The parent supplies profile facts and links; this module never invents prices,
suppliers, geometry, compatibility, or descriptions. It only tracks
user-grounded requirements, staged Meta proposals, and explicit user choice.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PlatformId = Literal["jubilee", "opentrons-ot2"]
RequirementField = Literal["procurement", "budget", "throughput", "assembly", "priorities"]
REQUIREMENT_FIELDS: tuple[str, ...] = (
    "procurement",
    "budget",
    "throughput",
    "assembly",
    "priorities",
)
PROCUREMENT_VALUES: tuple[str, ...] = ("prebuilt", "open_hardware")
PLATFORM_PROCUREMENT: dict[str, str] = {
    "jubilee": "open_hardware",
    "opentrons-ot2": "prebuilt",
}

Text600 = Annotated[str, Field(min_length=1, max_length=600)]
Text1000 = Annotated[str, Field(min_length=1, max_length=1000)]
Tradeoff = Annotated[str, Field(min_length=1, max_length=300)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EngineeringOption(StrictModel):
    platform_id: PlatformId
    reason: Text600
    tradeoffs: Annotated[list[Tradeoff], Field(max_length=4)]


class EngineeringRequirement(StrictModel):
    field: RequirementField
    value: Annotated[Text1000, Field(description=(
        "For procurement use only prebuilt or open_hardware. For every other field, "
        "copy the user's literal text. Never put a descriptive procurement phrase here."
    ))]
    source: Text1000

    @model_validator(mode="after")
    def _literal_procurement_alias(self) -> EngineeringRequirement:
        # A closed alias vocabulary repairs a field-format error, never a platform choice.
        # The literal source is still checked against the latest message before application.
        aliases = {
            "open hardware": "open_hardware", "open-hardware": "open_hardware",
            "open-source": "open_hardware", "buildable open-hardware route": "open_hardware",
            "buy assembled": "prebuilt", "pre-built": "prebuilt",
            "assembled platform": "prebuilt",
        }
        if self.field == "procurement" and self.value.casefold() == self.source.casefold():
            self.value = aliases.get(self.value.casefold(), self.value)
        return self


class EngineeringUpdate(StrictModel):
    requirements: Annotated[list[EngineeringRequirement], Field(max_length=5)] = []
    options: Annotated[list[EngineeringOption], Field(max_length=2)] = []
    platform_choice: PlatformId | None = None
    choice_source: Text1000 | None = None

    @model_validator(mode="after")
    def _consistent_choice(self) -> EngineeringUpdate:
        if self.platform_choice is None and self.choice_source is not None:
            # Non-operative evidence must not break an unrelated quantity update.
            # This never creates a choice or weakens the source checks for one.
            self.choice_source = None
        return self

    def verify_sources(self, message: object, project: object) -> None:
        """Raise ValueError unless the update is grounded in the latest message."""
        if not isinstance(message, str) or not message:
            raise ValueError("A latest user message is required.")
        if not isinstance(project, dict):
            raise ValueError("A project mapping is required.")
        seen_fields: set[str] = set()
        for requirement in self.requirements:
            if requirement.field in seen_fields:
                raise ValueError(f"Duplicate requirement field: {requirement.field}.")
            seen_fields.add(requirement.field)
            if requirement.source not in message:
                raise ValueError(
                    f"Requirement source is not in the latest message: {requirement.field}."
                )
            if _looks_like_url(requirement.source) or _looks_like_url(requirement.value):
                raise ValueError("Arbitrary URLs are not accepted as requirements.")
            if requirement.field == "procurement":
                if requirement.value not in PROCUREMENT_VALUES:
                    raise ValueError("procurement must be prebuilt or open_hardware.")
            elif requirement.value.strip().lower() not in requirement.source.strip().lower():
                raise ValueError(
                    f"Requirement value is not in its source span: {requirement.field}."
                )
        seen_options: set[str] = set()
        for option in self.options:
            if option.platform_id in seen_options:
                raise ValueError(f"Duplicate option platform: {option.platform_id}.")
            seen_options.add(option.platform_id)
            if _looks_like_url(option.reason) or any(_looks_like_url(t) for t in option.tradeoffs):
                raise ValueError("Arbitrary URLs are not accepted as options.")
        if self.platform_choice is None:
            return
        if self.choice_source is None or self.choice_source not in message:
            raise ValueError("Choice needs its literal source in the latest message.")
        if _looks_like_url(self.choice_source):
            raise ValueError("Arbitrary URLs are not accepted as choice sources.")
        previous = _previous_option_ids(project)
        if not _message_selects_platform(message, self.platform_choice, previous):
            raise ValueError("The latest message does not actually select that platform.")


class EngineeringState(StrictModel):
    schema_version: Literal["1"] = "1"
    requirements: dict[str, str | None]
    options: Annotated[list[EngineeringOption], Field(max_length=2)] = []
    selected_platform_id: PlatformId | None = None
    selection_source: Annotated[str, Field(max_length=1000)] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> EngineeringState:
        if set(self.requirements.keys()) != set(REQUIREMENT_FIELDS):
            raise ValueError("requirements must contain exactly the five supported fields.")
        procurement = self.requirements.get("procurement")
        if procurement not in (None, *PROCUREMENT_VALUES):
            raise ValueError("procurement must be prebuilt, open_hardware, or null.")
        for key, value in self.requirements.items():
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"Requirement {key} must be text or null.")
        if self.selection_source is not None and (
            not self.selection_source or _looks_like_url(self.selection_source)
        ):
            raise ValueError("selection_source must be plain text without URLs.")
        if self.selected_platform_id is None and self.selection_source is not None:
            raise ValueError("selection_source requires a selected platform.")
        return self


def _empty_state() -> dict:
    return {
        "schema_version": "1",
        "requirements": {name: None for name in REQUIREMENT_FIELDS},
        "options": [],
        "selected_platform_id": None,
        "selection_source": None,
    }


def state_for(project: object) -> dict:
    """Return fresh JSON-safe engineering state; never infer selection from CAD."""
    if not isinstance(project, dict):
        return _empty_state()
    stored = project.get("engineering")
    if stored is None:
        return _empty_state()
    try:
        validated = EngineeringState.model_validate(deepcopy(stored))
    except Exception:
        return _empty_state()
    return validated.model_dump()


def _looks_like_url(text: str) -> bool:
    lowered = text.lower()
    return (
        "http://" in lowered
        or "https://" in lowered
        or "www." in lowered
        or "href=" in lowered
        or "<a " in lowered
    )


def _previous_option_ids(project: dict) -> list[str]:
    try:
        state = state_for(project)
    except Exception:
        return []
    ids: list[str] = []
    for option in state.get("options", []):
        platform = option.get("platform_id") if isinstance(option, dict) else None
        if platform in ("jubilee", "opentrons-ot2"):
            ids.append(platform)
    return ids


def _mentions(platform: str, lowered: str) -> bool:
    if platform == "jubilee":
        return "jubilee" in lowered
    return "opentrons" in lowered or "ot-2" in lowered or "ot2" in lowered


def _mentions_procurement(route: str, lowered: str) -> bool:
    if route == "open_hardware":
        return any(
            token in lowered
            for token in (
                "open_hardware",
                "open hardware",
                "open-source",
                "open source",
                "buildable",
                "da assemblare",
                "costruibile",
                "fai-da-te",
            )
        )
    return any(
        token in lowered
        for token in (
            "prebuilt",
            "pre-built",
            "already assembled",
            "already-assembled",
            "ready-to-use",
            "ready to use",
            "ready-made",
            "ready made",
            "assemblata",
            "assemblato",
            "assembled",
        )
    )


def _has_choice_verb(lowered: str) -> bool:
    return bool(
        re.search(
            r"\b(?:choose|select|go with|go for|prefer|opt for|confirm|"
            r"proceed|design|build|start with|pick|take|use|let's|lets|"
            r"scelgo|scegli|preferisco|voglio|vorrei|prendo|opto|confermo|"
            r"procedi|procediamo|usiamo|usa)\b",
            lowered,
        )
    )


def _has_ordinal(text: str, lowered: str) -> str | None:
    _ = text
    if any(
        token in lowered
        for token in (
            "second option",
            "seconda opzione",
            "option 2",
            "opzione 2",
            "number 2",
            "n. 2",
        )
    ):
        return "second"
    if any(
        token in lowered
        for token in ("first option", "prima opzione", "option 1", "opzione 1", "number 1", "n. 1")
    ):
        return "first"
    return None


def _is_yes_only(lowered: str) -> bool:
    stripped = lowered.strip().strip("!.,;:").strip()
    if stripped in (
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "go",
        "confirmed",
        "confirm",
        "do it",
        "sì",
        "si",
        "confermo",
        "conferma",
        "procedi",
        "procediamo",
        "va bene",
        "perfetto",
    ):
        return True
    return any(
        phrase in lowered
        for phrase in (
            "sounds good",
            "let's do it",
            "lets do it",
            "go ahead",
            "yes, proceed",
            "yes proceed",
            "sì, proced",
            "si, proced",
            "va bene, proced",
            "ok proced",
        )
    )


def _is_question_only(lowered: str, choice: str) -> bool:
    if re.search(
        r"^\s*(?:should i|would you recommend|do you recommend|is it better|"
        r"which|dovrei|mi consigli|consiglieresti|è meglio|e meglio)\b", lowered
    ):
        return True
    if not _mentions(choice, lowered):
        return False
    question_markers = (
        "what is",
        "what's",
        "what are",
        "how does",
        "tell me",
        "cos'è",
        "cosa è",
        "che cos'è",
        "come funziona",
        "che cosa",
    )
    if any(marker in lowered for marker in question_markers) and not _has_choice_verb(lowered):
        return True
    return False


def _is_negated_or_future(lowered: str, choice: str) -> bool:
    future_markers = (
        "in the future",
        "in future",
        "later",
        "one day",
        "next month",
        "next year",
        "might later",
        "maybe later",
        "in futuro",
        "più avanti",
        "piu avanti",
        "un giorno",
        "forse",
        "maybe",
        "perhaps",
        "not yet",
        "non ancora",
        "thinking about",
        "considering",
    )
    if any(marker in lowered for marker in future_markers):
        return True
    negated_choice = (
        "don't choose",
        "do not choose",
        "don't want",
        "do not want",
        "not jubilee",
        "no jubilee",
        "avoid jubilee",
        "don't use",
        "do not use",
        "never",
        "non voglio",
        "non scelgo",
        "non usiamo",
        "non usare",
        "evita",
        "mai",
        "won't",
        "will not",
    )
    negated_single = (
        "don't",
        "do not",
        "not use",
        "not choose",
        "not select",
        "won't",
        "will not",
        "never",
        "non voglio",
        "non scelgo",
        "non us",
        "evita",
        "mai",
        "no jubilee",
        "not jubilee",
        "no opentrons",
        "not opentrons",
    )
    if _mentions(choice, lowered) and any(t in lowered for t in negated_single):
        # "I prefer X, not Y" disambiguation is handled by the caller when both
        # platforms are named; a single named platform with negation never selects.
        other = "opentrons-ot2" if choice == "jubilee" else "jubilee"
        if not _mentions(other, lowered):
            return True
    if choice == "jubilee":
        relevant = [
            t
            for t in negated_choice
            if "jubilee" in t
            or t in ("don't want", "do not want", "non voglio", "never", "won't", "will not", "mai")
        ]
        mention_negated = any(t in lowered for t in relevant) and _mentions(choice, lowered)
        if mention_negated:
            return True
        if (
            ("not " in lowered or "n't" in lowered or " non " in f" {lowered} ")
            and _mentions(choice, lowered)
            and not _has_choice_verb(lowered)
        ):
            return True
    else:
        relevant = [
            t
            for t in (
                "don't choose",
                "do not choose",
                "don't want",
                "do not want",
                "not opentrons",
                "no opentrons",
                "avoid opentrons",
                "don't use",
                "do not use",
                "never",
                "non voglio",
                "non scelgo",
                "non usiamo",
                "evita",
                "mai",
                "won't",
                "will not",
            )
        ]
        if any(t in lowered for t in relevant) and _mentions(choice, lowered):
            return True
    if lowered.strip().startswith(("no", "non ")) and _mentions(choice, lowered):
        return True
    return False


def _message_selects_platform(message: str, choice: str, previous: list[str]) -> bool:
    lowered = message.lower()
    short_answer = (
        len(message) <= 120
        and "?" not in message
        and not re.search(
            r"\b(?:explain|compare|what|why|how|tell me|spiega|parlami|confronta|quale)\b", lowered
        )
    )
    if _is_question_only(lowered, choice):
        return False
    if _is_negated_or_future(lowered, choice):
        return False
    other = "opentrons-ot2" if choice == "jubilee" else "jubilee"
    mentions_choice = _mentions(choice, lowered)
    mentions_other = _mentions(other, lowered)
    if mentions_choice and mentions_other:
        # Require an explicit preference for the chosen platform.
        preference = (
            f"prefer {choice}" in lowered
            or "rather than" in lowered
            or "instead of" in lowered
            or "invece di" in lowered
            or "piuttosto" in lowered
            or f"go with {choice}" in lowered
        )
        named = choice in lowered or (
            "ot2" in lowered or "ot-2" in lowered or "opentrons" in lowered
        )
        if not (preference and named):
            # Allow "X, not Y" style disambiguation.
            if not (
                mentions_choice
                and ("not " in lowered or "non " in lowered)
                and _has_choice_verb(lowered)
            ):
                return False
    if mentions_choice and (_has_choice_verb(lowered) or (choice in previous and short_answer)):
        return True
    route = PLATFORM_PROCUREMENT[choice]
    other_route = PLATFORM_PROCUREMENT[other]
    mentions_route = _mentions_procurement(route, lowered)
    mentions_other_route = _mentions_procurement(other_route, lowered)
    if mentions_route and not mentions_other_route and (_has_choice_verb(lowered) or short_answer):
        matching = [pid for pid in previous if PLATFORM_PROCUREMENT.get(pid) == route]
        if len(matching) == 1 and matching[0] == choice:
            return True
    ordinal = _has_ordinal(message, lowered)
    if ordinal is not None and previous:
        index = 0 if ordinal == "first" else 1
        if len(previous) > index and previous[index] == choice:
            if (
                "option" in lowered
                or "opzione" in lowered
                or _has_choice_verb(lowered)
                or _is_yes_only(lowered)
            ):
                return True
        return False
    if _is_yes_only(lowered) and len(previous) == 1 and previous[0] == choice:
        if not mentions_other and not mentions_other_route:
            return True
    return False


def apply_engineering_update(
    project: dict,
    update: EngineeringUpdate,
    message: str,
    bump: bool = True,
) -> dict:
    """Apply a verified engineering update without touching design artefacts."""
    if not isinstance(project, dict):
        raise ValueError("A project mapping is required.")
    if not isinstance(update, EngineeringUpdate):
        raise ValueError("An EngineeringUpdate is required.")
    update.verify_sources(message, project)
    result = deepcopy(project)
    before = state_for(result)
    requirements = dict(before["requirements"])
    for requirement in update.requirements:
        requirements[requirement.field] = requirement.value
    options = before["options"]
    if update.options:
        options = [option.model_dump() for option in update.options]
    selected = before["selected_platform_id"]
    selection_source = before["selection_source"]
    if update.platform_choice is not None:
        selected = update.platform_choice
        selection_source = update.choice_source
    after = {
        "schema_version": "1",
        "requirements": requirements,
        "options": deepcopy(options),
        "selected_platform_id": selected,
        "selection_source": selection_source,
    }
    # Validate the merged state before storing it.
    EngineeringState.model_validate(after)
    if after == before:
        return result
    result["engineering"] = deepcopy(after)
    if bump:
        try:
            result["revision"] = int(result.get("revision", 0)) + 1
        except (TypeError, ValueError):
            result["revision"] = 1
    result["status"] = "draft"
    return result


__all__ = [
    "EngineeringOption",
    "EngineeringRequirement",
    "EngineeringState",
    "EngineeringUpdate",
    "apply_engineering_update",
    "state_for",
]
