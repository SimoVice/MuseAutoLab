"""Evaluate a frozen developer-defined rack dataset through actual product turns.

Default execution only validates inputs and prints a plan. --live explicitly
permits bounded Meta calls; --replay reuses all recorded responses with no new
provider consumption. Neither mode is an independent held-out benchmark.

The dataset supplies every prompt and at most one clarification per case. This
harness never repairs prompts, synthesizes accepted results or changes app code.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODEL = "muse-spark-1.3-contributor"
MAX_CALLS = 16
EXCLUDED_DIRECTORIES = {
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".git",
    ".vite",
    ".cache",
    "test-results",
    "playwright-report",
}


class EvaluationAbort(RuntimeError):
    """A frozen input/source or bounded-call contract was violated."""


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_fingerprint(root: Path | None = None) -> dict:
    """Fingerprint app/web code and owned assets, excluding generated dependencies."""
    root = root or ROOT
    files = {}
    for scope in ("app", "web"):
        for folder, directories, filenames in os.walk(root / scope):
            directories[:] = sorted(d for d in directories if d not in EXCLUDED_DIRECTORIES)
            for filename in sorted(filenames):
                if filename.startswith(".env") or filename.endswith((".pyc", ".tsbuildinfo")):
                    continue
                path = Path(folder) / filename
                files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return {"sha256": digest(json.dumps(files, sort_keys=True).encode()), "files": files}


def owned_path(value: str, root: Path | None = None) -> Path:
    root = root or ROOT
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or path.name.startswith(".env"):
        raise ValueError("Evaluation inputs must be non-secret product files within this checkout.")
    return path


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Use a schema_version 1 evaluation dataset.")
    cases = data.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        raise ValueError("The dataset must contain 1 to 32 cases.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,80}", case.get("id", "")
        ):
            raise ValueError("Each case needs a bounded, filename-safe id.")
        if case["id"] in ids:
            raise ValueError("Case ids must be unique.")
        ids.add(case["id"])
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError("Every case requires its predeclared prompt.")
        if case.get("clarification") is not None and not isinstance(case["clarification"], str):
            raise ValueError("At most one predeclared clarification string is supported per case.")
        expected = case.get("expected")
        if not isinstance(expected, dict) or expected.get("outcome") not in {
            "accepted",
            "needs_dimensions",
            "rejected",
            "unsupported",
            "unchanged",
        }:
            raise ValueError("Each case requires an explicit expected outcome.")
        baseline = case.get("baseline", data.get("baseline"))
        if not baseline or not owned_path(baseline).is_file():
            raise ValueError("Every case needs a recorded portable baseline file.")
    return data


def pointer(document, path: str):
    """Read an RFC 6901 JSON pointer for dataset-defined exact assertions."""
    if not path:
        return document
    if not path.startswith("/"):
        raise ValueError("Expected assertion paths must be JSON pointers.")
    value = document
    for raw in path[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def assert_equal(actual, expected, label="value") -> None:
    if isinstance(expected, bool) or expected is None:
        assert actual == expected and type(actual) is type(expected), label
    elif isinstance(expected, (int, float)):
        assert not isinstance(actual, bool) and isinstance(actual, (int, float)), label
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-8), label
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), label
        for index, (left, right) in enumerate(zip(actual, expected)):
            assert_equal(left, right, f"{label}[{index}]")
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), label
        for key in expected:
            assert_equal(actual[key], expected[key], f"{label}.{key}")
    else:
        assert actual == expected, label


def token_totals(calls: list[dict]) -> dict:
    totals = {key: 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    missing = 0
    for call in calls:
        usage = call.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        missing += not all(key in usage for key in totals)
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
    return {**totals, "calls_with_incomplete_usage": missing}


def normalized_request(body: dict) -> str:
    """Remove only runtime UUID variation when verifying a recorded-response replay."""
    text = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<runtime-project-uuid>",
        text,
    )


def audit_inspection_targets(before: dict, after: dict, rack_part: dict) -> None:
    """Permit only the derived rack-surface height in unchanged inspection frames."""
    original = before.get("inspection_extension")
    actual = after.get("inspection_extension")
    if original is None:
        assert actual is None, "Rack update added an inspection extension"
        return
    assert isinstance(actual, dict), "Rack update removed the inspection extension"
    expected = deepcopy(original)
    frames = expected.get("pose_frames")
    assert isinstance(frames, list) and frames, "Inspection pose frames are missing"
    assert len(actual.get("pose_frames", [])) == len(frames), "Inspection frame count changed"
    surface_y = rack_part["position"][1] + rack_part["size"][1] / 2
    for index, frame in enumerate(frames):
        target = frame.get("target_mm")
        changed_target = actual["pose_frames"][index].get("target_mm")
        assert isinstance(target, list) and len(target) == 3, "Original target is invalid"
        assert isinstance(changed_target, list) and len(changed_target) == 3, "Target is invalid"
        assert changed_target[0::2] == target[0::2], "Inspection target x/z changed"
        assert_equal(changed_target[1], surface_y, "inspection target follows rack top")
        target[1] = surface_y
    assert actual == expected, "Rack update changed inspection fields beyond target height"


def audit_rack(before: dict, after: dict, expected: dict) -> list[str]:
    """Check independently observable canonical relationships, without compiling an answer."""
    rack = after.get("labware_rack")
    assert rack, "No accepted parametric rack exists"
    parts = {part["id"]: part for part in after["design"]["components"]}
    previous = {part["id"]: part for part in before["design"]["components"]}
    target = rack["target_component_id"]
    assert set(parts) == set(previous), "Rack update changed canonical part identities"
    for cid, part in previous.items():
        if cid != target:
            assert parts[cid] == part, f"Rack update changed unrelated component {cid}"
    for field in ("foundation", "platform", "cooling"):
        assert after["design"].get(field) == before["design"].get(field), field
    for field in ("engineering_design", "summary", "plan", "selections"):
        assert after.get(field) == before.get(field), f"Rack update changed {field}"
    part, deck = parts[target], parts["base"]
    audit_inspection_targets(before, after, part)
    assert_equal(part["size"], rack["size_mm"], "canonical rack envelope")
    assert part["geometry"] == rack["geometry"], "Viewer geometry differs from module geometry"
    assert part["position"][0::2] == previous[target]["position"][0::2], "Rack moved in x/z"
    assert_equal(
        part["position"][1],
        deck["position"][1] + deck["size"][1] / 2 + part["size"][1] / 2,
        "rack sits on current deck",
    )
    assert all(check["passed"] for check in rack["checks"]), "Canonical rack checks failed"
    tops = [p for p in part["geometry"]["primitives"] if p.get("id") == "perforated-top"]
    assert len(tops) == 1, "Rack needs one canonical perforated top"
    holes = tops[0].get("holes", [])
    assert len(holes) == rack["spec"]["count"] == rack["derived"]["count"], "Position count differs"
    assert len({(hole["x_mm"], hole["z_mm"]) for hole in holes}) == len(holes)
    for hole in holes:
        assert_equal(2 * hole["radius_mm"], rack["derived"]["bore_diameter_mm"], "bore diameter")
    if "spec" in expected:
        for key, value in expected["spec"].items():
            assert_equal(rack["spec"][key], value, f"rack spec {key}")
    if "size_mm" in expected:
        assert_equal(rack["size_mm"], expected["size_mm"], "predeclared rack size")
    if "hole_count" in expected:
        assert len(holes) == expected["hole_count"], "Predeclared hole count differs"
    return [
        "canonical_ids",
        "unchanged_source_and_other_modules",
        "inspection_target_height_derived_only",
        "exact_spec_and_envelope",
        "canonical_geometry",
        "hole_count_and_bores",
        "deck_placement",
        "recorded_checks",
    ]


class Evaluation:
    def __init__(
        self,
        dataset_path: Path,
        dataset: dict,
        output: Path,
        max_calls: int,
        *,
        replay: dict | None = None,
    ):
        self.dataset_path, self.dataset, self.output = dataset_path, dataset, output
        self.max_calls, self.replay = max_calls, replay
        self.mode = "recorded_response_replay" if replay is not None else "live"
        self.source_before = source_fingerprint()
        self.dataset_sha256 = digest(dataset_path.read_bytes())
        self.baselines = {
            str(owned_path(case.get("baseline", dataset.get("baseline")))): digest(
                owned_path(case.get("baseline", dataset.get("baseline"))).read_bytes()
            )
            for case in dataset["cases"]
        }
        self.calls, self.cases = [], []
        self.case_id, self.turn_index = "initialization", -1
        self.abort_reason = None
        self.harness_sha256 = digest(Path(__file__).read_bytes())
        self.started = time.monotonic()
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "provider").mkdir()
        self.save()

    def guard(self):
        if source_fingerprint() != self.source_before:
            self.abort_reason = "Application/web source changed during the frozen evaluation."
        elif digest(self.dataset_path.read_bytes()) != self.dataset_sha256:
            self.abort_reason = "Frozen evaluation dataset changed during the run."
        elif any(
            digest(Path(path).read_bytes()) != value for path, value in self.baselines.items()
        ):
            self.abort_reason = "A recorded baseline changed during the run."
        if self.abort_reason:
            raise EvaluationAbort(self.abort_reason)

    def save(self):
        payload = {
            "schema_version": 1,
            "evidence_mode": self.mode,
            "scope": "Synthetic developer-defined bounded cases; not independent held-out "
            "validation, hardware evidence or a generalization benchmark.",
            "model": MODEL,
            "dataset": str(self.dataset_path),
            "dataset_sha256_before": self.dataset_sha256,
            "dataset_sha256_after": digest(self.dataset_path.read_bytes()),
            "baseline_sha256": self.baselines,
            "source_before": self.source_before,
            "source_after": source_fingerprint(),
            "harness_sha256": self.harness_sha256,
            "harness_sha256_after": digest(Path(__file__).read_bytes()),
            "max_model_calls": self.max_calls,
            "physical_provider_calls": len(self.calls) if self.mode == "live" else 0,
            "recorded_attempts": len(self.calls),
            "usage_scope": "Reported consumption for this live run"
            if self.mode == "live"
            else "Historical recorded usage only; no new provider consumption",
            "token_totals": token_totals(self.calls),
            "provider_calls": self.calls,
            "cases": self.cases,
            "abort_reason": self.abort_reason,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
        }
        (self.output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def instrument(self, original_send, settings):
        async def send(client, request, *args, **kwargs):
            if str(request.url).startswith("http://evaluation.local/"):
                return await original_send(client, request, *args, **kwargs)
            if str(request.url) != f"{settings.base_url}/chat/completions":
                self.abort_reason = (
                    "Unexpected external request; evaluation only permits Meta turns."
                )
                raise EvaluationAbort(self.abort_reason)
            self.guard()
            if len(self.calls) >= self.max_calls:
                self.abort_reason = "Physical provider-call limit reached; no extra request sent."
                raise EvaluationAbort(self.abort_reason)
            body = json.loads(request.content)
            number = len(self.calls) + 1
            record = {
                "number": number,
                "case_id": self.case_id,
                "turn_index": self.turn_index,
                "request": body,
                "url": str(request.url),
                "status": "started",
                "schema": body.get("response_format", {}).get("json_schema", {}).get("name"),
            }
            self.calls.append(record)
            (self.output / "provider" / f"{number:03d}-request.json").write_bytes(request.content)
            self.save()
            started = time.monotonic()
            try:
                if self.replay is None:
                    response = await original_send(client, request, *args, **kwargs)
                    await response.aread()
                else:
                    records = self.replay["provider_calls"]
                    if number > len(records):
                        raise EvaluationAbort("No recorded provider attempt remains for replay.")
                    previous = records[number - 1]
                    assert (previous["case_id"], previous["turn_index"], previous["schema"]) == (
                        self.case_id,
                        self.turn_index,
                        record["schema"],
                    ), "Replay attempt mismatch"
                    assert normalized_request(previous["request"]) == normalized_request(body), (
                        "Replay request differs beyond runtime project UUIDs"
                    )
                    if "http_status" not in previous:
                        raise httpx.ReadTimeout(
                            "Replaying the recorded transport failure", request=request
                        )
                    response = httpx.Response(
                        previous["http_status"],
                        content=previous["response_body"].encode("utf-8"),
                        request=request,
                    )
                record.update(
                    http_status=response.status_code,
                    response_body=response.text,
                    status="completed" if response.is_success else "provider_error",
                )
                (self.output / "provider" / f"{number:03d}-response.body").write_bytes(
                    response.content
                )
                try:
                    parsed = response.json()
                    record["usage"] = parsed.get("usage", {})
                    record["actual_model"] = parsed.get("model")
                except (ValueError, AttributeError):
                    record["usage"] = {}
                return response
            except BaseException as exc:
                record.update(status="transport_or_replay_error", error_type=type(exc).__name__)
                raise
            finally:
                record["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self.save()

        return send

    async def run_case(self, client, api, case):
        self.case_id = case["id"]
        folder = self.output / case["id"]
        folder.mkdir()
        record = {"id": case["id"], "expected": case["expected"], "status": "started", "turns": []}
        self.cases.append(record)
        project = None
        try:
            self.guard()
            baseline = owned_path(case.get("baseline", self.dataset.get("baseline")))
            response = await client.post(
                "/api/projects/open",
                content=baseline.read_bytes(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 201, f"Baseline reopen failed: {response.text}"
            project = response.json()["project"]
            assert not project.get("labware_rack"), (
                "Use an isolated baseline without an existing custom rack"
            )
            before = deepcopy(project)
            api._sessions[project["id"]].model = MODEL
            record["baseline"] = str(baseline)
            record["baseline_project"] = before
            (folder / "before-project.json").write_text(
                json.dumps(before, indent=2), encoding="utf-8"
            )
            prompts = [case["prompt"]]
            if case.get("clarification"):
                prompts.append(case["clarification"])
            for index, prompt in enumerate(prompts):
                self.turn_index = index
                self.guard()
                started = time.monotonic()
                response = await client.post(
                    f"/api/projects/{project['id']}/messages", json={"message": prompt}
                )
                data = response.json()
                project = deepcopy(api._sessions[project["id"]].project)
                turn = {
                    "index": index,
                    "prompt": prompt,
                    "http_status": response.status_code,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "response": data,
                }
                record["turns"].append(turn)
                self.save()
                self.guard()
                print(
                    json.dumps(
                        {
                            "case": case["id"],
                            "turn": index,
                            "http": response.status_code,
                            "provider_attempts": len(self.calls),
                        }
                    ),
                    flush=True,
                )
                accepted = any(
                    run.get("kind") == "develop_labware" and run.get("status") == "accepted"
                    for run in data.get("action_runs", [])
                )
                if index == 0 and case.get("first_turn_expected"):
                    first = case["first_turn_expected"]
                    assert first["outcome"] == "needs_dimensions", "Unsupported first-turn audit"
                    assert not project.get("labware_rack"), "First turn guessed a rack"
                    assert project["design"] == before["design"], "First turn changed geometry"
                    brief = project.get("labware_brief") or {}
                    assert brief.get("status") == "needs_dimensions" and brief.get("missing_fields")
                    for key in ("count", "columns"):
                        assert_equal(
                            brief["spec"].get(key),
                            case["expected"]["spec"][key],
                            f"first-turn retained {key}",
                        )
                    record["first_turn_audits"] = [
                        "missing_dimensions_explicit",
                        "no_guessed_rack",
                        "geometry_preserved",
                        "count_and_columns_retained",
                    ]
                if (
                    accepted
                    or response.status_code != 200
                    or case["expected"]["outcome"] != "accepted"
                ):
                    break
            expected = case["expected"]
            if expected["outcome"] == "accepted":
                assert accepted, "Product turn did not accept a develop_labware action"
                assert response.status_code == 200, f"Product HTTP {response.status_code}"
                audits = audit_rack(before, project, expected)
                audits += await self.audit_documents_and_roundtrip(client, project, folder)
            elif expected["outcome"] == "needs_dimensions":
                assert not project.get("labware_rack"), "Incomplete measurements produced a rack"
                assert project["design"] == before["design"], (
                    "Incomplete measurements changed geometry"
                )
                brief = project.get("labware_brief") or {}
                assert brief.get("status") == "needs_dimensions" and brief.get("missing_fields")
                if "missing_fields" in expected:
                    assert set(brief["missing_fields"]) == set(expected["missing_fields"])
                audits = ["missing_dimensions_explicit", "no_invented_rack", "geometry_preserved"]
            else:
                assert response.status_code in (200, 422), (
                    "A provider/server failure is not a successful negative: "
                    f"HTTP {response.status_code}"
                )
                assert project == before, "Negative/unsupported turn changed the canonical project"
                assert not project.get("labware_rack"), "Negative turn produced a rack"
                audits = ["whole_project_preserved", "no_accepted_rack"]
            for path, value in expected.get("equals", {}).items():
                assert_equal(pointer(project, path), value, path)
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

    async def audit_documents_and_roundtrip(self, client, project, folder):
        from app.assembly import build_document_files

        query = {"revision": project["revision"]}
        pid = project["id"]
        response = await client.get(f"/api/projects/{pid}/instructions", params=query)
        assert response.status_code == 200, "Instruction preview failed"
        guide = response.json()
        assert guide["labware_rack"] == project["labware_rack"], "Guide module differs"
        target = project["labware_rack"]["target_component_id"]
        part = next(p for p in guide["parts"] if p["component_id"] == target)
        canonical = next(p for p in project["design"]["components"] if p["id"] == target)
        assert part["size_mm"] == canonical["size"] and part["position_mm"] == canonical["position"]
        steps = {s["id"]: s for s in guide["steps"]}
        for sid in ("rack-inputs", "rack-print", "rack-fit", "rack-placement"):
            assert target in steps[sid]["component_ids"], f"Missing guide step {sid}"
        docs = build_document_files(project)
        assert json.loads(docs["assembly.json"]) == guide, "Packaged guide differs from preview"
        for name in ("assembly.json", "assembly-guide.html", "assembly-guide.md"):
            (folder / name).write_bytes(docs[name])
        saved = await client.get(f"/api/projects/{pid}/snapshot", params=query)
        assert saved.status_code == 200, "Portable save failed"
        (folder / "portable-project.json").write_bytes(saved.content)
        reopened = await client.post(
            "/api/projects/open",
            content=saved.content,
            headers={"Content-Type": "application/json"},
        )
        assert reopened.status_code == 201, f"Portable reopen failed: {reopened.text}"
        restored = reopened.json()["project"]
        for key in (
            "revision",
            "status",
            "design",
            "engineering_design",
            "inspection_extension",
            "labware_rack",
            "labware_brief",
            "sourcing",
        ):
            assert restored.get(key) == project.get(key), f"Save/reopen changed {key}"
        assert restored["id"] != project["id"], "Reopen did not create a new runtime session"
        return [
            "guide_component_and_module_coherence",
            "same_packaged_guide",
            "save_reopen_roundtrip",
        ]


async def execute(args, dataset: dict) -> int:
    sys.path.insert(0, str(ROOT))
    import app.api as api
    from app.model_client import ModelSettings

    recorded = json.loads(args.replay.read_text(encoding="utf-8")) if args.replay else None
    if recorded and recorded["dataset_sha256_before"] != digest(args.dataset.read_bytes()):
        raise ValueError("Replay requires the exact original frozen dataset.")
    if recorded:
        settings = ModelSettings("offline-recorded-replay", "https://replay.invalid/v1", MODEL)
    else:
        configured = ModelSettings.load()
        settings = ModelSettings(configured.api_key, configured.base_url, MODEL)
    maximum = min(args.max_calls, dataset.get("max_model_calls", MAX_CALLS))
    output = args.output or ROOT / ".local" / "labware-evaluation" / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S%fZ")
    output = output.resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Raw evaluation records must stay in the ignored .local directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    run = Evaluation(args.dataset, dataset, output, maximum, replay=recorded)
    original = httpx.AsyncClient.send
    try:
        with (
            patch.object(ModelSettings, "load", return_value=settings),
            patch.object(httpx.AsyncClient, "send", run.instrument(original, settings)),
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
    except EvaluationAbort as exc:
        run.abort_reason = str(exc)
    finally:
        run.save()
    summary = {
        "output": str(output),
        "evidence_mode": run.mode,
        "physical_provider_calls": len(run.calls) if args.live else 0,
        "token_totals": token_totals(run.calls),
        "abort_reason": run.abort_reason,
        "cases": [{key: case.get(key) for key in ("id", "status", "error")} for case in run.cases],
    }
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if not run.abort_reason and all(c["status"] == "passed" for c in run.cases) else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dataset", type=Path, required=True)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Explicitly permit bounded Meta requests")
    mode.add_argument("--replay", type=Path, help="Replay a previous results.json without network")
    result.add_argument("--max-calls", type=int, choices=range(1, MAX_CALLS + 1), default=MAX_CALLS)
    result.add_argument(
        "--output", type=Path, help="Fresh evidence directory; existing output is never overwritten"
    )
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    args.dataset = args.dataset.resolve()
    data = load_dataset(args.dataset)
    if not args.live and not args.replay:
        print(
            json.dumps(
                {
                    "evidence_mode": "dry_run",
                    "physical_provider_calls": 0,
                    "dataset_sha256": digest(args.dataset.read_bytes()),
                    "source_fingerprint": source_fingerprint()["sha256"],
                    "baseline_paths": sorted(
                        {c.get("baseline", data.get("baseline")) for c in data["cases"]}
                    ),
                    "case_ids": [c["id"] for c in data["cases"]],
                    "max_provider_calls": min(
                        args.max_calls, data.get("max_model_calls", MAX_CALLS)
                    ),
                    "note": "No case executed. --live requires explicit launch authorization.",
                },
                indent=2,
            )
        )
        return 0
    return asyncio.run(execute(args, data))


if __name__ == "__main__":
    raise SystemExit(main())
