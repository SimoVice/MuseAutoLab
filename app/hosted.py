"""Serve the built workspace and the private API at one HTTPS origin."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import project_library
from app.model_client import DEFAULT_BASE_URL


def create_app() -> FastAPI:
    if os.environ.get("MUSEAUTOLAB_HOSTED") != "1":
        raise RuntimeError("The hosted entry point requires MUSEAUTOLAB_HOSTED=1.")
    if not os.environ.get("MODEL_API_KEY", "").strip():
        raise RuntimeError("Configure the Meta key in the hosting provider's secret store.")
    if os.environ.get("META_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/") != DEFAULT_BASE_URL:
        raise RuntimeError("Hosted sessions require the official Meta API endpoint.")
    if not project_library.configured():
        raise RuntimeError("Configure persistent storage before starting a hosted workspace.")
    storage = Path(project_library.database_path() or project_library.library_directory())
    if not storage.is_absolute():
        raise RuntimeError("Hosted storage requires an absolute path on a persistent mount.")

    public = Path(__file__).resolve().parents[1] / "web" / "dist"
    if not (public / "index.html").is_file() or storage.resolve().is_relative_to(public):
        raise RuntimeError("The compiled website and private project storage must be separate.")

    # Import only after checking the environment. The API installs its auth boundary at import.
    from app.api import app as api
    from app.host_auth import HostAuth

    if not any(m.cls is HostAuth for m in api.user_middleware):
        raise RuntimeError("The hosted API must start in a fresh process with authentication.")
    server = FastAPI(openapi_url=None)

    @server.get("/healthz")
    async def health():
        return {"status": "ok"}

    # Keep every API route behind its middleware. A static mount only serves the built bundle.
    if not any(route.name == "workspace" for route in api.routes):
        api.mount("/", StaticFiles(directory=public, html=True), name="workspace")
    server.mount("/", api)
    return server
