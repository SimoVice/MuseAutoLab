"""Bounded ordinary-chat tip-rack evaluation, dry run by default.

One attempt per frozen case, eight physical Meta requests maximum, no retries.
Fixtures are deterministic setup, not live evidence. Strict replay has no network.
Raw requests, responses, failures, source hashes and usage stay in ignored .local.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
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
FIXTURES = {
    "original",
    "comparison",
    "printer_yes",
    "selected_tipone",
    "selected_tipone_printer_yes",
}
OUTCOMES = {
    "printer_question",
    "no_printer",
    "needs_dimensions",
    "commercial",
    "placement_confirmation",
    "printed",
    "unchanged",
}


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("Use a schema_version 1 tip-options dataset.")
    if not 1 <= len(data["cases"]) <= MAX_CALLS:
        raise ValueError("Declare one to eight isolated cases.")
    if (
        type(data.get("max_model_calls")) is not int
        or not 1 <= data["max_model_calls"] <= MAX_CALLS
    ):
        raise ValueError("The physical call cap must be one to eight.")
    if not shared.owned_path(data["baseline"]).is_file():
        raise ValueError("A public synthetic product baseline is required.")
    seen = set()
    for case in data["cases"]:
        cid = case.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cid) or cid in seen:
            raise ValueError("Case ids must be safe and unique.")
        seen.add(cid)
        if case.get("fixture") not in FIXTURES or not isinstance(case.get("prompt"), str):
            raise ValueError("Declare a fixture and a prompt.")
        if not case["prompt"].strip() or case.get("clarification"):
            raise ValueError("Exactly one predeclared message per case; no prompt repair.")
        if case.get("expected", {}).get("outcome") not in OUTCOMES:
            raise ValueError("Declare the expected tip-rack outcome.")
    return data


def assert_closed_provider_schema(schema: dict) -> None:
    """Fail locally before spending a call on an unsupported open object."""
    invalid = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                invalid.append(path)
            for key, value in node.items():
                visit(value, path + "/" + key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, path + "/" + str(index))

    visit(schema, "$")
    if invalid:
        raise ValueError("Provider schema contains open objects: " + ", ".join(invalid))


def make_fixtures(baseline: Path) -> dict:
    """Use product functions for setup only, without any model request."""
    from app.project_storage import decode_snapshot, make_snapshot, restore_snapshot
    from app.tip_racks import (
        TipRackUpdate,
        select_tip_rack,
        show_tip_options,
        tip_rack_options,
        update_tip_request,
    )

    original_snapshot = decode_snapshot(baseline.read_bytes())
    original, history = restore_snapshot(original_snapshot)
    assert original.get("engineering_design") and not original.get("tip_rack")
    comparison, question = show_tip_options(original)
    printer_yes = update_tip_request(comparison, TipRackUpdate(), "I have access to a 3D printer.")
    literal = "Choose TipOne for this synthetic deterministic setup."
    choice = TipRackUpdate(profile_id="tipone_96_tiprack_200ul", source=literal)
    selected = update_tip_request(comparison, choice, literal)
    selected, run = select_tip_rack(selected, choice, literal, accept_placement=True)
    assert run["status"] == "accepted"
    selected_yes = update_tip_request(selected, TipRackUpdate(), "I have access to a 3D printer.")
    values = {
        "original": original,
        "comparison": comparison,
        "printer_yes": printer_yes,
        "selected_tipone": selected,
        "selected_tipone_printer_yes": selected_yes,
    }
    snapshots = {}
    for name, project in values.items():
        context = deepcopy(history)
        if name != "original":
            context += [
                {"role": "user", "content": "Show me alternative tip rack products."},
                {
                    "role": "assistant",
                    "content": question["message"]
                    + "\n"
                    + json.dumps(tip_rack_options(comparison)),
                },
            ]
        snapshots[name] = make_snapshot(project, context)
        snapshots[name]["saved_at"] = original_snapshot["saved_at"]
    return snapshots


def audit_preserved(before: dict, after: dict, *, geometry: bool) -> list[str]:
    for key in (
        "summary",
        "plan",
        "engineering_design",
        "engineering",
        "inspection_extension",
        "labware_rack",
        "labware_plate",
        "brief",
        "workflow",
        "selections",
    ):
        assert after.get(key) == before.get(key), f"Unrelated {key} changed"
    if geometry:
        assert after["design"] == before["design"], "Accepted geometry changed"
        assert after.get("tip_rack") == before.get("tip_rack"), "Accepted tip rack changed"
    else:
        left = {p["id"]: p for p in before["design"]["components"]}
        right = {p["id"]: p for p in after["design"]["components"]}
        assert left.keys() == right.keys(), "Component identities changed"
        for cid in left:
            if cid != "tip-rack":
                assert right[cid] == left[cid], f"Other component {cid} changed"
        for key in ("foundation", "platform", "footprint", "cooling", "constraint_status"):
            assert after["design"].get(key) == before["design"].get(key), f"Design {key} changed"
    return [
        "recipe_source_and_other_modules_preserved",
        "geometry_preserved" if geometry else "only_tip_rack_geometry_changed",
    ]


def audit_selected(before: dict, after: dict, expected: dict) -> list[str]:
    from app.tiprack_geometry import compile_tiprack

    audits = audit_preserved(before, after, geometry=False)
    module = after.get("tip_rack")
    assert module and module["profile_id"] == expected["profile_id"], "Wrong selected profile"
    compiled = compile_tiprack(module)
    for key in ("geometry", "size_mm", "derived"):
        assert module[key] == compiled[key], f"Canonical {key} differs from compiler"
    part = next(p for p in after["design"]["components"] if p["id"] == "tip-rack")
    assert part["geometry"] == module["geometry"] and part["size"] == module["size_mm"]
    assert part["position"][0::2] == module["position_xz_mm"]
    assert module["checks"] and all(c["passed"] for c in module["checks"])
    assert module["metrics"]["physical_fit_verified"] is False
    if "size_mm" in expected:
        shared.assert_equal(module["size_mm"], expected["size_mm"], "Declared reference envelope")
    if "spec" in expected:
        for key, value in expected["spec"].items():
            shared.assert_equal(module["spec"][key], value, key)
        assert module["derived"]["count"] == expected["spec"]["count"]
    group = next(g for g in after["sourcing"]["groups"] if g["id"] == "tip-rack-options")
    assert group["selected_id"] == module["profile_id"]
    return audits + [
        "selected_profile_canonical_geometry_and_sourcing",
        "placement_checks_pass",
        "physical_fit_explicitly_unverified",
    ]


def normalized_tip_request(value: dict | None) -> dict:
    """Compare saved request meaning after the schema fills inert defaults."""
    from app.tip_racks import SavedTipRequest

    return SavedTipRequest.model_validate(value or {}).model_dump(exclude_none=True)


def audit_dimension_request(pending: dict, visible: str) -> None:
    from app.tip_racks import PRINTED_ID

    assert pending.get("profile_id") == PRINTED_ID, "Printed request not retained"
    assert re.search(r"provide|measure|need|fornisci|misur|servono", visible), (
        "No explicit request for missing mating dimensions"
    )
    for role in (
        r"body|corpo",
        r"rim|bordo",
        r"below|sotto",
        r"count|positions|posizioni",
        r"columns|colonne",
    ):
        assert re.search(role, visible), "Missing physical role in dimension request"


class Evaluation(shared.Evaluation):
    def __init__(self, *args, **kwargs):
        self.own_hashes = {
            str(Path(__file__)): shared.digest(Path(__file__).read_bytes()),
            str(Path(shared.__file__)): shared.digest(Path(shared.__file__).read_bytes()),
        }
        super().__init__(*args, **kwargs)
        self.fixtures = make_fixtures(shared.owned_path(self.dataset["baseline"]))
        folder = self.output / "fixtures"
        folder.mkdir()
        for name, value in self.fixtures.items():
            (folder / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
        self.fixture_hashes = {str(p): shared.digest(p.read_bytes()) for p in folder.iterdir()}
        self.save()

    def guard(self):
        super().guard()
        for path, expected in {**self.own_hashes, **getattr(self, "fixture_hashes", {})}.items():
            if shared.digest(Path(path).read_bytes()) != expected:
                self.abort_reason = "Harness, helper or fixture changed during frozen run."
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
            fixture_scope="Deterministic setup only; not live Meta evidence.",
            reviewed_payload_manifest=getattr(self, "review_manifest", None),
            token_totals_interpretation="Sum of reported usage fields only; missing usage "
            "means actual consumption is unknown, never zero.",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def instrument(self, original_send, settings):
        tracked = super().instrument(original_send, settings)

        async def send(client, request, *args, **kwargs):
            if not str(request.url).startswith("http://evaluation.local/"):
                body = json.loads(request.content)
                if self.replay is None:
                    schema = body.get("response_format", {}).get("json_schema", {}).get("schema")
                    if not isinstance(schema, dict):
                        self.abort_reason = (
                            "Every provider request requires a reviewed strict schema."
                        )
                        raise shared.EvaluationAbort(self.abort_reason)
                    try:
                        assert_closed_provider_schema(schema)
                    except ValueError as exc:
                        self.abort_reason = str(exc)
                        raise shared.EvaluationAbort(self.abort_reason) from exc
                review = getattr(self, "reviewed_payloads", {}).get(self.case_id)
                if review is not None:
                    expected = shared.normalized_request(review)
                    actual = shared.normalized_request(json.loads(request.content))
                    if actual != expected:
                        self.abort_reason = "Request differs from reviewed synthetic payload."
                        raise shared.EvaluationAbort(self.abort_reason)
                if any(record["case_id"] == self.case_id for record in self.calls):
                    self.abort_reason = "One provider attempt per case; retry blocked before send."
                    raise shared.EvaluationAbort(self.abort_reason)
                if body.get("model") != MODEL:
                    self.abort_reason = "Only the approved Spark Contributor model is permitted."
                    raise shared.EvaluationAbort(self.abort_reason)
            return await tracked(client, request, *args, **kwargs)

        return send

    async def audit_documents(self, client, project, folder):
        from app.assembly import build_document_files

        pid, revision = project["id"], project["revision"]
        response = await client.get(
            f"/api/projects/{pid}/instructions", params={"revision": revision}
        )
        assert response.status_code == 200, "Current instructions unavailable"
        guide = response.json()
        assert guide["tip_rack"] == project["tip_rack"], "Guide selected module differs"
        docs = build_document_files(project)
        assert json.loads(docs["assembly.json"]) == guide, "Packaged instructions differ"
        for name in ("assembly.json", "assembly-guide.html", "assembly-guide.md"):
            (folder / name).write_bytes(docs[name])
        response = await client.get(f"/api/projects/{pid}/snapshot", params={"revision": revision})
        assert response.status_code == 200
        (folder / "portable-project.json").write_bytes(response.content)
        opened = await client.post(
            "/api/projects/open",
            content=response.content,
            headers={"Content-Type": "application/json"},
        )
        assert opened.status_code == 201, f"Portable reopen failed: {opened.text}"
        restored = opened.json()["project"]
        for key in (
            "revision",
            "status",
            "summary",
            "plan",
            "design",
            "engineering_design",
            "inspection_extension",
            "labware_rack",
            "labware_plate",
            "tip_rack",
            "fabrication_capabilities",
            "sourcing",
        ):
            assert restored.get(key) == project.get(key), f"Portable reopen changed {key}"
        assert normalized_tip_request(restored.get("tip_rack_request")) == normalized_tip_request(
            project.get("tip_rack_request")
        ), "Portable reopen changed tip-rack request information"
        return ["current_and_packaged_guide_agree", "portable_roundtrip_preserves_tip_rack"]

    async def run_case(self, client, api, case):
        from app.tip_racks import PRINTED_ID, tip_rack_options

        self.case_id, self.turn_index = case["id"], 0
        folder = self.output / case["id"]
        folder.mkdir()
        record = {"id": case["id"], "expected": case["expected"], "status": "started", "turns": []}
        self.cases.append(record)
        project = None
        try:
            self.guard()
            response = await client.post("/api/projects/open", json=self.fixtures[case["fixture"]])
            assert response.status_code == 201, f"Fixture open failed: {response.text}"
            project = response.json()["project"]
            before = deepcopy(project)
            record["baseline_project"] = before
            (folder / "before-project.json").write_text(
                json.dumps(before, indent=2), encoding="utf-8"
            )
            api._sessions[project["id"]].model = MODEL
            attempts_before = len(self.calls)
            started = time.monotonic()
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
            record["provider_attempts"] = len(self.calls) - attempts_before
            record["execution_route"] = (
                "model_assisted"
                if record["provider_attempts"]
                else "deterministic_product_handling"
            )
            self.save()
            self.guard()
            assert record["provider_attempts"] <= 1
            outcome = case["expected"]["outcome"]
            assert response.status_code in ((200, 422) if outcome == "unchanged" else (200,)), (
                f"HTTP {response.status_code} is not acceptance"
            )
            reply = data.get("assistant_message", data.get("detail", ""))
            assert isinstance(reply, str) and reply.strip(), "No user-visible explanation"
            visible = re.sub(r"[*_`]+", "", reply.casefold())
            if outcome in {"commercial", "printed"}:
                assert any(
                    r.get("kind") == "select_tip_rack" and r.get("status") == "accepted"
                    for r in data.get("action_runs", [])
                ), "No accepted tip-rack action"
                audits = audit_selected(before, project, case["expected"])
                audits += await self.audit_documents(client, project, folder)
                assert re.search(r"unverified|require|unchecked|still|verific", visible), (
                    "Fit limitations omitted"
                )
            else:
                audits = audit_preserved(before, project, geometry=True)
                options = tip_rack_options(project)
                ids = {o["id"] for o in options["options"]}
                pending = project.get("tip_rack_request", {})
                if outcome == "printer_question":
                    assert pending.get("awaiting_printer") and PRINTED_ID not in ids
                    assert re.search(r"printer|stampante", visible) and "?" in visible
                elif outcome == "no_printer":
                    assert options["printer_available"] == "no" and PRINTED_ID not in ids
                    assert re.search(r"commercial|no printer|no access|non.*stampante", visible)
                elif outcome == "needs_dimensions":
                    assert options["printer_available"] == "yes" and PRINTED_ID in ids
                    audit_dimension_request(pending, visible)
                elif outcome == "placement_confirmation":
                    assert pending.get("awaiting_placement"), (
                        "Direct product choice skipped placement confirmation"
                    )
                    assert pending.get("profile_id") == case["expected"]["profile_id"]
                    assert re.search(r"confirm|conferm", visible) and re.search(
                        r"shift|spost|move", visible
                    )
                    # This explicit deterministic API choice is separate from the live chat outcome.
                    accepted = await client.post(
                        f"/api/projects/{project['id']}/tip-rack-options",
                        json={
                            "revision": project["revision"],
                            "profile_id": case["expected"]["profile_id"],
                        },
                    )
                    record["deterministic_followup"] = {
                        "http_status": accepted.status_code,
                        "response": accepted.json(),
                        "scope": "Explicit UI-choice API after the observed confirmation request; "
                        "no Meta call or claim of live chat acceptance.",
                    }
                    assert accepted.status_code == 200, "Explicit choice API failed"
                    applied = accepted.json()["project"]
                    audits += audit_selected(project, applied, case["expected"])
                    audits += await self.audit_documents(client, applied, folder)
                else:
                    assert project == before, "Rejected/unknown request changed canonical state"
                    assert re.search(
                        r"not changed|preserv|unchanged|not supported|unsupported|no reviewed|"
                        r"cannot|invalid|too narrow|unverified|dimension",
                        visible,
                    )
                audits += ["visible_expected_conversation_gate"]
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


async def execute(args, dataset):
    import app.api as api
    from app.model_client import ModelSettings, _strict_schema

    if args.live:
        assert_closed_provider_schema(_strict_schema())

    recorded = json.loads(args.replay.read_text(encoding="utf-8")) if args.replay else None
    if recorded and recorded["dataset_sha256_before"] != shared.digest(args.dataset.read_bytes()):
        raise ValueError("Replay requires the exact frozen dataset.")
    if recorded:
        settings = ModelSettings("offline-recorded-replay", "https://replay.invalid/v1", MODEL)
    else:
        configured = ModelSettings.load()
        settings = ModelSettings(configured.api_key, configured.base_url, MODEL)
    output = (
        args.output
        or ROOT
        / ".local/tip-options-evaluation"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Raw evaluation evidence must remain in ignored .local.")
    output.parent.mkdir(parents=True, exist_ok=True)
    run = Evaluation(
        args.dataset,
        dataset,
        output,
        min(args.max_calls, dataset["max_model_calls"]),
        replay=recorded,
    )
    if args.review_manifest:
        review = json.loads(args.review_manifest.read_text(encoding="utf-8"))
        if review["dataset_sha256"] != run.dataset_sha256:
            raise ValueError("Review does not match the frozen evaluation dataset.")
        if review["source_sha256"] != run.source_before["sha256"]:
            raise ValueError("Review does not match the frozen app/web source.")
        run.reviewed_payloads = {}
        for entry in review["requests"]:
            path = Path(entry["path"])
            if shared.digest(path.read_bytes()) != entry["sha256"]:
                raise ValueError("A reviewed prospective request changed.")
            run.reviewed_payloads[entry["case_id"]] = json.loads(path.read_bytes())
        if set(run.reviewed_payloads) != {case["id"] for case in dataset["cases"]}:
            raise ValueError("Every case requires its reviewed prospective payload.")
        run.review_manifest = {
            "path": str(args.review_manifest.resolve()),
            "sha256": shared.digest(args.review_manifest.read_bytes()),
            "scope": "Every external body must match its reviewed synthetic payload "
            "beyond runtime UUIDs, or is blocked before send.",
        }
        run.save()
    print(
        json.dumps(
            {
                "stage": "frozen_before_provider_attempts",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "dataset_sha256": run.dataset_sha256,
                "source_sha256": run.source_before["sha256"],
                "harness_and_helper_sha256": run.own_hashes,
                "fixture_sha256": run.fixture_hashes,
                "max_provider_calls": run.max_calls,
            }
        ),
        flush=True,
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
                        replaying_abort = bool(recorded and recorded.get("abort_reason"))
                        if (
                            (not recorded or replaying_abort)
                            and run.calls
                            and run.calls[-1].get("http_status") != 200
                        ):
                            run.abort_reason = (
                                "Provider request failed; remaining cases blocked by fail-fast "
                                "gate. No automatic retry or additional case was sent."
                            )
                        elif (not recorded or replaying_abort) and run.cases[-1].get("turns", []):
                            visible = run.cases[-1]["turns"][-1]["response"]
                            if visible.get("failure_kind") == "source_validation":
                                run.abort_reason = (
                                    "Product source validation failed; remaining cases blocked "
                                    "by fail-fast gate. No automatic retry was sent."
                                )
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
                "cases": [
                    {k: c.get(k) for k in ("id", "status", "error", "execution_route")}
                    for c in run.cases
                ],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if not run.abort_reason and all(c["status"] == "passed" for c in run.cases) else 1


async def prepare_requests(args, dataset):
    """Capture actual prospective bodies with every external transport blocked.

    Credentials are never written. The real endpoint is recorded for review;
    provider calls receive an offline 503 before any network transport runs.
    """
    import app.api as api
    from app.model_client import ModelSettings

    configured = ModelSettings.load()
    settings = ModelSettings("offline-inspection-no-credential", configured.base_url, MODEL)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Prospective payload review must remain in ignored .local.")
    output.mkdir(parents=True, exist_ok=False)
    fixtures = make_fixtures(shared.owned_path(dataset["baseline"]))
    original_send = httpx.AsyncClient.send
    records = []
    current_case = None

    async def blocked_send(client, request, *a, **kw):
        if str(request.url).startswith("http://evaluation.local/"):
            return await original_send(client, request, *a, **kw)
        assert str(request.url) == settings.base_url + "/chat/completions"
        body = request.content
        path = output / (current_case + "-prospective-request.json")
        path.write_bytes(body)
        parsed = json.loads(body)
        private_markers = [
            "Xsensio",
            "00_GESTIONE",
            "CONTESTO.md",
            "DIARIO.md",
            "C:\\Users\\",
            ".env",
        ]
        markers_found = [
            value for value in private_markers if value.casefold() in body.decode().casefold()
        ]
        records.append(
            {
                "case_id": current_case,
                "path": str(path),
                "sha256": shared.digest(body),
                "bytes": len(body),
                "destination": str(request.url),
                "model": parsed.get("model"),
                "top_level_fields": sorted(parsed),
                "messages": [
                    {"role": m["role"], "characters": len(m.get("content", ""))}
                    for m in parsed["messages"]
                ],
                "private_marker_scan": markers_found,
                "credential_present_in_body": bool(
                    configured.api_key and configured.api_key.encode() in body
                ),
                "email_addresses": re.findall(
                    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", body.decode()
                ),
                "transport": "Blocked before send; offline synthetic 503 response; "
                "no external request.",
            }
        )
        return httpx.Response(
            503,
            json={
                "error": {"message": "Offline prospective-payload inspection; transport blocked."}
            },
            request=request,
        )

    with (
        patch.object(ModelSettings, "load", return_value=settings),
        patch.object(httpx.AsyncClient, "send", blocked_send),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False),
            base_url="http://evaluation.local",
        ) as client:
            for case in dataset["cases"]:
                current_case = case["id"]
                opened = await client.post("/api/projects/open", json=fixtures[case["fixture"]])
                assert opened.status_code == 201, opened.text
                project = opened.json()["project"]
                api._sessions[project["id"]].model = MODEL
                await client.post(
                    f"/api/projects/{project['id']}/messages", json={"message": case["prompt"]}
                )
    baseline = shared.owned_path(dataset["baseline"])
    tracked = subprocess.run(
        ["git", "show", "HEAD:" + dataset["baseline"]], cwd=ROOT, capture_output=True, check=True
    ).stdout
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    report = {
        "scope": "Prospective request bodies only; all external transport blocked. "
        "Synthetic public-baseline inputs and developer-written messages; "
        "no live response evidence.",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "physical_provider_calls": 0,
        "dataset_sha256": shared.digest(args.dataset.read_bytes()),
        "source_sha256": shared.source_fingerprint()["sha256"],
        "baseline": str(baseline),
        "baseline_sha256": shared.digest(baseline.read_bytes()),
        "baseline_tracked_head_sha256": shared.digest(tracked),
        "baseline_matches_tracked_head": baseline.read_bytes() == tracked,
        "git_head": head,
        "baseline_public_commit": "b6054c5ff003d20ec4a301852da968cba76f8e6e",
        "input_sources": [
            dataset["baseline"],
            "app/tip_racks.py reviewed public supplier definitions",
            "docs/examples/tip-options-evaluation-cases.json synthetic prompts/dimensions",
            "app/model_client.py product system/schema instructions",
        ],
        "excluded_inputs": [
            "Parent startup/thesis/employer records",
            "Real printer inventory or identity",
            "Environment/credential values and headers",
        ],
        "requests": records,
    }
    (output / "review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return (
        0
        if len(records) == len(dataset["cases"])
        and all(
            not r["private_marker_scan"]
            and not r["credential_present_in_body"]
            and not r["email_addresses"]
            for r in records
        )
        else 1
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "docs/examples/tip-options-evaluation-cases.json"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    mode.add_argument(
        "--prepare-requests",
        action="store_true",
        help="Capture prospective request bodies with external transport blocked; "
        "no Meta consumption",
    )
    parser.add_argument("--max-calls", type=int, choices=range(1, MAX_CALLS + 1), default=MAX_CALLS)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--review-manifest",
        type=Path,
        help="Permit only bodies identical to reviewed payloads beyond runtime UUIDs",
    )
    args = parser.parse_args(argv)
    args.dataset = args.dataset.resolve()
    data = load_dataset(args.dataset)
    if args.prepare_requests:
        if not args.output:
            parser.error("--prepare-requests requires a fresh private --output folder")
        return asyncio.run(prepare_requests(args, data))
    if not args.live and not args.replay:
        print(
            json.dumps(
                {
                    "evidence_mode": "dry_run",
                    "physical_provider_calls": 0,
                    "dataset_sha256": shared.digest(args.dataset.read_bytes()),
                    "case_ids": [c["id"] for c in data["cases"]],
                    "max_provider_calls": min(args.max_calls, data["max_model_calls"]),
                    "note": "No cases executed; explicit --live required.",
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(execute(args, data))


if __name__ == "__main__":
    raise SystemExit(main())
