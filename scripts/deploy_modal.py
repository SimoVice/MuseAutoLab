"""Reviewed Modal entry point; importing this file never deploys or creates cloud resources.

Requires the separately installed, pinned Modal SDK. Before deployment, enforce a
zero out-of-pocket Workspace spend limit in Modal's dashboard. Credits alone do
not impose this limit. Provision the named Secret and v2 Volume separately.
Stop the old app before replacing it: the project store requires one writer.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import modal

APP_NAME = "museautolab"
SECRET_NAME = "museautolab-host"
VOLUME_NAME = "museautolab-projects"
ROOT = Path(__file__).resolve().parents[1]
EXACT_FILES = {
    "Dockerfile",
    ".dockerignore",
    "pyproject.toml",
    "uv.lock",
    "THIRD_PARTY_NOTICES.md",
    "web/package.json",
    "web/package-lock.json",
    "web/.npmrc",
    "web/index.html",
    "web/tsconfig.json",
    "web/vite.config.ts",
    "scripts/deploy_modal.py",
}


def allowed_context_path(relative: str) -> bool:
    """Only product build inputs; tracked status is checked separately."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "__pycache__" in path.parts:
        return False
    if any(part.startswith(".") for part in path.parts) and relative not in EXACT_FILES:
        return False
    return (
        relative in EXACT_FILES
        or (relative.startswith("app/") and path.suffix == ".py")
        or relative.startswith(("app/data/", "app/assets/", "web/src/", "web/public/"))
    )


def stage_context(root: Path, destination: Path) -> Path:
    """Copy current allowlisted tracked files, from the Git index only.

    Never send the checkout itself as a Docker context. Credentials, local records,
    generated exports and untracked assets cannot enter this temporary context.
    """
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    )
    candidates = {name for name in tracked if name and allowed_context_path(name)}
    for name in sorted(candidates):
        source = root / name
        if source.is_symlink() or any(
            parent.is_symlink() for parent in source.parents if parent != root
        ):
            raise RuntimeError("Symlinks are not permitted in the deployment context.")
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if not (destination / "Dockerfile").is_file():
        raise RuntimeError("The reviewed product Dockerfile is required.")
    return destination


# Disable implicit package upload: only the staged build inputs are transmitted.
app = modal.App(APP_NAME, include_source=False)
image = None
if modal.is_local():
    _staging = tempfile.TemporaryDirectory(prefix="museautolab-modal-context-")
    context = stage_context(ROOT, Path(_staging.name))
    image = modal.Image.from_dockerfile(context / "Dockerfile", context_dir=context)

volume = modal.Volume.from_name(VOLUME_NAME)  # Existing Volume only; never auto-create.
server_secrets = modal.Secret.from_name(
    SECRET_NAME,
    required_keys=[
        "MUSEAUTOLAB_AUTH_ORIGIN",
        "MUSEAUTOLAB_AUTH_USERNAME",
        "MUSEAUTOLAB_AUTH_PASSWORD_HASH",
        "MUSEAUTOLAB_AUTH_SIGNING_SECRET",
        "MODEL_API_KEY",
    ],
)


@app.function(
    image=image,
    cpu=1,
    memory=4096,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
    scaledown_window=60,
    timeout=600,
    secrets=[server_secrets],
    volumes={"/data": volume},
    env={
        "MUSEAUTOLAB_HOSTED": "1",
        "MUSEAUTOLAB_LIVE_PLATFORM_PRICES": "1",
        "MUSEAUTOLAB_LIBRARY_DIRECTORY": "/data/projects",
        "MUSEAUTOLAB_MODAL_VOLUME_NAME": VOLUME_NAME,
    },
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app(label="museautolab")
def web():
    from app.hosted import create_app

    return create_app()
