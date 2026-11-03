"""Local concept sequence preview and explicit device-integration boundary.

Run: python controller.py project.json --simulate
Project JSON is data, never imported Python code. Default simulation opens no
device connection. Gateway mode sends separately configured commands only after
explicit hardware arming and the requested typed confirmation.
"""

from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class DeviceAdapter(Protocol):
    """Implement these methods in a separately reviewed, device-specific integration.

    prepare must check identity, limits, homing/calibration and stop/recovery behavior.
    perform maps a logical step to calibrated device commands, never preview millimetres.
    stop must be safe to call after partial preparation or a failed operation.
    """

    def prepare(self, project: dict) -> None: ...
    def perform(self, step: dict) -> dict: ...
    def stop(self) -> None: ...


class SimulationAdapter:
    """Record logical steps; do not open a port or move equipment."""

    def prepare(self, project: dict) -> None:
        self.project = project

    def perform(self, step: dict) -> dict:
        return {
            "step": step["name"],
            "status": "simulated",
            "instruction": step["instruction"],
            "component_names": step.get("component_names", []),
            "preview_translation_mm": step.get("translation_mm", [0, 0, 0]),
            "preview_rotation_deg": step.get("rotation_deg", 0),
            "preview_rotation_start_deg": step.get("start_rotation_deg", 0),
            "preview_rotation_delta_deg": step.get(
                "rotation_delta_deg", step.get("rotation_deg", 0)
            ),
            "preview_motion_mode": (
                "indexed_rotation"
                if step.get("index_chain")
                else "out_and_back"
                if step.get("moving_key")
                else "operator_prompt"
            ),
            "index_station": step.get("index_station"),
            "planned_travel_stops": step.get("stops", []),
            "preview_rotation_axis": step.get("rotation_axis"),
            "preview_pivot_mm": step.get("pivot_mm"),
            "scope": "Logical schedule only; no physics, collision or hardware validation.",
        }

    def stop(self) -> None:
        pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Device gateways must not redirect commands.")


class HttpGatewayAdapter:
    """Real, opt-in JSON/HTTP gateway integration, not a vendor device driver.

    A separately implemented gateway must validate device limits, interlocks and
    idempotency by request_id, reject stale project revisions, and acknowledge
    prepare/execute/stop only when the action has completed. A software stop
    request cannot replace an independent physical emergency-stop circuit.
    """

    def __init__(self, config: dict, *, armed: bool = False):
        if not isinstance(config, dict):
            raise ValueError("Gateway configuration must be a JSON object.")
        self.config = deepcopy(config)
        if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
            raise ValueError("Use a gateway configuration with schema version 1.")
        self.armed = armed
        self.prepared = False
        self.stop_required = False
        self.opener = build_opener(_NoRedirect())
        base = str(config.get("base_url", "http://127.0.0.1:8787")).rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Gateway base_url must be an HTTP(S) origin without credentials.")
        self.base_url = base
        self.timeout = config.get("timeout_seconds", 5)
        if (
            isinstance(self.timeout, bool)
            or not isinstance(self.timeout, (int, float))
            or not math.isfinite(self.timeout)
            or not 0 < self.timeout <= 30
        ):
            raise ValueError("Gateway timeout must be greater than zero and at most 30 seconds.")

    def _request(self, endpoint: str, content: dict, expected: str) -> dict:
        request_id = str(uuid4())
        body = {
            "schema_version": 1,
            "request_id": request_id,
            "device_id": self.config["device_id"],
            "project_id": self.config["project_id"],
            "revision": self.config["revision"],
            **content,
        }
        request = Request(
            f"{self.base_url}/{endpoint}",
            method="POST",
            data=json.dumps(body, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(65537)
                if response.status != 200 or len(raw) > 65536:
                    raise ValueError("Gateway response is invalid or too large.")
                result = json.loads(raw)
        except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
            raise ValueError("Gateway command failed; check the device and gateway log.") from exc
        if (
            not isinstance(result, dict)
            or result.get("accepted") is not True
            or result.get("request_id") != request_id
            or result.get("device_id") != self.config["device_id"]
            or result.get("project_id") != self.config["project_id"]
            or result.get("revision") != self.config["revision"]
            or type(result.get("revision")) is not int
            or result.get("status") != expected
        ):
            raise ValueError(
                "Gateway acknowledgement did not match the device, revision or action."
            )
        return result

    def prepare(self, project: dict) -> None:
        if not self.armed or self.config.get("commissioning_reviewed") is not True:
            raise ValueError("Review commissioning and explicitly arm the gateway before use.")
        if any(self.config.get(key) != project.get(key) for key in ("project_id", "revision")):
            raise ValueError("Gateway configuration belongs to another project revision.")
        if type(self.config.get("revision")) is not int:
            raise ValueError("The gateway revision must be a whole number.")
        if (
            not isinstance(self.config.get("device_id"), str)
            or not self.config["device_id"].strip()
        ):
            raise ValueError("Specify the commissioned device identity.")
        actions = self.config.get("actions")
        step_names = [step["name"] for step in project["design"]["steps"]]
        if (
            len(step_names) != len(set(step_names))
            or not isinstance(actions, dict)
            or set(actions) != set(step_names)
        ):
            raise ValueError("Map each uniquely named sequence step exactly once.")
        for action in actions.values():
            if (
                not isinstance(action, dict)
                or not isinstance(action.get("action"), str)
                or not action["action"].strip()
                or not isinstance(action.get("parameters"), dict)
                or set(action) != {"action", "parameters"}
            ):
                raise ValueError("Each step needs a reviewed action and explicit parameters.")
            json.dumps(action, allow_nan=False)
        self.stop_required = True
        self._request("prepare", {}, "ready")
        self.prepared = True

    def perform(self, step: dict) -> dict:
        if not self.prepared:
            raise ValueError("The gateway is not ready; no command was sent.")
        mapping = self.config["actions"].get(step["name"])
        if mapping is None:
            raise ValueError("This step has no commissioned device mapping.")
        return self._request("execute", {"step_name": step["name"], **mapping}, "completed")

    def stop(self) -> None:
        self.prepared = False
        if self.stop_required:
            self.stop_required = False
            self._request("stop", {}, "stopped")


def load_project(path: str | Path) -> dict:
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("Project file is too large; use the downloaded concept project.")
    project = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(project, dict) or not isinstance(project.get("design"), dict):
        raise ValueError("Expected a downloaded project containing a design.")
    revision = project.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Project revision must be a nonnegative integer.")
    if not isinstance(project.get("project_id"), str) or not project["project_id"]:
        raise ValueError("Project identity is missing.")
    design = project["design"]
    parts = design.get("components")
    steps = design.get("steps")
    if not isinstance(parts, list) or not parts or not isinstance(steps, list) or not steps:
        raise ValueError("The project needs components and an ordered sequence.")
    if len(parts) > 100 or len(steps) > 200:
        raise ValueError("The project exceeds the supported local preview size.")
    keys, step_names = set(), set()
    for part in parts:
        if (
            not isinstance(part, dict)
            or not isinstance(part.get("key"), str)
            or not part["key"].strip()
        ):
            raise ValueError("Each component needs a key.")
        if part["key"] in keys:
            raise ValueError("Component keys must be unique.")
        keys.add(part["key"])
    previous_step = None
    for step in steps:
        if not isinstance(step, dict) or not all(
            isinstance(step.get(field), str) and step[field].strip()
            for field in ("name", "instruction")
        ):
            raise ValueError("Each sequence step needs a name and instruction.")
        if step["name"].casefold() in step_names:
            raise ValueError("Give every sequence step a distinct name.")
        step_names.add(step["name"].casefold())
        ids = step.get("component_keys", [])
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(key, str) or key not in keys for key in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValueError("A sequence step refers to an unknown component.")
        moving = step.get("moving_key")
        if moving is not None and (not isinstance(moving, str) or moving not in ids):
            raise ValueError("A moving component is missing from this project.")
        vector = step.get("translation_mm", [0, 0, 0])
        if (
            not isinstance(vector, list)
            or len(vector) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            )
        ):
            raise ValueError("Preview translations must contain three finite millimetre values.")
        angle = step.get("rotation_deg", 0)
        if (
            isinstance(angle, bool)
            or not isinstance(angle, (int, float))
            or not math.isfinite(angle)
            or abs(angle) > 180
        ):
            raise ValueError("Preview rotation must be finite and within 180 degrees.")
        if step.get("rotation_axis") not in (None, "x", "y", "z"):
            raise ValueError("Preview rotation axis must be x, y or z.")
        if angle and (not moving or not step.get("rotation_axis") or step.get("pivot_mm") is None):
            raise ValueError("A rotation needs a moving component, an axis and a local pivot.")
        pivot = step.get("pivot_mm")
        if pivot is not None and (
            not isinstance(pivot, list)
            or len(pivot) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in pivot
            )
        ):
            raise ValueError("A local pivot needs three finite millimetre values.")
        if (step.get("rotation_axis") is None) != (pivot is None):
            raise ValueError("Specify a rotation axis and local pivot together.")
        stops = step.get("stops", [])
        if (
            not isinstance(stops, list)
            or len(stops) > 12
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in stops
            )
            or any(b <= a for a, b in zip(stops, stops[1:]))
        ):
            raise ValueError("Planned pauses must be increasing travel fractions from zero to one.")
        if stops and moving is None:
            raise ValueError("Planned travel pauses require a moving component.")
        reference = step.get("rotation_reference", "from_rest")
        if reference not in ("from_rest", "previous_index"):
            raise ValueError("Use a known rotary reference for each step.")
        if "index_chain" in step and type(step["index_chain"]) is not bool:
            raise ValueError("An indexed movement flag must be true or false.")
        if step.get("index_chain") or reference == "previous_index":
            start = step.get("start_rotation_deg", 0)
            delta = step.get("rotation_delta_deg", angle)
            if (
                any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    or abs(v) > 180
                    for v in (start, delta)
                )
                or moving is None
                or step.get("rotation_axis") is None
                or pivot is None
                or any(vector)
            ):
                raise ValueError("Indexed movement needs bounded angles and a rotary part only.")
            if not math.isclose((start + delta - angle + 180) % 360 - 180, 0, abs_tol=1e-7):
                raise ValueError(
                    "The indexed start and travel do not match the recorded final pose."
                )
            if reference == "previous_index" and (
                previous_step is None
                or not previous_step.get("index_chain")
                or not step.get("index_chain")
                or previous_step.get("moving_key") != moving
                or previous_step.get("rotation_axis") != step.get("rotation_axis")
                or previous_step.get("pivot_mm") != pivot
                or any(previous_step.get("translation_mm", [0, 0, 0]))
                or not math.isclose(start, previous_step.get("rotation_deg", 0), abs_tol=1e-7)
            ):
                raise ValueError(
                    "An indexed step must continue the preceding matching rotary pose."
                )
        previous_step = step
    return project


def run_sequence(
    project: dict, adapter: DeviceAdapter | None = None, *, commissioned: bool = False
) -> dict:
    """Default to simulation. A real adapter requires explicit commissioning approval.

    The flag is an integration guard, never evidence that commissioning occurred.
    Store actual configuration and acceptance results outside this logical preview.
    """
    device = adapter if adapter is not None else SimulationAdapter()
    simulation = isinstance(device, SimulationAdapter)
    if not simulation and not commissioned:
        raise ValueError("Review and commission the device integration before enabling hardware.")
    events = []
    try:
        device.prepare(project)
        for step in project["design"]["steps"]:
            events.append(device.perform(step))
    finally:
        device.stop()
    return {
        "project_id": project["project_id"],
        "revision": project["revision"],
        "mode": "simulation" if simulation else "external_device_adapter",
        "events": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Downloaded project.json from the same revision")
    parser.add_argument(
        "--simulate", action="store_true", help="Print the logical schedule (default)"
    )
    parser.add_argument("--gateway-config", help="Reviewed JSON/HTTP device integration mapping")
    parser.add_argument(
        "--arm-hardware",
        action="store_true",
        help="Request hardware mode; also requires a typed confirmation",
    )
    args = parser.parse_args()
    try:
        project = load_project(args.project)
        if args.gateway_config or args.arm_hardware:
            if args.simulate or not (args.gateway_config and args.arm_hardware):
                raise ValueError("Hardware requires --gateway-config and --arm-hardware together.")
            config = json.loads(Path(args.gateway_config).read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("Gateway configuration must be a JSON object.")
            phrase = f"ARM {project['project_id']} r{project['revision']}"
            print(
                "Hardware mode sends real gateway commands. Verify a clear setup and stop access."
            )
            if input(f"Type {phrase} to continue: ") != phrase:
                raise ValueError("Hardware arming was not confirmed; no command was sent.")
            result = run_sequence(
                project, HttpGatewayAdapter(config, armed=True), commissioned=True
            )
        else:
            result = run_sequence(project)
    except KeyboardInterrupt:
        parser.exit(130, "Run interrupted. If hardware was started, verify its stopped state.\n")
    except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
        parser.exit(2, f"Cannot run this project: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
