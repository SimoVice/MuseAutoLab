"""Bounded real-product microplate acceptance evaluation; dry run by default.

Uses /open and /messages, not a manually accepted model result. Deterministic
setup fixtures are explicitly separate from live evidence. Each predeclared case
gets one message, with no retries or prompt repairs. Replay consumes no credits.
Raw product requests, provider attempts and all failures remain in ignored .local.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import evaluate_labware as shared  # noqa: E402

MODEL = shared.MODEL
MAX_CALLS = 8
FIXTURES = {"rack_2ml", "rack_200ul", "plate_200ul"}
OUTCOMES = {"plate_ready", "volume_conflict", "rack_restored", "unchanged"}


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("Use a schema_version 1 microplate dataset.")
    if not 1 <= len(data["cases"]) <= MAX_CALLS:
        raise ValueError("Use one to eight predeclared cases.")
    if type(data.get("max_model_calls")) is not int or not 1 <= data["max_model_calls"] <= 8:
        raise ValueError("The dataset provider-call cap must be one to eight.")
    if not shared.owned_path(data["baseline"]).is_file():
        raise ValueError("A public product baseline file is required.")
    seen = set()
    for case in data["cases"]:
        cid = case.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cid) or cid in seen:
            raise ValueError("Case ids must be safe and unique.")
        seen.add(cid)
        if case.get("fixture") not in FIXTURES or not isinstance(case.get("prompt"), str):
            raise ValueError("Each case needs a declared fixture and prompt.")
        if not case["prompt"].strip() or case.get("clarification"):
            raise ValueError("Only one predeclared message per case; no clarification or repair.")
        if case.get("expected", {}).get("outcome") not in OUTCOMES:
            raise ValueError("Declare the expected microplate outcome.")
        if type(case["expected"].get("volume_ul")) not in (int, float):
            raise ValueError("Declare the unchanged or explicitly edited volume.")
    return data


def make_fixtures(baseline: Path) -> dict:
    """Deterministic test setup only; these fixtures are never live model results."""
    from app.domain import apply_update, confirm_project
    from app.microplates import PROFILE_ID, LabwareSelection, select_plate
    from app.project_storage import decode_snapshot, make_snapshot, restore_snapshot

    baseline_snapshot = decode_snapshot(baseline.read_bytes())
    original, history = restore_snapshot(baseline_snapshot)
    assert original.get("labware_rack") and not original.get("labware_plate")
    assert original["plan"]["final_volume_ul"] == 2000
    smaller = confirm_project(apply_update(original, {"final_volume": "200 µL"}))
    assert smaller["design"] == original["design"], "Quantity-only setup changed geometry"
    literal = "Use the reviewed 96-well reference for this synthetic test fixture."
    plate, run = select_plate(
        smaller, LabwareSelection(profile_id=PROFILE_ID, source=literal), literal
    )
    assert run["status"] == "accepted"
    plate = confirm_project(plate)
    fixtures = {"rack_2ml": original, "rack_200ul": smaller, "plate_200ul": plate}
    snapshots = {name: make_snapshot(project, history) for name, project in fixtures.items()}
    for value in snapshots.values():
        value["saved_at"] = baseline_snapshot["saved_at"]
    return snapshots


def component_index(project: dict) -> dict:
    return {part["id"]: part for part in project["design"]["components"]}


def audit_invariants(before: dict, after: dict, expected: dict) -> list[str]:
    """Allow sample-only replacement plus exactly recomputed existing inspection IK."""
    from app.inspection import check_extension

    for key in (
        "engineering_design",
        "engineering",
        "brief",
        "workflow",
        "selections",
        "labware_brief",
    ):
        assert after.get(key) == before.get(key), f"Unexpected {key} change"
    summary = deepcopy(after["summary"])
    summary["final_volume"] = before["summary"]["final_volume"]
    assert summary == before["summary"], "Other preparation inputs changed"
    for key in ("foundation", "footprint", "constraint_status", "cooling"):
        assert after["design"].get(key) == before["design"].get(key), f"Fixed design {key} changed"
    left, right = component_index(before), component_index(after)
    assert left.keys() == right.keys(), "Canonical component identities changed"
    previous_extension = before.get("inspection_extension")
    inspection_ids = set((previous_extension or {}).get("component_ids", []))
    for cid in left:
        if cid != "sample-rack" and cid not in inspection_ids:
            assert right[cid] == left[cid], f"Fixed component {cid} changed"
    if previous_extension:
        recomputed = check_extension(after, previous_extension["proposal"])
        recomputed["provenance"] = deepcopy(previous_extension.get("provenance", {}))
        assert after["inspection_extension"] == recomputed, (
            "Inspection differs from existing deterministic IK"
        )
        assert recomputed["attachment"] == previous_extension["attachment"], (
            "Inspection mount changed"
        )
        assert recomputed["proposal"] == previous_extension["proposal"], (
            "Inspection links/proposal changed"
        )
        for part in recomputed["components"]:
            assert right[part["id"]] == part, "Inspection component differs from existing IK"
    else:
        assert not after.get("inspection_extension"), "Inspection added"
    assert after["plan"]["final_volume_ul"] == expected["volume_ul"], "Volume silently changed"
    assert len(after["plan"]["steps"]) == len(before["plan"]["steps"]) == 3, (
        "Capacity changed target count"
    )
    scale = expected["volume_ul"] / before["plan"]["final_volume_ul"]
    for old, new in zip(before["plan"]["steps"], after["plan"]["steps"]):
        for key in ("id", "target"):
            assert new[key] == old[key], "Preparation target changed"
        for key in ("stock_volume_ul", "diluent_volume_ul", "total_volume_ul"):
            shared.assert_equal(new[key], old[key] * scale, f"Recipe arithmetic {key}")
    return [
        "fixed_source_and_components_preserved",
        "retained_inspection_proposal_and_exact_ik",
        "three_targets_and_explicit_volume_preserved",
    ]


def audit_plate(before: dict, after: dict, expected: dict) -> list[str]:
    from app.microplate_geometry import compile_microplate
    from app.microplates import PROFILE_ID, _placement_checks

    audits = audit_invariants(before, after, expected)
    module = after.get("labware_plate")
    assert module and not after.get("labware_rack"), (
        "Plate not visible as sole active sample module"
    )
    assert module["profile_id"] == PROFILE_ID
    compiled = compile_microplate(PROFILE_ID)
    assert module["profile_binding"] == {
        "source_revision": compiled["profile"]["source"]["revision"],
        "source_sha256": compiled["profile"]["source"]["sha256"],
    }, "Plate source binding differs from the pinned profile"
    for key in ("geometry", "profile", "derived", "size_mm"):
        assert module[key] == compiled[key], f"Plate {key} differs from pinned compiler"
    compatibility = module["compatibility"]
    assert compatibility["status"] == (
        "volume_conflict" if expected["outcome"] == "volume_conflict" else "ready"
    )
    assert compatibility["occupied_wells"] == ["A1", "B1", "C1"]
    assert module["derived"]["well_count"] == 96
    assert len(module["derived"]["wells"]) == 96
    assert after["plan"]["destination_labels"] == ["A1", "B1", "C1"]
    assert [s["well_name"] for s in after["plan"]["steps"]] == ["A1", "B1", "C1"]
    assert after["plan"]["container_kind"] == "well"
    part = component_index(after)["sample-rack"]
    base = component_index(after)["base"]
    shared.assert_equal(part["size"], compiled["size_mm"], "plate canonical size")
    shared.assert_equal(
        part["position"][1], base["position"][1] + base["size"][1] / 2 + part["size"][1] / 2
    )
    assert all(
        c["passed"]
        for c in _placement_checks(after, part["size"], part["position"][0], part["position"][2])
    )
    original = component_index(before)["sample-rack"]
    for key in ("kind", "label", "size", "position"):
        assert module["previous_sample"]["component"][key] == original[key], "Previous rack lost"
    assert module["checks"] and module["metrics"]["physical_fit_verified"] is False
    return audits + [
        "pinned_plate_geometry_and_capacity",
        "A1_B1_C1_only",
        "sample_only_feasible_placement",
        "stored_previous_rack",
    ]


def audit_restoration(before: dict, after: dict, expected: dict) -> list[str]:
    audits = audit_invariants(before, after, expected)
    previous = before["labware_plate"]["previous_sample"]
    assert not after.get("labware_plate") and after.get("labware_rack")
    part = component_index(after)["sample-rack"]
    for key, value in previous["component"].items():
        assert part[key] == value, f"Restored rack {key} differs"
    from app.labware import rack_inputs

    assert rack_inputs(after["labware_rack"]) == previous["rack_inputs"], (
        "Stored rack spec/provenance changed"
    )
    assert after["plan"]["status"] == "ready"
    return audits + ["exact_stored_rack_geometry_position_and_spec_restored"]


def audit_visible_reply(reply: str, project: dict, expected: dict) -> list[str]:
    """Audit the final /messages text, including deterministic API appendices.

    Deliberately fails on obsolete raw-model prose even when a later appendix is
    correct. Presence checks are bounded regression assertions, not a general
    natural-language truth evaluator or a check of unshown provider prose.
    """
    assert isinstance(reply, str) and reply.strip(), "Final user-visible reply is empty"
    text = reply.casefold().replace("μ", "µ")
    text = re.sub(r"[*_`]+", "", text)
    outcome = expected["outcome"]
    if outcome == "unchanged":
        assert re.search(
            r"not supported|isn.t supported|unsupported|no reviewed|no adapter|not applied|"
            r"non.{0,12}support|non.{0,12}disponib|non.{0,12}verificat|nessun.adattatore",
            text,
        ), "Unsupported reply does not explain rejection"
        assert not re.search(
            r"\b(?:not|never|no longer|doesn.t|won.t|cannot|can.t)\s+"
            r"(?:stays?|remains?)\s+as[- ]is\b",
            text,
        ), "Unsupported reply explicitly says the current state will change"
        assert re.search(
            r"unchanged|preserv|keeping|kept|manteng|invariat|no changes|not changed|"
            r"\b(?:stays?|remains?)\s+as[- ]is\b",
            text,
        ), "Unsupported reply does not say the existing state was preserved"
        assert not re.search(
            r"(?:selected|switched to|adopted|selezionata|adottata).{0,25}(?:bio.rad|384)", text
        ), "Unsupported reply claims to adopt the unsupported destination"
        return ["visible_unsupported_rejection_and_preserved_state"]
    volume = project["plan"]["final_volume_ul"]
    assert volume == expected["volume_ul"]
    volume_patterns = [rf"\b{volume:g}(?:\.0+)?\s*(?:µl|ul)\b"]
    if volume >= 1000:
        volume_patterns.append(rf"\b{volume / 1000:g}(?:\.0+)?\s*ml\b")
    assert any(re.search(pattern, text) for pattern in volume_patterns), (
        "Visible reply omits the current final volume"
    )
    assert re.search(
        r"\b3\s+(?:existing\s+)?(?:preparations?|targets?|target\(s\)|wells?|pozzetti|preparazioni)"
        r"|(?:preparations?|targets?|preparazioni|occupied(?:\s+wells)?)[^\n.;]{0,15}\b3\b",
        text,
    ), "Visible reply omits the actual three preparations"
    plate = project.get("labware_plate")
    if plate:
        assert re.search(r"corning|piastra|plate", text), "Visible reply omits the active plate"
        assert re.search(r"\b96\b", text), "Visible reply omits plate capacity"
        for well in plate["compatibility"]["occupied_wells"]:
            assert re.search(rf"\b{well.casefold()}\b", text), f"Visible reply omits {well}"
        assert not re.search(r"(?:per|each)\s+(?:tube|tubo|provetta)\b", text), (
            "Active plate recipe is still labelled per tube"
        )
        if outcome == "volume_conflict":
            assert plate["compatibility"]["status"] == "volume_conflict"
            assert re.search(r"exceed|supera|conflit|conflict", text)
            assert re.search(r"\b360\s*(?:µl|ul)\b", text), "Reference maximum omitted"
            assert re.search(r"block|blocc|cannot confirm|non.*conferm", text), (
                "Visible reply omits the real confirmation/export block"
            )
            assert re.search(r"confirm|conferm", text) and re.search(
                r"export|esport|project.file generation", text
            ), "Visible reply must explain both confirmation and export gates"
            assert not re.search(r"(?:plan|recipe|preparazione|ricetta)\s+(?:is\s+)?ready", text)
        else:
            assert plate["compatibility"]["status"] == "ready"
            assert re.search(
                r"ready|pront|no volume conflict|nessun conflitto|"
                r"passes.{0,60}reference maximum check",
                text,
            ), "Visible reply omits the ready preparation state"
            assert not re.search(r"\b2(?:\.0+)?\s*ml\b|\b2000\s*(?:µl|ul)\b", text), (
                "Visible ready reply repeats the obsolete 2 mL recipe"
            )
            assert not re.search(
                r"(?:recipe|plan|ricetta|preparazione)[^\n.!?]{0,55}(?:blocked|bloccata|invalid)"
                r"|(?:unblock|sbloccare|dimmi il nuovo volume|tell me.{0,25}volume)",
                text,
            ), "Ready reply falsely requires a new volume to unblock the recipe"
    else:
        assert outcome == "rack_restored"
        assert re.search(r"rack|portaprovette", text) and re.search(r"restor|ripristin|torn", text)
        assert re.search(r"ready|pront|review and confirm this draft|project is confirmed", text), (
            "Restored rack reply omits ready recipe state"
        )
        assert not re.search(r"calculated preparation per well|preparazione per pozzetto", text)
    return ["visible_current_module_volume_occupancy_and_blocking_status"]


class Evaluation(shared.Evaluation):
    def instrument(self, original_send, settings):
        product_send = original_send
        if self.regression_replay is not None:
            original_send = self.regression_provider
        tracked = super().instrument(original_send, settings)

        async def send(client, request, *args, **kwargs):
            if not str(request.url).startswith("http://evaluation.local/"):
                if any(record["case_id"] == self.case_id for record in self.calls):
                    self.abort_reason = "One-call limit per case reached; no retry request sent."
                    raise shared.EvaluationAbort(self.abort_reason)
                if json.loads(request.content).get("model") != MODEL:
                    self.abort_reason = (
                        "Unexpected provider model; only Spark Contributor is allowed."
                    )
                    raise shared.EvaluationAbort(self.abort_reason)
            if str(request.url).startswith("http://evaluation.local/"):
                # Keep the real ASGI product request; only the provider is replayed.
                return await product_send(client, request, *args, **kwargs)
            return await tracked(client, request, *args, **kwargs)

        return send

    def __init__(self, *args, replay_regression=False, **kwargs):
        self.regression_replay = None
        self.replay_differences = []
        self.own_hashes = {
            str(Path(__file__)): shared.digest(Path(__file__).read_bytes()),
            str(Path(shared.__file__)): shared.digest(Path(shared.__file__).read_bytes()),
        }
        super().__init__(*args, **kwargs)
        if replay_regression:
            assert self.replay is not None, "Regression replay requires recorded provider responses"
            self.regression_replay, self.replay = self.replay, None
            self.mode = "recorded_response_regression_replay"
        self.fixtures = make_fixtures(shared.owned_path(self.dataset["baseline"]))
        folder = self.output / "fixtures"
        folder.mkdir()
        for name, value in self.fixtures.items():
            (folder / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
        self.fixture_hashes = {str(p): shared.digest(p.read_bytes()) for p in folder.iterdir()}
        self.save()

    async def regression_provider(self, client, request, *args, **kwargs):
        """Supply unedited historical bytes to a changed prompt/app with no network."""
        records = self.regression_replay["provider_calls"]
        index = len(self.calls) - 1
        assert 0 <= index < len(records), "No recorded response remains"
        previous, current = records[index], self.calls[index]
        assert (previous["case_id"], previous["turn_index"], previous["schema"]) == (
            self.case_id,
            self.turn_index,
            current["schema"],
        ), "Regression replay case/schema mismatch"
        self.replay_differences.append(
            {
                "call": index + 1,
                "case_id": self.case_id,
                "request_identical_beyond_runtime_ids": shared.normalized_request(
                    previous["request"]
                )
                == shared.normalized_request(current["request"]),
                "recorded_request": previous["request"],
                "current_request": current["request"],
                "recorded_response_sha256": shared.digest(
                    previous.get("response_body", "").encode()
                ),
                "scope": "Historical response to the old request, injected for regression only; "
                "not a new prediction for the changed request.",
            }
        )
        if "http_status" not in previous:
            raise httpx.ReadTimeout("Replaying recorded transport failure", request=request)
        return httpx.Response(
            previous["http_status"], content=previous["response_body"].encode(), request=request
        )

    def guard(self):
        super().guard()
        for path, expected in {**self.own_hashes, **getattr(self, "fixture_hashes", {})}.items():
            if shared.digest(Path(path).read_bytes()) != expected:
                self.abort_reason = (
                    "Evaluation harness/helper or deterministic fixture changed during run."
                )
                raise shared.EvaluationAbort(self.abort_reason)

    def save(self):
        super().save()
        path = self.output / "results.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(
            harness_sha256=self.own_hashes[str(Path(__file__))],
            harness_sha256_after=shared.digest(Path(__file__).read_bytes()),
            harness_and_helper_sha256=self.own_hashes,
            harness_and_helper_sha256_after={
                path: shared.digest(Path(path).read_bytes()) for path in self.own_hashes
            },
            fixture_sha256=getattr(self, "fixture_hashes", {}),
            fixture_scope="Deterministic setup, not live Meta acceptance evidence.",
            replay_request_differences=self.replay_differences,
        )
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def run_case(self, client, api, case):
        self.case_id, self.turn_index = case["id"], 0
        folder = self.output / case["id"]
        folder.mkdir()
        record = {"id": case["id"], "expected": case["expected"], "status": "started", "turns": []}
        self.cases.append(record)
        project = None
        try:
            self.guard()
            response = await client.post("/api/projects/open", json=self.fixtures[case["fixture"]])
            assert response.status_code == 201, f"Fixture reopen failed: {response.text}"
            project = response.json()["project"]
            before = deepcopy(project)
            record["baseline_project"] = before
            (folder / "before-project.json").write_text(
                json.dumps(before, indent=2), encoding="utf-8"
            )
            api._sessions[project["id"]].model = MODEL
            started = time.monotonic()
            calls_before = len(self.calls)
            response = await client.post(
                f"/api/projects/{project['id']}/messages", json={"message": case["prompt"]}
            )
            data = response.json()
            project = deepcopy(api._sessions[project["id"]].project)
            record["turns"].append(
                {
                    "prompt": case["prompt"],
                    "http_status": response.status_code,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "response": data,
                }
            )
            self.save()
            self.guard()
            assert len(self.calls) > calls_before, (
                "No actual/recorded provider attempt in product turn"
            )
            assert response.status_code == 200, (
                f"Provider/server failure is not acceptance: HTTP {response.status_code}"
            )
            outcome = case["expected"]["outcome"]
            accepted = any(
                r.get("kind") == "select_labware" and r.get("status") == "accepted"
                for r in data.get("action_runs", [])
            )
            if outcome == "unchanged":
                assert not accepted and project == before, (
                    "Unsupported destination silently changed canonical state"
                )
                audits = ["whole_canonical_state_preserved", "no_silent_substitution"]
            else:
                assert accepted, "No accepted select_labware action"
                audits = (audit_restoration if outcome == "rack_restored" else audit_plate)(
                    before, project, case["expected"]
                )
                audits += await self.audit_documents_and_roundtrip(client, project, folder)
                audits += await self.audit_gating(client, api, before, project, outcome)
                assert data.get("assistant_message_origin") == "canonical_labware_state", (
                    "Accepted labware reply is not grounded in the committed state"
                )
            audits += audit_visible_reply(data.get("assistant_message"), project, case["expected"])
            record.update(status="passed", passed_audits=audits, final_project=project)
        except Exception as exc:
            record.update(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc),
                final_project=project,
            )
        finally:
            if project:
                (folder / "after-project.json").write_text(
                    json.dumps(project, indent=2), encoding="utf-8"
                )
            self.save()
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "status": record["status"],
                        "error": record.get("error"),
                        "provider_attempts": len(self.calls),
                    }
                ),
                flush=True,
            )

    async def audit_documents_and_roundtrip(self, client, project, folder):
        from app.assembly import build_document_files

        pid, revision = project["id"], project["revision"]
        response = await client.get(
            f"/api/projects/{pid}/instructions", params={"revision": revision}
        )
        assert response.status_code == 200, "Guide unavailable"
        guide = response.json()
        assert guide["project_revision"] == revision
        key = "labware_plate" if project.get("labware_plate") else "labware_rack"
        assert guide[key] == project[key], "Guide module differs from canonical"
        part = next(p for p in guide["parts"] if p["component_id"] == "sample-rack")
        canonical = component_index(project)["sample-rack"]
        assert part["size_mm"] == canonical["size"] and part["position_mm"] == canonical["position"]
        steps = {s["id"]: s for s in guide["steps"]}
        required = (
            ("plate-profile", "plate-volume", "plate-holder", "plate-placement")
            if key == "labware_plate"
            else ("rack-inputs", "rack-print", "rack-fit", "rack-placement")
        )
        assert all("sample-rack" in steps[s]["component_ids"] for s in required)
        if key == "labware_plate":
            source = next(s for s in guide["sources"] if s["id"] == "microplate-profile")
            expected_source = project[key]["profile"]["source"]
            assert source["url"] == expected_source["source_url"]
            assert source["revision"] == expected_source["revision"]
            assert steps["plate-volume"]["status"] == (
                "needs_design"
                if project[key]["compatibility"]["status"] == "volume_conflict"
                else "ready"
            ), "Guide volume readiness differs from the preparation gate"
        docs = build_document_files(project)
        assert json.loads(docs["assembly.json"]) == guide, "Packaged guide differs"
        for name in ("assembly.json", "assembly-guide.html", "assembly-guide.md"):
            (folder / name).write_bytes(docs[name])
        saved = await client.get(f"/api/projects/{pid}/snapshot", params={"revision": revision})
        assert saved.status_code == 200
        (folder / "portable-project.json").write_bytes(saved.content)
        opened = await client.post(
            "/api/projects/open",
            content=saved.content,
            headers={"Content-Type": "application/json"},
        )
        assert opened.status_code == 201, f"Reopen failed: {opened.text}"
        restored = opened.json()["project"]
        for field in (
            "revision",
            "status",
            "summary",
            "plan",
            "design",
            "engineering_design",
            "inspection_extension",
            "labware_rack",
            "labware_plate",
            "labware_brief",
            "sourcing",
        ):
            assert restored.get(field) == project.get(field), f"Portable reopen changed {field}"
        return ["current_and_packaged_guide_agree", "portable_save_reopen_roundtrip"]

    async def audit_gating(self, client, api, before, project, outcome):
        from app.project_exports import ExportError, _ensure_supported

        pid = project["id"]
        stale = await client.get(
            f"/api/projects/{pid}/instructions", params={"revision": before["revision"]}
        )
        assert stale.status_code == 409, "Stale guide not blocked"
        saved = await client.get(
            f"/api/projects/{pid}/snapshot", params={"revision": before["revision"]}
        )
        assert saved.status_code == 409, "Stale snapshot not blocked"
        if outcome == "volume_conflict":
            assert project["status"] == "draft" and project["plan"]["status"] == "invalid"
            confirmed = await client.post(f"/api/projects/{pid}/confirm")
            assert confirmed.status_code == 422, "Volume conflict confirmed"
            exported = await client.post(f"/api/projects/{pid}/exports")
            assert exported.status_code in (409, 422), "Volume conflict started CAD export"
            assert api._sessions[pid].project == project, (
                "Blocked request mutated canonical project"
            )
        else:
            assert project["plan"]["status"] == "ready"
            confirmed = await client.post(f"/api/projects/{pid}/confirm")
            assert confirmed.status_code == 200, f"Ready project cannot confirm: {confirmed.text}"
            accepted = confirmed.json()["project"]
            assert accepted["status"] == "confirmed" and accepted["design"] == project["design"]
            _ensure_supported(accepted)  # Pure gate; do not start heavy CAD jobs per case.
            try:
                _ensure_supported(project)
            except ExportError:
                pass
            else:
                raise AssertionError("Draft unexpectedly exportable")
        return ["stale_revision_blocked", "volume_confirmation_and_export_gates"]


async def execute(args, dataset):
    import app.api as api
    from app.model_client import ModelSettings

    recorded = json.loads(args.replay.read_text(encoding="utf-8")) if args.replay else None
    if recorded and recorded["dataset_sha256_before"] != shared.digest(args.dataset.read_bytes()):
        raise ValueError("Replay requires the identical frozen dataset.")
    if recorded:
        settings = ModelSettings("offline-recorded-replay", "https://replay.invalid/v1", MODEL)
    else:
        configured = ModelSettings.load()
        settings = ModelSettings(configured.api_key, configured.base_url, MODEL)
    output = (
        args.output
        or ROOT
        / ".local/microplate-evaluation"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Raw evidence must remain in ignored .local.")
    run = Evaluation(
        args.dataset,
        dataset,
        output,
        min(args.max_calls, dataset["max_model_calls"]),
        replay=recorded,
        replay_regression=args.replay_regression,
    )
    try:
        with (
            patch.object(ModelSettings, "load", return_value=settings),
            patch.object(
                httpx.AsyncClient, "send", run.instrument(httpx.AsyncClient.send, settings)
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False),
                base_url="http://evaluation.local",
                timeout=180,
            ) as client:
                for case in dataset["cases"]:
                    if run.abort_reason:
                        run.cases.append(
                            {"id": case["id"], "status": "not_run", "reason": run.abort_reason}
                        )
                    else:
                        await run.run_case(client, api, case)
        run.guard()
        if recorded and len(run.calls) != len(recorded["provider_calls"]):
            run.abort_reason = "Replay left recorded provider attempts unused."
    except shared.EvaluationAbort as exc:
        run.abort_reason = str(exc)
    finally:
        run.save()
    print(
        json.dumps(
            {
                "output": str(output),
                "evidence_mode": run.mode,
                "physical_provider_calls": len(run.calls) if args.live else 0,
                "token_totals": shared.token_totals(run.calls),
                "abort_reason": run.abort_reason,
                "cases": [{k: c.get(k) for k in ("id", "status", "error")} for c in run.cases],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if not run.abort_reason and all(c["status"] == "passed" for c in run.cases) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "docs/examples/microplate-evaluation-cases.json"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    parser.add_argument(
        "--replay-regression",
        action="store_true",
        help="With --replay: inject unchanged historical responses despite changed requests; "
        "record the request differences and label this offline product regression.",
    )
    parser.add_argument("--max-calls", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.replay_regression and not args.replay:
        parser.error("--replay-regression requires --replay; it can never make live calls")
    args.dataset = args.dataset.resolve()
    dataset = load_dataset(args.dataset)
    if not args.live and not args.replay:
        print(
            json.dumps(
                {
                    "evidence_mode": "dry_run",
                    "physical_provider_calls": 0,
                    "dataset_sha256": shared.digest(args.dataset.read_bytes()),
                    "source_fingerprint": shared.source_fingerprint()["sha256"],
                    "harness_sha256": shared.digest(Path(__file__).read_bytes()),
                    "baseline": dataset["baseline"],
                    "case_ids": [c["id"] for c in dataset["cases"]],
                    "max_provider_calls": min(args.max_calls, dataset["max_model_calls"]),
                    "note": "No fixture/model turn executed; request source freeze before launch.",
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(execute(args, dataset))


if __name__ == "__main__":
    raise SystemExit(main())
