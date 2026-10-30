"""Async visual inspection job orchestration.

Wraps ``app.vision`` (prepare_image + analyze_image) with bounded background
tasks, per-project deduplication, retention, sanitized errors and a
human-review layer. No image or prompt logging happens here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from xml.sax.saxutils import escape as _xml_escape

from app import vision
from app.model_client import active_model, using_model

MAX_RETAINED_PER_PROJECT = 3
MAX_ACTIVE_MODEL_CALLS = 2
JOB_TIMEOUT_S = 120.0
MAX_ADDITIONS_PER_REVIEW = 16
MAX_TOTAL_OBJECTS = 40

VALID_KINDS = ("tube", "pipette_tip", "tip_rack", "uncertain_labware")
VALID_CONTENTS = ("tips_visible", "empty_visible", "unknown", "not_applicable")
VALID_COMPONENTS = ("source-rack", "sample-rack", "tip-rack")
VALID_STATES = ("observed", "needs_review", "confirmed", "rejected")

_log = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_cache: dict[tuple[str, int, str, str], str] = {}
_jobs_lock = asyncio.Lock()
_model_semaphore = asyncio.Semaphore(MAX_ACTIVE_MODEL_CALLS)
_background_tasks: set[asyncio.Task] = set()

_seq = 0


class InspectionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _sanitize_error(exc: BaseException) -> str:
    _log.error("Inspection job failed (%s)", type(exc).__name__)
    return "Visual inspection failed. Retry with a clear labware photo."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_inspectable(project: dict) -> None:
    if not isinstance(project, dict) or project.get("status") not in ("draft", "confirmed"):
        raise InspectionError(409, "Inspections require a draft or confirmed project.")


def _check_coherence(project: dict, job: dict) -> None:
    if project.get("id") != job["project_id"]:
        raise InspectionError(404, "Inspection job not found for this project.")
    if project.get("revision") != job["project_revision"]:
        raise InspectionError(409, "Inspection is stale for the current project revision.")


def _public_job(job: dict) -> dict:
    result = deepcopy(job["result"]) if job.get("result") is not None else None
    if result is not None:
        result.pop("raw", None)
        result.pop("review_history", None)
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "project_revision": job["project_revision"],
        "model": job["model"],
        "status": job["status"],
        "stage": job["stage"],
        "error": job["error"],
        "result": result,
    }


def _validate_box(box: dict) -> dict:
    if not isinstance(box, dict):
        raise InspectionError(422, "Box must be an object with x_min/y_min/x_max/y_max.")
    for key in ("x_min", "y_min", "x_max", "y_max"):
        if key not in box:
            raise InspectionError(422, f"Box is missing {key}.")
        value = box[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InspectionError(422, f"Box {key} must be a number.")
        import math as _math

        if not _math.isfinite(float(value)):
            raise InspectionError(422, f"Box {key} must be finite.")
        if not 0 <= float(value) <= 1000:
            raise InspectionError(422, f"Box {key} must be within 0..1000.")
    box_f = {k: float(box[k]) for k in ("x_min", "y_min", "x_max", "y_max")}
    if not box_f["x_min"] < box_f["x_max"]:
        raise InspectionError(422, "Box requires x_min < x_max.")
    if not box_f["y_min"] < box_f["y_max"]:
        raise InspectionError(422, "Box requires y_min < y_max.")
    return box_f


def _validate_kind(kind: object) -> str:
    if kind not in VALID_KINDS:
        raise InspectionError(422, f"Unknown kind: {kind!r}.")
    return str(kind)


def _validate_contents(value: object) -> str:
    if value not in VALID_CONTENTS:
        raise InspectionError(422, f"Unknown tip_rack_contents: {value!r}.")
    return str(value)


def _normalize_component(value: object) -> str | None:
    if value is None:
        return None
    if value == "":
        return None
    if not isinstance(value, str):
        raise InspectionError(422, "component_id must be a string or null.")
    if value not in VALID_COMPONENTS:
        raise InspectionError(422, f"Unknown component_id: {value!r}.")
    return value


def _check_component_mapping(kind: str, component_id: str | None) -> None:
    if component_id is None:
        return
    if kind == "uncertain_labware":
        raise InspectionError(422, "uncertain_labware cannot map to a component.")
    if kind == "tube" and component_id not in ("source-rack", "sample-rack"):
        raise InspectionError(422, "Tubes map only to source-rack or sample-rack.")
    if kind in ("pipette_tip", "tip_rack") and component_id != "tip-rack":
        raise InspectionError(422, "Tips and tip racks map only to tip-rack.")


def _initial_state(det: dict, image_quality: str, coverage: str) -> str:
    conf = det.get("confidence")
    low_conf = conf is None or float(conf) < 0.85
    if (
        bool(det.get("uncertain"))
        or low_conf
        or image_quality in ("uncertain", "unusable")
        or coverage in ("partial", "uncertain")
        or det.get("kind") == "uncertain_labware"
        or (det.get("kind") == "tip_rack" and det.get("tip_rack_contents") == "unknown")
    ):
        return "needs_review"
    return "observed"


def _compute_presence(detections: list[dict], image_quality: str) -> dict:
    def presence_for(kind: str) -> str:
        uncertain = image_quality != "clear"
        for det in detections:
            if det["state"] == "rejected":
                continue
            relevant = det["kind"] == kind or (kind == "pipette_tip" and det["kind"] == "tip_rack")
            if not relevant:
                continue
            if det["kind"] == "tip_rack":
                if det["tip_rack_contents"] in ("unknown", "not_applicable"):
                    uncertain = True
                    continue
                if det["tip_rack_contents"] == "empty_visible":
                    continue
            if det["state"] in ("confirmed", "observed"):
                return "present"
            uncertain = True
        return "uncertain" if uncertain else "not_observed"

    return {"tubes": presence_for("tube"), "pipette_tips": presence_for("pipette_tip")}


def _build_result(
    raw: dict,
    canonical,
    model_name: str,
    usage: dict,
    project_id: str,
    job_id: str,
) -> dict:
    image_quality = raw["image_quality"]
    coverage = raw["coverage"]
    detections: list[dict] = []
    for index, det in enumerate(raw["detections"], start=1):
        state = _initial_state(det, image_quality, coverage)
        detections.append(
            {
                "id": f"det-{index:03d}",
                "kind": det["kind"],
                "label": det["label"],
                "box": dict(det["box"]),
                "confidence": det["confidence"],
                "uncertain": bool(det["uncertain"]),
                "reason": det["reason"],
                "tip_rack_contents": det["tip_rack_contents"],
                "state": state,
                "origin": "model",
                "component_id": None,
            }
        )
    presence = _compute_presence(detections, image_quality)
    return {
        "observation_version": 1,
        "image": {
            "width": int(canonical.width),
            "height": int(canonical.height),
            "sha256": str(canonical.sha256),
            "url": f"/api/projects/{project_id}/inspections/{job_id}/image",
        },
        "model": str(model_name),
        "usage": dict(usage),
        "image_quality": image_quality,
        "coverage": coverage,
        "summary": raw["summary"],
        "warnings": list(raw["warnings"]),
        "detections": detections,
        "scene_reviewed": False,
        "review_required": True,
        "presence": presence,
        "raw": deepcopy(raw),
        "review_history": [],
    }


def _prune_project(project_id: str) -> None:
    ids = [jid for jid, job in _jobs.items() if job["project_id"] == project_id]
    ids.sort(key=lambda jid: _jobs[jid]["created_seq"])
    remaining = len(ids)
    for jid in ids:
        if remaining <= MAX_RETAINED_PER_PROJECT:
            break
        job = _jobs[jid]
        if job["status"] in ("queued", "running"):
            continue
        del _jobs[jid]
        remaining -= 1
        key = (job["project_id"], job["project_revision"], job["image_sha256"], job["model"])
        if _cache.get(key) == jid:
            _cache.pop(key, None)


async def _run_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    async with _jobs_lock:
        job["status"] = "running"
        job["stage"] = "analyzing"
    canonical = job["canonical"]
    try:
        async with _model_semaphore:
            with using_model(job["model"]):
                outcome = await asyncio.wait_for(
                    vision.analyze_image(canonical), timeout=JOB_TIMEOUT_S
                )
        raw, usage = outcome
        raw = deepcopy(raw)
        model_name = usage.get("model", job["model"])
        usage = {k: v for k, v in dict(usage).items()
                 if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        usage["model"] = model_name
        raw = vision.RawInspection.model_validate(raw).model_dump()
        result = _build_result(raw, canonical, model_name, usage, job["project_id"], job_id)
        async with _jobs_lock:
            target = _jobs.get(job_id)
            if target is None or target["status"] not in ("queued", "running"):
                return
            target["result"] = result
            target["stage"] = "done"
            target["status"] = "ready"
            target["error"] = None
            _cache[(target["project_id"], target["project_revision"],
                    target["image_sha256"], target["model"])] = (
                job_id
            )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, InspectionError):
            message = exc.detail
        elif isinstance(exc, getattr(vision, "VisionError", ())):
            message = str(exc) or "Visual inspection failed. Retry with a clear labware photo."
        else:
            message = _sanitize_error(exc)
        async with _jobs_lock:
            target = _jobs.get(job_id)
            if target is None:
                return
            target["status"] = "failed"
            target["stage"] = "failed"
            target["error"] = message
            target["result"] = None
    finally:
        _prune_project(job["project_id"])


async def start_inspection(project: dict, project_revision: int, image_data_url: str) -> dict:
    global _seq
    _ensure_inspectable(project)
    if not isinstance(project_revision, int) or isinstance(project_revision, bool):
        raise InspectionError(422, "project_revision must be an integer.")
    if project_revision != project.get("revision"):
        raise InspectionError(409, "Project revision is stale.")
    if not isinstance(image_data_url, str) or not image_data_url:
        raise InspectionError(422, "image_data_url must be a non-empty string.")
    try:
        canonical = await asyncio.to_thread(vision.prepare_image, image_data_url)
    except Exception as exc:
        status = getattr(exc, "status_code", 422)
        try:
            code = int(status)
        except Exception:
            code = 422
        if code not in (400, 404, 409, 422):
            code = 422
        raise InspectionError(code, str(exc) or "Invalid image.") from None
    image_hash = str(canonical.sha256)
    model = active_model()
    async with _jobs_lock:
        for job in _jobs.values():
            if job["project_id"] != project.get("id"):
                continue
            if job["status"] in ("queued", "running"):
                if (
                    job["project_revision"] == project_revision
                    and job["image_sha256"] == image_hash
                    and job["model"] == model
                ):
                    return _public_job(job)
                raise InspectionError(
                    409, "Another inspection is already running for this project."
                )
        key = (project.get("id"), project_revision, image_hash, model)
        cached_id = _cache.get(key)
        if cached_id is not None:
            cached = _jobs.get(cached_id)
            if cached is not None and cached["status"] == "ready":
                return _public_job(cached)
            _cache.pop(key, None)
        for job in _jobs.values():
            if (
                job["project_id"] == project.get("id")
                and job["project_revision"] == project_revision
                and job["image_sha256"] == image_hash
                and job["model"] == model
                and job["status"] == "ready"
            ):
                _cache[key] = job["id"]
                return _public_job(job)
        _seq += 1
        job_id = uuid4().hex
        job = {
            "id": job_id,
            "project_id": project.get("id"),
            "project_revision": project_revision,
            "image_sha256": image_hash,
            "model": model,
            "canonical": canonical,
            "status": "queued",
            "stage": "queued",
            "error": None,
            "result": None,
            "created_seq": _seq,
        }
        _jobs[job_id] = job
    _prune_project(project.get("id"))
    task = asyncio.create_task(_run_job(job_id))
    async with _jobs_lock:
        stored = _jobs.get(job_id)
        if stored is not None:
            stored["task"] = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return _public_job(job)


async def inspection_status(project: dict, job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise InspectionError(404, "Inspection job not found.")
    _check_coherence(project, job)
    return _public_job(job)


async def inspection_image(project: dict, job_id: str) -> tuple[bytes, int, int]:
    job = _jobs.get(job_id)
    if job is None:
        raise InspectionError(404, "Inspection job not found.")
    _check_coherence(project, job)
    canonical = job["canonical"]
    return bytes(canonical.content), int(canonical.width), int(canonical.height)


def _validate_review_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise InspectionError(422, "Review body must be an object.")
    if set(payload) - {"observation_version", "scene_reviewed", "decisions", "additions"}:
        raise InspectionError(422, "Unsupported review fields.")
    observation_version = payload.get("observation_version")
    if isinstance(observation_version, bool) or not isinstance(observation_version, int):
        raise InspectionError(422, "observation_version must be an integer.")
    scene_reviewed = payload.get("scene_reviewed")
    if not isinstance(scene_reviewed, bool):
        raise InspectionError(422, "scene_reviewed must be a boolean.")
    decisions = payload.get("decisions", [])
    additions = payload.get("additions", [])
    if decisions is None:
        decisions = []
    if additions is None:
        additions = []
    if not isinstance(decisions, list) or not isinstance(additions, list):
        raise InspectionError(422, "decisions and additions must be arrays.")
    return {
        "observation_version": observation_version,
        "scene_reviewed": scene_reviewed,
        "decisions": decisions,
        "additions": additions,
    }


async def review_inspection(project: dict, job_id: str, payload: dict) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise InspectionError(404, "Inspection job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready" or job.get("result") is None:
        raise InspectionError(409, "Inspection result is not ready.")
    body = _validate_review_payload(payload)
    result = job["result"]
    if body["observation_version"] != result["observation_version"]:
        raise InspectionError(409, "Observation version is stale.")
    by_id = {d["id"]: d for d in result["detections"]}
    if len(body["additions"]) > MAX_ADDITIONS_PER_REVIEW:
        raise InspectionError(422, "At most 16 additions per review.")
    if len(result["detections"]) + len(body["additions"]) > MAX_TOTAL_OBJECTS:
        raise InspectionError(422, "At most 40 objects per inspection.")
    # Validate everything before publishing (atomic).
    parsed_decisions: list[dict] = []
    seen: set[str] = set()
    for entry in body["decisions"]:
        if not isinstance(entry, dict):
            raise InspectionError(422, "Each decision must be an object.")
        allowed = {"id", "action", "kind", "label", "box", "component_id", "tip_rack_contents"}
        unknown = set(entry) - allowed
        if unknown:
            raise InspectionError(
                422, f"Unsupported decision fields: {', '.join(sorted(unknown))}."
            )
        det_id = entry.get("id")
        action = entry.get("action")
        if det_id not in by_id:
            raise InspectionError(422, f"Unknown detection id: {det_id!r}.")
        if det_id in seen:
            raise InspectionError(422, f"Duplicate decision for {det_id!r}.")
        seen.add(det_id)
        if action not in ("accept", "reject"):
            raise InspectionError(422, "Decision action must be 'accept' or 'reject'.")
        target = by_id[det_id]
        new_kind = target["kind"]
        new_label = target["label"]
        new_box = dict(target["box"])
        new_component: str | None = target.get("component_id")
        component_touched = "component_id" in entry
        if "kind" in entry and entry["kind"] is not None:
            new_kind = _validate_kind(entry["kind"])
        if "label" in entry and entry["label"] is not None:
            label = entry["label"]
            if not isinstance(label, str) or not label.strip():
                raise InspectionError(422, "Label must be non-empty text.")
            if len(label.strip()) > 80:
                raise InspectionError(422, "Label must contain at most 80 characters.")
            new_label = label.strip()
        if "box" in entry and entry["box"] is not None:
            new_box = _validate_box(entry["box"])
        if component_touched:
            new_component = _normalize_component(entry.get("component_id"))
        if new_kind == "uncertain_labware" and new_component is not None:
            raise InspectionError(422, "uncertain_labware cannot map to a component.")
        _check_component_mapping(new_kind, new_component)
        contents = entry.get("tip_rack_contents", target["tip_rack_contents"])
        if new_kind != "tip_rack":
            contents = "not_applicable"
        elif contents == "not_applicable":
            contents = "unknown"
        contents = _validate_contents(contents)
        parsed_decisions.append(
            {
                "id": det_id,
                "action": action,
                "tip_rack_contents": contents,
                "kind": new_kind,
                "label": new_label,
                "box": new_box,
                "component_id": new_component,
            }
        )
    parsed_additions: list[dict] = []
    for entry in body["additions"]:
        if not isinstance(entry, dict):
            raise InspectionError(422, "Each addition must be an object.")
        allowed = {"kind", "label", "box", "component_id", "tip_rack_contents"}
        unknown = set(entry) - allowed
        if unknown:
            raise InspectionError(
                422, f"Unsupported addition fields: {', '.join(sorted(unknown))}."
            )
        if "kind" not in entry or "label" not in entry or "box" not in entry:
            raise InspectionError(422, "Additions require kind, label and box.")
        kind = _validate_kind(entry["kind"])
        label = entry["label"]
        if not isinstance(label, str) or not label.strip():
            raise InspectionError(422, "Addition label must be non-empty text.")
        if len(label.strip()) > 80:
            raise InspectionError(422, "Addition label must contain at most 80 characters.")
        box = _validate_box(entry["box"])
        component_id = _normalize_component(entry.get("component_id"))
        _check_component_mapping(kind, component_id)
        contents = (
            entry.get("tip_rack_contents") or "unknown" if kind == "tip_rack" else "not_applicable"
        )
        contents = _validate_contents(contents)
        parsed_additions.append(
            {
                "kind": kind,
                "label": label.strip(),
                "box": box,
                "component_id": component_id,
                "tip_rack_contents": contents,
            }
        )
    # Apply atomically.
    new_detections = deepcopy(result["detections"])
    index = {d["id"]: d for d in new_detections}
    for parsed in parsed_decisions:
        det = index[parsed["id"]]
        det["kind"] = parsed["kind"]
        det["label"] = parsed["label"]
        det["box"] = parsed["box"]
        det["component_id"] = parsed["component_id"]
        det["state"] = "confirmed" if parsed["action"] == "accept" else "rejected"
        det["tip_rack_contents"] = parsed["tip_rack_contents"]
        det["origin"] = (
            "human"
            if parsed["action"] == "accept"
            and det["origin"] == "model"
            and (
                parsed["kind"] != by_id[parsed["id"]]["kind"]
                or parsed["label"] != by_id[parsed["id"]]["label"]
                or parsed["box"] != by_id[parsed["id"]]["box"]
            )
            else det["origin"]
        )
    existing_manual = sum(1 for d in new_detections if d["id"].startswith("manual-"))
    if existing_manual + len(parsed_additions) > 16:
        raise InspectionError(422, "At most 16 manually added objects per inspection.")
    for offset, parsed in enumerate(parsed_additions, start=1):
        manual_id = f"manual-{existing_manual + offset:03d}"
        new_detections.append(
            {
                "id": manual_id,
                "kind": parsed["kind"],
                "label": parsed["label"],
                "box": parsed["box"],
                "confidence": None,
                "uncertain": False,
                "reason": "Added by human reviewer.",
                "tip_rack_contents": parsed["tip_rack_contents"],
                "state": "confirmed",
                "origin": "human",
                "component_id": parsed["component_id"],
            }
        )
    pending = [d for d in new_detections if d["state"] in ("observed", "needs_review")]
    if body["scene_reviewed"] and pending:
        raise InspectionError(422, "Resolve every object before final scene review.")
    new_scene = bool(body["scene_reviewed"]) and not pending
    # Any correction resets an old scene review unless this same review finalizes it.
    result["detections"] = new_detections
    result["scene_reviewed"] = new_scene
    result["presence"] = _compute_presence(new_detections, result["image_quality"])
    still_pending = bool(pending)
    result["review_required"] = bool(still_pending or not new_scene)
    result["observation_version"] = int(result["observation_version"]) + 1
    result.setdefault("review_history", []).append(
        {
            "observation_version": int(result["observation_version"]),
            "timestamp": _utc_now(),
            "scene_reviewed": new_scene,
            "decisions": deepcopy(body["decisions"]),
            "additions": deepcopy(body["additions"]),
        }
    )
    return _public_job(job)


def build_svg(
    canonical_width: int, canonical_height: int, detections: list[dict], content: bytes
) -> str:
    """Self-contained photo with numbered boxes and a separate readable legend."""
    height = round(1000 * canonical_height / canonical_width)
    rows = (len(detections) + 2) // 3
    total_height = height + 88 + rows * 46
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 1000 {total_height}" role="img" '
        'aria-label="Photo inspection with numbered regions and legend">'
        "<style>text{font-family:Arial,sans-serif}</style>"
        f'<rect width="1000" height="{total_height}" fill="#f5faf9"/>'
    ]
    encoded = base64.b64encode(content).decode("ascii")
    parts.append(f'<image width="1000" height="{height}" href="data:image/jpeg;base64,{encoded}"/>')
    for number, det in enumerate(detections, 1):
        box = det["box"]
        x, y = box["x_min"], box["y_min"] * height / 1000
        w = box["x_max"] - x
        h = (box["y_max"] - box["y_min"]) * height / 1000
        color = {"confirmed": "#087d7d", "rejected": "#ac4444"}.get(det["state"], "#b77909")
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="2"/>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="30" height="22" rx="3" fill="{color}"/>'
            f'<text x="{x + 15:.1f}" y="{y + 16:.1f}" text-anchor="middle" '
            f'font-size="14" fill="white">{number}</text>'
        )
        lx, ly = 24 + ((number - 1) % 3) * 328, height + 77 + ((number - 1) // 3) * 46
        label = _xml_escape(det["label"][:33])
        parts.append(
            f'<text x="{lx}" y="{ly}" font-size="14" fill="#244e56">{number}. {label}</text>'
            f'<text x="{lx}" y="{ly + 17}" font-size="11" fill="{color}">'
            f"{det['id']} / {det['state']}</text>"
        )
    parts.append(
        f'<text x="24" y="{height + 32}" font-size="21" fill="#244e56">Labware inspection</text>'
        f'<text x="24" y="{height + 50}" font-size="12" fill="#5a7577">'
        "Image regions only. Uncalibrated observations; human decisions are recorded separately."
        "</text></svg>"
    )
    return "".join(parts)


async def inspection_archive(
    project: dict, job_id: str, observation_version: int | None
) -> tuple[bytes, str]:
    job = _jobs.get(job_id)
    if job is None:
        raise InspectionError(404, "Inspection job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready" or job.get("result") is None:
        raise InspectionError(409, "Inspection result is not ready.")
    result = deepcopy(job["result"])
    history = list(result.get("review_history", []))
    if observation_version is not None and observation_version != result["observation_version"]:
        raise InspectionError(409, "Observation version is stale. Download the current report.")
    result["project_id"] = job["project_id"]
    result["project_revision"] = job["project_revision"]
    result["inspection_id"] = job["id"]
    canonical = job["canonical"]
    detections = result.get("detections", [])
    svg = build_svg(int(canonical.width), int(canonical.height), detections, canonical.content)
    inspection_doc = deepcopy(result)
    files: dict[str, bytes] = {
        "image.jpg": bytes(canonical.content),
        "annotated.svg": svg.encode("utf-8"),
        "inspection.json": json.dumps(inspection_doc, indent=2).encode("utf-8"),
        "review-history.json": json.dumps(history, indent=2).encode("utf-8"),
        "README.md": (
            "# Visual inspection export\n\n"
            f"Project {job['project_id']}, revision {job['project_revision']}, "
            f"observation {result['observation_version']}.\n\n"
            "Photo-based labware assessment. Assessment scores are uncalibrated.\n"
            "image.jpg is the exact metadata-free input analyzed by the model.\n"
            "annotated.svg embeds that image and current reviewed boxes.\n"
            "inspection.json preserves raw model observations and current results.\n"
            "review-history.json records human decisions, corrections and additions.\n"
            "Human associations are labels, not calibrated registration.\n"
            "No hardware, fluid or concentration measurement is performed.\n"
            "Positions are normalized 0..1000 image coordinates, never world/mm.\n"
            "No absence is claimed from an empty detection list.\n\n"
            "## Photograph attribution\n\n"
            "If this is the bundled laboratory example, the photo is by Gannu03,\n"
            "Laboratory microcentrifuge tubes and pipette tips 01, dated 2025-12-11.\n"
            "Source: https://commons.wikimedia.org/wiki/"
            "File:Laboratory_microcentrifuge_tubes_and_pipette_tips_01.jpg\n"
            "License: https://creativecommons.org/licenses/by-sa/4.0/ .\n"
            "The example was resized/recompressed, metadata removed and boxes added;\n"
            "the photograph and its adaptations remain under CC BY-SA 4.0.\n"
            "This attribution does not assign that license to other uploaded photos\n"
            "or to the surrounding software. It is not MuseAutoLab hardware.\n"
        ).encode("utf-8"),
    }
    manifest = {name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    filename = f"inspection-{job_id}-v{result.get('observation_version')}.zip"
    return buffer.getvalue(), filename
