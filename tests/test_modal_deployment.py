"""Offline deployment context checks; never load a real Modal client."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def load_entry(monkeypatch):
    modal = MagicMock()
    modal.is_local.return_value = False
    monkeypatch.setitem(__import__("sys").modules, "modal", modal)
    spec = importlib.util.spec_from_file_location(
        "deploy_modal_test", Path(__file__).resolve().parents[1] / "scripts/deploy_modal.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, modal


def test_deployment_limits_and_existing_resources(monkeypatch):
    _, modal = load_entry(monkeypatch)
    knobs = modal.App.return_value.function.call_args.kwargs
    assert knobs["max_containers"] == 1
    assert knobs["min_containers"] == knobs["buffer_containers"] == 0
    assert knobs["memory"] == 4096 and knobs["cpu"] == 1
    assert "gpu" not in knobs
    assert knobs["env"]["MUSEAUTOLAB_HOSTED"] == "1"
    assert "create_if_missing" not in modal.Volume.from_name.call_args.kwargs
    modal.Image.from_dockerfile.assert_not_called()
    assert modal.App.call_args.kwargs["include_source"] is False
    assert modal.asgi_app.call_args.kwargs["label"] == "museautolab"
    required = modal.Secret.from_name.call_args.kwargs["required_keys"]
    assert "MODEL_API_KEY" in required and "META_API_KEY" not in required


def test_allowlisted_context_uses_current_contents(monkeypatch, tmp_path):
    entry, _ = load_entry(monkeypatch)
    files = {
        "Dockerfile": "FROM python:3.12",
        "app/api.py": "current source",
        "app/new_auth.py": "new source",
        "app/assets/public.glb": "public",
        "app/assets/private.glb": "private",
        ".env": "secret",
        ".local/private.md": "private",
        "web/src/main.ts": "public",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    tracked = "\0".join(
        name for name in files if name not in {"app/new_auth.py", "app/assets/private.glb"}
    )
    monkeypatch.setattr(entry.subprocess, "check_output", lambda *args, **kwargs: tracked.encode())
    context = entry.stage_context(tmp_path, tmp_path / "context")
    try:
        assert (context / "app/api.py").read_text() == "current source"
        assert not (context / "app/new_auth.py").exists()
        assert (context / "app/assets/public.glb").is_file()
        assert not (context / "app/assets/private.glb").exists()
        assert not (context / ".env").exists()
        assert not (context / ".local").exists()
        assert not entry.allowed_context_path("../private")
    finally:
        entry.shutil.rmtree(context)


def test_missing_dockerfile_fails_before_cloud(monkeypatch, tmp_path):
    entry, _ = load_entry(monkeypatch)
    monkeypatch.setattr(entry.subprocess, "check_output", lambda *args, **kwargs: b"")
    with pytest.raises(RuntimeError, match="Dockerfile"):
        entry.stage_context(tmp_path, tmp_path / "context")
