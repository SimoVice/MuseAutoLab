"""Human guide assets, standalone execution and actual loopback device integration."""

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import sleep
from urllib.parse import unquote, urljoin, urlsplit

import pytest

from app.concept_controller import HttpGatewayAdapter, load_project, run_sequence
from app.concept_guide import (
    build_concept_guide,
    concept_controller_source,
    concept_gateway_config,
)


def project():
    return {
        "project_id": "example",
        "revision": 3,
        "design": {
            "title": "Sample rotation station",
            "overview": "Review samples in a proposed holder.",
            "footprint_mm": [420, 300],
            "components": [
                {
                    "key": "rotary-holder",
                    "name": "Rotating sample holder",
                    "role": "Present a sample",
                    "assembly": "Attach to a reviewed mount.",
                    "check": "Verify retention.",
                    "source": {
                        "title": "Manufacturer reference",
                        "url": "https://example.com/part",
                    },
                }
            ],
            "supplies": [
                {
                    "name": "Sample vessels",
                    "quantity": 4,
                    "unit": "each",
                    "role": "Hold representative samples",
                    "source": None,
                }
            ],
            "steps": [
                {
                    "name": "Present sample",
                    "instruction": "Turn the holder for inspection.",
                    "component_keys": ["rotary-holder"],
                    "component_names": ["Rotating sample holder"],
                    "moving_key": "rotary-holder",
                    "translation_mm": [0, 0, 0],
                    "rotation_deg": 45,
                    "rotation_axis": "y",
                    "pivot_mm": [0, 0, 0],
                }
            ],
            "software": {
                "controller": "Select an actual controller.",
                "interfaces": ["Rotation drive"],
                "setup": ["Review the configuration."],
                "checks": ["Test stop behavior."],
            },
            "open_questions": ["Which vessel is required?"],
        },
    }


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href")

    def handle_data(self, data):
        self.text.append(data)


def test_guide_links_resolve_on_server_and_in_offline_package(tmp_path):
    data = project()
    original = deepcopy(data)
    page = build_concept_guide(data["design"], data["project_id"], data["revision"])
    parser = Links()
    parser.feed(page.decode())
    assert data == original
    assert "rotary-holder" not in "".join(parser.text)
    assert "Rotating sample holder" in "".join(parser.text)
    assert "Sample vessels" in "".join(parser.text)
    assert "4 each" in "".join(parser.text)
    files = {
        "guide.html": page,
        "controller.py": concept_controller_source(),
        "gateway-config.json": concept_gateway_config(data["design"], "example", 3),
        "project.json": json.dumps(data).encode(),
        "machine.stl": b"model",
        "parts/rotary-holder.stl": b"part",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for link in parser.links:
        if not link.startswith("./"):
            continue
        resolved = urlsplit(
            urljoin("http://localhost/api/projects/example/concept/guide.html", link)
        )
        assert resolved.path.startswith("/api/projects/example/concept/")
        assert resolved.query == "revision=3"
        assert (tmp_path / unquote(urlsplit(link).path)).exists()


def test_guide_escapes_text_and_rejects_unsafe_source_links():
    data = project()
    data["design"]["components"][0]["name"] = '<script>alert("x")</script>'
    data["design"]["components"][0]["source"]["url"] = "javascript:alert(1)"
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "javascript:" not in page


def test_guide_explains_real_model_controls_pauses_and_portable_project_difference():
    data = project()
    data["design"]["steps"][0]["stops"] = [0.25, 0.5, 1]
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "Reset view restores the camera" in page
    assert "Play advances the illustrative sequence" in page
    assert "not a measured cycle time" in page
    assert "Includes 3 planned travel pause(s)" in page
    assert "project.json is controller data, a different file" in page
    assert "sensor readings and process outcomes are not simulated" in page


def indexed_project():
    data = project()
    first = data["design"]["steps"][0]
    first.update(
        index_chain=True,
        start_rotation_deg=0,
        rotation_delta_deg=45,
        rotation_reference="from_rest",
        index_station="First position",
    )
    second = deepcopy(first)
    second.update(
        name="Index to second position",
        rotation_deg=90,
        start_rotation_deg=45,
        rotation_delta_deg=45,
        rotation_reference="previous_index",
        index_station="Second position",
    )
    data["design"]["steps"].append(second)
    return data


def test_indexed_guide_and_controller_preserve_consecutive_poses_without_claiming_return(tmp_path):
    data = indexed_project()
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "moves to the next indexed pose and holds that pose" in page
    assert "moves out and returns to its resting position" not in page
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    output = run_sequence(load_project(path))
    first, second = output["events"]
    assert first["preview_motion_mode"] == second["preview_motion_mode"] == "indexed_rotation"
    assert second["preview_rotation_start_deg"] == first["preview_rotation_deg"] == 45
    assert second["preview_rotation_delta_deg"] == 45
    assert second["preview_rotation_deg"] == 90
    assert second["index_station"] == "Second position"


def test_downloaded_controller_rejects_a_broken_index_chain(tmp_path):
    data = indexed_project()
    data["design"]["steps"][0]["index_chain"] = False
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="preceding matching rotary pose"):
        load_project(path)


def test_unsourced_supply_search_is_a_separate_non_evidence_link():
    data = project()
    supply = data["design"]["supplies"][0]
    supply["catalog_search_url"] = "https://www.digikey.com/en/products?keywords=Sample%20vessels"
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "Search US catalog</a>" in page
    assert "(search only; no product or price verified)" in page
    assert supply["catalog_search_url"] in page
    supply["source"] = {"title": "A reviewed candidate", "url": "https://example.com/candidate"}
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "A reviewed candidate</a>" in page
    assert "Search US catalog</a>" not in page
    supply["source"] = None
    supply["catalog_search_url"] = "javascript:alert(1)"
    page = build_concept_guide(data["design"], "example", 3).decode()
    assert "javascript:" not in page
    assert "Search US catalog</a>" not in page


def test_downloaded_controller_runs_without_repository_imports(tmp_path):
    controller = tmp_path / "controller.py"
    controller.write_bytes(concept_controller_source())
    source = tmp_path / "project.json"
    source.write_text(json.dumps(project()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(controller), str(source), "--simulate"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["mode"] == "simulation" and data["revision"] == 3
    assert data["events"][0]["preview_rotation_deg"] == 45
    assert data["events"][0]["preview_rotation_axis"] == "y"
    spec = importlib.util.spec_from_file_location("downloaded_controller", controller)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.run_sequence(module.load_project(source)) == data


@pytest.mark.parametrize(
    "field,value",
    [
        ("translation_mm", [0, float("nan"), 0]),
        ("rotation_deg", float("inf")),
        ("rotation_axis", "bad"),
        ("moving_key", "missing"),
    ],
)
def test_controller_rejects_invalid_sequence_before_execution(tmp_path, field, value):
    data = project()
    data["design"]["steps"][0][field] = value
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(path)


@pytest.fixture
def gateway():
    records = []
    faults = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            records.append((self.path, body))
            payload = {
                key: body[key] for key in ("request_id", "device_id", "project_id", "revision")
            }
            payload.update(
                accepted=True,
                status={"/prepare": "ready", "/execute": "completed", "/stop": "stopped"}[
                    self.path
                ],
            )
            fault = faults.get(self.path, {})
            sleep(fault.get("_delay", 0))
            payload.update({key: value for key, value in fault.items() if not key.startswith("_")})
            self.send_response(fault.get("_http_status", 200))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(fault.get("_raw", json.dumps(payload).encode()))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = json.loads(concept_gateway_config(project()["design"], "example", 3))
    config.update(
        base_url=f"http://127.0.0.1:{server.server_port}",
        device_id="test-device",
        commissioning_reviewed=True,
    )
    config["actions"]["Present sample"] = {"action": "rotate_fixture", "parameters": {"angle": 12}}
    try:
        yield config, records, faults
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_gateway_executes_explicit_mapping_and_stops_over_real_loopback_http(gateway):
    config, records, _ = gateway
    result = run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert result["mode"] == "external_device_adapter"
    assert [path for path, _ in records] == ["/prepare", "/execute", "/stop"]
    command = records[1][1]
    assert command["parameters"] == {"angle": 12}
    assert "translation_mm" not in command and "rotation_deg" not in command
    assert len({body["request_id"] for _, body in records}) == 3


@pytest.mark.parametrize(
    "fault",
    [
        {"accepted": False},
        {"request_id": "old-request"},
        {"device_id": "wrong-device"},
        {"revision": 2},
        {"status": "queued"},
    ],
)
def test_gateway_acknowledgement_fault_stops_without_advancing(gateway, fault):
    config, records, faults = gateway
    faults["/execute"] = fault
    with pytest.raises(ValueError, match="acknowledgement"):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert [path for path, _ in records] == ["/prepare", "/execute", "/stop"]


def test_gateway_failed_prepare_attempts_stop_without_execution(gateway):
    config, records, faults = gateway
    faults["/prepare"] = {"accepted": False}
    with pytest.raises(ValueError):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert [path for path, _ in records] == ["/prepare", "/stop"]


@pytest.mark.parametrize(
    "change",
    [{"commissioning_reviewed": False}, {"revision": 2}, {"actions": {}}, {"device_id": ""}],
)
def test_gateway_configuration_failures_send_no_commands(gateway, change):
    config, records, _ = gateway
    config.update(change)
    with pytest.raises(ValueError):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert records == []


def test_gateway_requires_explicit_arming_and_integration_gate(gateway):
    config, records, _ = gateway
    with pytest.raises(ValueError, match="commission"):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True))
    with pytest.raises(ValueError, match="arm"):
        run_sequence(project(), HttpGatewayAdapter(config), commissioned=True)
    assert records == []


@pytest.mark.parametrize("change", [{"schema_version": True}, {"schema_version": 2}])
def test_gateway_rejects_unsupported_configuration_schema(gateway, change):
    config, records, _ = gateway
    config.update(change)
    with pytest.raises(ValueError, match="schema version"):
        HttpGatewayAdapter(config, armed=True)
    assert records == []


def test_gateway_copies_mapping_before_execution(gateway):
    config, records, _ = gateway
    device = HttpGatewayAdapter(config, armed=True)
    config["actions"]["Present sample"]["parameters"]["angle"] = 999
    run_sequence(project(), device, commissioned=True)
    assert records[1][1]["parameters"] == {"angle": 12}


@pytest.mark.parametrize("stops", [[0.5, 0.5], [1, 0.5], [-0.2], [True], [float("nan")]])
def test_downloaded_controller_rejects_invalid_planned_pauses(tmp_path, stops):
    data = project()
    data["design"]["steps"][0]["stops"] = stops
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Planned pauses"):
        load_project(path)


def test_pause_fractions_remain_preview_data_and_are_not_device_commands(gateway):
    config, records, _ = gateway
    data = project()
    data["design"]["steps"][0]["stops"] = [0.1, 0.6, 1]
    result = run_sequence(data)
    assert result["events"][0]["planned_travel_stops"] == [0.1, 0.6, 1]
    run_sequence(data, HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert "stops" not in records[1][1]


@pytest.mark.parametrize("fault", [{"_http_status": 500}, {"_raw": b"not json"}, {"_delay": 0.15}])
def test_gateway_transport_faults_attempt_stop_and_fail_closed(gateway, fault):
    config, records, faults = gateway
    config["timeout_seconds"] = 0.05
    faults["/execute"] = fault
    with pytest.raises(ValueError, match="command failed"):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert [path for path, _ in records] == ["/prepare", "/execute", "/stop"]


def test_failed_stop_is_reported_instead_of_a_successful_run(gateway):
    config, records, faults = gateway
    faults["/stop"] = {"accepted": False}
    with pytest.raises(ValueError, match="acknowledgement"):
        run_sequence(project(), HttpGatewayAdapter(config, armed=True), commissioned=True)
    assert [path for path, _ in records] == ["/prepare", "/execute", "/stop"]


def test_hardware_cli_rejects_missing_or_incorrect_arming_without_commands(tmp_path, gateway):
    config, records, _ = gateway
    script, data, mapping = (
        tmp_path / name for name in ("controller.py", "project.json", "gateway-config.json")
    )
    script.write_bytes(concept_controller_source())
    data.write_text(json.dumps(project()), encoding="utf-8")
    mapping.write_text(json.dumps(config), encoding="utf-8")
    for options, answer in [
        (["--gateway-config", str(mapping)], ""),
        (["--gateway-config", str(mapping), "--arm-hardware"], "NO\n"),
    ]:
        result = subprocess.run(
            [sys.executable, str(script), str(data), *options],
            cwd=tmp_path,
            input=answer,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
    assert records == []
