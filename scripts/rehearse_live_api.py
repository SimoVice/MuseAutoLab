"""Bounded, opt-in Meta rehearsal using synthetic needs through the real local API.

Without --live this prints the scenarios and makes no model requests. Example:
    .venv/Scripts/python scripts/rehearse_live_api.py --live --routes 1
All evidence stays in ignored .local/delivery-rehearsal; no hardware/export runs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

import app.api as api  # noqa: E402
from app.engineering import state_for  # noqa: E402
from app.model_client import DEFAULT_MODEL, ModelClientError, ModelSettings  # noqa: E402

SCENARIOS = [
    {
        "name": "bench-dilutions",
        "needs": (
            "I prepare aliquots and dilutions manually using a pipette and microcentrifuge "
            "tubes. I have 1200 mm of bench width, can assemble open hardware, and prioritize "
            "customization. Compare an assembled platform with an open-source buildable "
            "platform, explain tradeoffs, and ask for my choice before designing anything."
        ),
        "choice": "I choose the open-source buildable Jubilee platform. Proceed with its design.",
        "revision": (
            "Lower the existing build plate by another 30 mm while preserving the source frame "
            "dimensions and the component arrangement."
        ),
        "cooling": (
            "Now add a refrigerated cold-storage bay with a target of 4 C. Keep the existing "
            "component arrangement and bed position."
        ),
        "arm": (
            "Now add an inspection arm and camera to this workstation. Preserve the workstation "
            "and cold-storage bay."
        ),
        "quantities": (
            "Use 10 mg/mL stock and target concentrations of 1, 0.5 and 0.1 mg/mL, with a final "
            "volume of 1 mL per tube. Keep the machine layout unchanged."
        ),
        "stock_ul": [100, 50, 10],
        "revision_drop_mm": 30,
    },
    {
        "name": "flexible-preparation",
        "needs": (
            "My repetitive task is making dilutions and aliquoting them with a manual pipette "
            "into microcentrifuge tubes. Available bench width is 1300 mm. I am willing to "
            "build the automation platform myself. Please compare buy-assembled and buildable "
            "open hardware choices and wait for my selection before making a model."
        ),
        "choice": (
            "The buildable open-hardware route suits me; use Jubilee and develop the "
            "workstation now."
        ),
        "revision": (
            "Move the original build plate down by 25 mm from its current pose; leave the fixed "
            "frame and all part sizes unchanged."
        ),
        "cooling": (
            "Include a refrigerated cold-storage bay now, target 6 C, retaining the accepted "
            "bed pose and custom insert layout."
        ),
        "arm": (
            "Expand this same machine now with a camera on an inspection arm; retain the "
            "cold-storage module and existing platform."
        ),
        "quantities": (
            "My stock is 20 mg/mL. Use targets of 2, 1 and 0.2 mg/mL and 500 uL per tube. Keep "
            "the machine layout unchanged."
        ),
        "stock_ul": [50, 25, 5],
        "revision_drop_mm": 25,
    },
    {
        "name": "customizable-bench",
        "needs": (
            "Help automate pipette-based aliquoting and dilution preparation in microcentrifuge "
            "tubes. My bench allows a maximum width of 1250 mm, I can assemble a kit, and "
            "flexibility matters more than rapid installation. Offer the reviewed assembled and "
            "open-hardware alternatives with practical tradeoffs, then ask which I want. Do not "
            "generate CAD yet."
        ),
        "choice": (
            "I prefer the open-source buildable option you offered. Choose Jubilee and generate "
            "that design."
        ),
        "revision": (
            "Revise the accepted machine by lowering its current build plate another 20 mm. "
            "Retain the original frame and all existing part dimensions."
        ),
        "cooling": (
            "Add a cold-storage refrigerated bay to the current workstation at a target of 8 C, "
            "preserving its accepted bed pose and insert arrangement."
        ),
        "arm": (
            "Add the inspection-arm and camera module now to this same workstation, keeping all "
            "existing modules."
        ),
        "quantities": (
            "Set stock concentration to 5 mg/mL, targets to 0.5, 0.25 and 0.05 mg/mL, and final "
            "volume to 2 mL per tube. Keep the machine layout unchanged."
        ),
        "stock_ul": [200, 100, 20],
        "revision_drop_mm": 20,
    },
]


def token_totals(calls: list[dict]) -> dict:
    """Count each physical provider response once, including rejected responses."""
    totals = {key: 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    missing = 0
    for call in calls:
        usage = call.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        missing += not all(key in usage for key in totals)
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
    return {**totals, "calls_with_incomplete_usage": missing}


def audit_route(route: dict, scenario: dict) -> list[str]:
    """Audit actual geometry/quantities, rather than differences in model prose."""
    projects = {
        step["stage"]: step["response"]["project"]
        for step in route["steps"]
        if "project" in step.get("response", {})
    }
    selected, revised, cooled, extended, quantified = (
        projects[stage] for stage in ("choice", "revision", "cooling", "arm", "quantities")
    )
    first = selected["engineering_design"]["proposal"]
    changed = revised["engineering_design"]["proposal"]
    assert changed["bed_drop_mm"] == first["bed_drop_mm"] + scenario["revision_drop_mm"], (
        "Requested bed-pose change was not implemented exactly"
    )
    geometry_fields = ("deck_width_mm", "deck_depth_mm")

    def placements(proposal):
        return {p["component_id"]: p for p in proposal["placements"]}

    assert placements(changed) == placements(first), "Revision rearranged accepted placements"
    for field in geometry_fields:
        assert changed[field] == first[field], f"Revision changed preserved {field}"
    for field in ("id", "source_sha256", "bbox_mm"):
        assert revised["design"]["foundation"][field] == selected["design"]["foundation"][field]
    initial_parts = {part["id"]: part for part in selected["design"]["components"]}
    revised_parts = {part["id"]: part for part in revised["design"]["components"]}
    assert revised_parts["foundation-jubilee"] == initial_parts["foundation-jubilee"]
    for part_id, part in initial_parts.items():
        assert revised_parts[part_id]["size"] == part["size"], f"Revision resized {part_id}"
        for axis in (0, 2):
            assert revised_parts[part_id]["position"][axis] == part["position"][axis], (
                f"Revision rearranged {part_id}"
            )
    cold_proposal = cooled["engineering_design"]["proposal"]
    assert placements(cold_proposal) == placements(changed), "Cooling rearranged placements"
    for field in (*geometry_fields, "bed_drop_mm"):
        assert cold_proposal[field] == changed[field], f"Cooling changed preserved {field}"
    cold_parts = {part["id"]: part for part in cooled["design"]["components"]}
    for part_id, part in revised_parts.items():
        assert cold_parts[part_id] == part, f"Cooling moved/resized existing {part_id}"
    extended_parts = {part["id"]: part for part in extended["design"]["components"]}
    for part_id, part in cold_parts.items():
        assert extended_parts[part_id] == part, f"Inspection modified existing {part_id}"
    assert extended["design"]["cooling"] == cooled["design"]["cooling"]
    assert_quantity_layout(extended, quantified)
    assert [s["stock_volume_ul"] for s in quantified["plan"]["steps"]] == scenario["stock_ul"]
    assert route["final_project"]["status"] == "confirmed"
    return [
        "exact_bed_delta",
        "source_identity_and_frame",
        "preserved_part_sizes_and_arrangement",
        "cooling_preserves_layout",
        "inspection_preserves_workstation",
        "direct_dilution",
        "quantity_preserves_geometry",
        "confirmed_final_state",
    ]


def assert_quantity_layout(before: dict, after: dict) -> None:
    """Permit only the exact canonical target-count rack representation to change."""
    from app.geometry import add_geometry

    expected = deepcopy(before)
    expected["plan"] = deepcopy(after["plan"])
    expected = add_geometry(expected)
    assert after["design"] == expected["design"], "Quantities altered accepted layout"
    assert after["engineering_design"] == before["engineering_design"]
    assert after.get("inspection_extension") == before.get("inspection_extension")


class Rehearsal:
    def __init__(self, output: Path, settings: ModelSettings, max_calls: int, *, mode="live"):
        self.output, self.settings, self.max_calls = output, settings, max_calls
        self.mode = mode
        self.code_sha256 = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "app/engineering.py",
                "app/model_client.py",
                "app/design_agent.py",
                "scripts/rehearse_live_api.py",
            )
        }
        self.calls: list[dict] = []
        self.routes: list[dict] = []
        self.stage = "initialization"

    def save(self):
        self.output.mkdir(parents=True, exist_ok=True)
        payload = {
            "scope": "Synthetic live API integration; no laboratory or hardware validation",
            "model": self.settings.model,
            "evidence_mode": self.mode,
            "physical_provider_calls": len(self.calls) if self.mode == "live" else 0,
            "token_usage_scope": ("Reported usage for this live run" if self.mode == "live"
                                  else "Historical recorded usage; no new Meta consumption"),
            "code_sha256": self.code_sha256,
            "max_model_calls": self.max_calls,
            "provider_calls": self.calls,
            "token_totals": token_totals(self.calls),
            "routes": self.routes,
        }
        (self.output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def instrument(self, original):
        async def send(client, request, *args, **kwargs):
            if str(request.url) != f"{self.settings.base_url}/chat/completions":
                return await original(client, request, *args, **kwargs)
            if len(self.calls) >= self.max_calls:
                raise ModelClientError("Rehearsal model-call budget exhausted; project unchanged.")
            body = json.loads(request.content)
            record = {
                "number": len(self.calls) + 1,
                "stage": self.stage,
                "requested_model": body.get("model"),
                "schema": body.get("response_format", {}).get("json_schema", {}).get("name"),
                "status": "started",
            }
            self.calls.append(record)
            self.save()
            started = time.monotonic()
            try:
                response = await original(client, request, *args, **kwargs)
                record["http_status"] = response.status_code
                try:
                    raw = response.json()
                except ValueError:
                    raw = {}
                record.update(
                    status="completed" if response.is_success else "provider_error",
                    usage=raw.get("usage", {}),
                    actual_model=raw.get("model"),
                    choices=raw.get("choices", []),
                )
                return response
            except BaseException as exc:
                record.update(status="transport_error", error_type=type(exc).__name__)
                raise
            finally:
                record["latency_seconds"] = round(time.monotonic() - started, 3)
                self.save()

        return send

    async def run_route(
        self, client: httpx.AsyncClient, scenario: dict, recovery: dict | None = None
    ):
        route = {"name": scenario["name"], "status": "started", "steps": []}
        self.routes.append(route)
        project = (await client.post("/api/projects")).json()["project"]

        async def message(stage):
            nonlocal project
            self.stage = f"{scenario['name']}/{stage}"
            before = deepcopy(project)
            started = time.monotonic()
            response = await client.post(
                f"/api/projects/{project['id']}/messages", json={"message": scenario[stage]}
            )
            data = response.json()
            record = {
                "stage": stage,
                "message": scenario[stage],
                "http": response.status_code,
                "latency_seconds": round(time.monotonic() - started, 3),
                "response": data,
            }
            route["steps"].append(record)
            self.save()
            print(
                json.dumps(
                    {
                        "route": route["name"],
                        "stage": stage,
                        "http": response.status_code,
                        "calls": len(self.calls),
                        "latency_seconds": record["latency_seconds"],
                    }
                ),
                flush=True,
            )
            if response.status_code != 200:
                assert api._sessions[project["id"]].project == before, "Failed turn changed state"
                raise AssertionError(f"{stage}: HTTP {response.status_code}: {data.get('detail')}")
            project = data["project"]
            failed = [
                r for r in data.get("action_runs", []) if r["status"] in ("failed", "rejected")
            ]
            if failed:
                assert project == before, "Failed turn changed project state"
                raise AssertionError(f"{stage}: " + "; ".join(r["message"] for r in failed))

        try:
            if recovery:
                restored = await client.post(
                    "/api/projects/open",
                    content=recovery["snapshot"].read_bytes(),
                    headers={"Content-Type": "application/json"},
                )
                assert restored.status_code == 201, "Recovery snapshot failed to open"
                project = restored.json()["project"]
                route["recovery"] = {
                    "source_results": recovery["source_results"],
                    "snapshot": str(recovery["snapshot"]),
                    "scope": "Recovered after harness correction; not an uninterrupted fresh run",
                }
                route["steps"] = deepcopy(
                    [
                        step
                        for step in recovery["route"]["steps"]
                        if step["stage"]
                        in ("needs", "choice", "revision", "cooling", "save_reopen")
                    ]
                )
            else:
                await message("needs")
                assert len(state_for(project)["options"]) == 2, "Needs did not offer both routes"
                assert state_for(project)["selected_platform_id"] is None
                assert not project.get("engineering_design"), "CAD appeared before selection"
                await message("choice")
                assert state_for(project)["selected_platform_id"] == "jubilee"
                assert project.get("engineering_design"), "Selection did not develop a design"
                original_proposal = deepcopy(project["engineering_design"]["proposal"])
                await message("revision")
                assert project["engineering_design"]["proposal"] != original_proposal, (
                    "Revision had no effect"
                )
                await message("cooling")
                assert project["design"]["cooling"]["enabled"], "Cold bay was not enabled"
                saved = await client.get(
                    f"/api/projects/{project['id']}/snapshot",
                    params={"revision": project["revision"]},
                )
                assert saved.status_code == 200, "Snapshot failed"
                (self.output / f"{scenario['name']}-snapshot.json").write_bytes(saved.content)
                before = deepcopy(project)
                reopened = await client.post(
                    "/api/projects/open",
                    content=saved.content,
                    headers={"Content-Type": "application/json"},
                )
                assert reopened.status_code == 201, f"Reopen failed: {reopened.status_code}"
                project = reopened.json()["project"]
                assert project["id"] != before["id"]
                assert project["design"] == before["design"], "Reopen changed design"
                route["steps"].append(
                    {"stage": "save_reopen", "status": "passed", "model_calls": 0}
                )
            await message("arm")
            assert project.get("inspection_extension"), "Inspection extension missing"
            before_quantities = deepcopy(project)
            await message("quantities")
            assert_quantity_layout(before_quantities, project)
            assert [step["stock_volume_ul"] for step in project["plan"]["steps"]] == scenario[
                "stock_ul"
            ]
            confirmed = await client.post(f"/api/projects/{project['id']}/confirm")
            assert confirmed.status_code == 200, f"Confirmation failed: {confirmed.status_code}"
            project = confirmed.json()["project"]
            assert project["status"] == "confirmed"
            final_snapshot = await client.get(
                f"/api/projects/{project['id']}/snapshot",
                params={"revision": project["revision"]},
            )
            assert final_snapshot.status_code == 200, "Final snapshot failed"
            final_path = self.output / f"{scenario['name']}-final-snapshot.json"
            final_path.write_bytes(final_snapshot.content)
            route.update(status="passed", final_project=project)
            route["final_snapshot"] = str(final_path)
            route["passed_audits"] = audit_route(route, scenario)
            route["steps"].append({"stage": "confirmation", "status": "passed", "model_calls": 0})
        except Exception as exc:
            route.update(
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                final_project=project,
            )
        finally:
            self.save()


def dry_run(args):
    selected = SCENARIOS[args.start_route - 1 : args.start_route - 1 + args.routes]
    print(
        json.dumps(
            {
                "mode": "dry_run",
                "model": DEFAULT_MODEL,
                "max_model_calls": args.max_model_calls,
                "scenarios": selected,
                "note": "Add --live to send synthetic inputs to Meta.",
            },
            indent=2,
        )
    )


async def main(args):
    selected = SCENARIOS[args.start_route - 1 : args.start_route - 1 + args.routes]
    recoveries = {}
    if args.resume_results:
        resume = args.resume_results.resolve()
        if not resume.is_relative_to((ROOT / ".local" / "delivery-rehearsal").resolve()):
            raise ValueError("Resume only synthetic rehearsal records in .local/delivery-rehearsal")
        previous = json.loads(resume.read_text(encoding="utf-8"))
        for route in previous["routes"]:
            snapshot = resume.parent / f"{route['name']}-snapshot.json"
            if snapshot.is_file():
                recoveries[route["name"]] = {
                    "source_results": str(resume),
                    "snapshot": snapshot,
                    "route": route,
                }
    replay_calls = None
    if args.replay_results:
        recorded = json.loads(args.replay_results.read_text(encoding="utf-8"))
        prefixes = tuple(s["name"] + "/" for s in selected)
        replay_calls = iter(
            c for c in recorded["provider_calls"] if c["stage"].startswith(prefixes)
        )
        configured = ModelSettings("offline-replay", "https://replay.invalid/v1", DEFAULT_MODEL)
    else:
        configured = ModelSettings.load()
    # Explicitly use Contributor even when local application configuration selects another model.
    settings = ModelSettings(configured.api_key, configured.base_url, DEFAULT_MODEL)
    output = (
        ROOT
        / ".local"
        / "delivery-rehearsal"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    rehearsal = Rehearsal(
        output,
        settings,
        args.max_model_calls,
        mode="recorded_response_replay" if replay_calls is not None else "live",
    )
    original_send = httpx.AsyncClient.send

    async def recorded_send(client, request, *positional, **keyword):
        if str(request.url) != f"{settings.base_url}/chat/completions":
            return await original_send(client, request, *positional, **keyword)
        record = next(replay_calls, None)
        if record is None:
            raise ModelClientError("No recorded response remains for this replay.")
        schema = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if record["stage"] != rehearsal.stage or record["schema"] != schema:
            raise ModelClientError("Recorded response does not match the current rehearsal stage.")
        return httpx.Response(
            record["http_status"],
            request=request,
            json={
                "model": record.get("actual_model"),
                "choices": record.get("choices", []),
                "usage": record.get("usage", {}),
            },
        )

    with (
        patch.object(ModelSettings, "load", return_value=settings),
        patch.object(
            httpx.AsyncClient,
            "send",
            rehearsal.instrument(recorded_send if replay_calls is not None else original_send),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://local"
        ) as client:
            for scenario in selected:
                await rehearsal.run_route(client, scenario, recoveries.get(scenario["name"]))
                if rehearsal.routes[-1]["status"] == "failed" and not args.continue_after_failure:
                    break
    print(
        json.dumps(
            {
                "output": str(output),
                "provider_calls": len(rehearsal.calls),
                "evidence_mode": rehearsal.mode,
                "token_totals": token_totals(rehearsal.calls),
                "routes": [
                    {"name": r["name"], "status": r["status"], "error": r.get("error")}
                    for r in rehearsal.routes
                ],
            },
            indent=2,
        )
    )
    return 0 if all(r["status"] == "passed" for r in rehearsal.routes) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly permit real Contributor calls"
    )
    parser.add_argument("--routes", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--start-route", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--max-model-calls", type=int, choices=range(1, 46), default=30)
    parser.add_argument("--continue-after-failure", action="store_true")
    parser.add_argument(
        "--resume-results",
        type=Path,
        help="Recover completed cooling stages from a prior synthetic rehearsal",
    )
    parser.add_argument(
        "--replay-results",
        type=Path,
        help="Replay recorded provider responses offline; makes no real Meta calls",
    )
    arguments = parser.parse_args()
    if arguments.start_route + arguments.routes > 4:
        parser.error("Requested routes exceed the three synthetic scenarios")
    if arguments.live and arguments.replay_results:
        parser.error("Choose --live or --replay-results, never both")
    if arguments.live or arguments.replay_results:
        raise SystemExit(asyncio.run(main(arguments)))
    dry_run(arguments)
