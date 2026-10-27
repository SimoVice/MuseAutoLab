"""Verify isolated dependencies, a CAD round-trip and a minimal physics step.

This does not test the workstation, a dispensing protocol or real hardware.
No environment file is loaded and no network or model request is made.
"""

import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    expected_python = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Run this check with the project's virtual environment")
    if platform.python_version() != expected_python:
        raise RuntimeError(f"Expected Python {expected_python}; got {platform.python_version()}")
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(local / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(local / "cache"))
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    specs = list(project["dependencies"])
    for group in project["optional-dependencies"].values():
        specs.extend(group)
    specs.extend(manifest["dependency-groups"]["dev"])
    versions = {}
    for spec in specs:
        name, expected = spec.split("==", 1)
        installed = importlib.metadata.version(name)
        if installed != expected:
            raise RuntimeError(f"{name}: expected {expected}, got {installed}")
        versions[name] = installed

    import fastapi
    import httpx
    import matplotlib
    import mujoco
    import pydantic
    from build123d import Box, export_step, import_step

    # Reopen an exported solid: import success alone does not exercise the CAD kernel.
    with tempfile.TemporaryDirectory(prefix="environment-cad-", dir=local) as directory:
        solid = Box(10, 20, 30)
        target = Path(directory) / "environment-coupon.step"
        export_step(solid, target)
        reopened = import_step(target)
        if not reopened.is_valid or abs(reopened.volume - 6000.0) > 1e-6:
            raise RuntimeError("CAD export/import failed")

    # CPU physics only: no renderer, hardware assumptions or remote requests.
    model = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody><body name="probe" pos="0 0 1">'
        '<freejoint/><geom type="sphere" size="0.01" mass="0.01"/>'
        '</body></worldbody></mujoco>'
    )
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    for _ in range(10):
        mujoco.mj_step(model, data)
    mujoco.mj_forward(model, data)
    if not 0 < float(data.body("probe").xpos[2]) < 1:
        raise RuntimeError("Minimal physics step failed")

    assert fastapi.FastAPI and httpx.Client and pydantic.BaseModel and matplotlib.__version__
    print(json.dumps({
        "status": "passed",
        "python": platform.python_version(),
        "isolated": True,
        "packages": versions,
        "checks": ["exact direct versions", "CAD STEP round-trip", "CPU physics step"],
        "scope": "environment only; no application, WebGL, workstation or hardware validation",
    }, indent=2))


if __name__ == "__main__":
    main()
