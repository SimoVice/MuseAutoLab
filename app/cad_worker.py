"""CAD execution isolated from the API interpreter and its global interpreter lock.

The parent starts a fixed local script with copied project JSON. No callable,
module path or executable supplied by a project can select what the worker runs.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
MAX_RESULT_FILES = 256
MAX_DIAGNOSTIC_BYTES = 2048
CAD_TIMEOUT_SECONDS = 15 * 60
CAD_QUEUE_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 0.05
_slots = threading.BoundedSemaphore(1)
_children: dict[int, subprocess.Popen] = {}
_children_lock = threading.Lock()


class CadWorkerError(Exception):
    """Bounded worker execution, protocol or lifecycle failure."""


def _safe_name(name: object) -> None:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 256
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", name)
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise CadWorkerError("The CAD worker returned an unsafe artifact name.")


def _validate_files(files: object) -> dict[str, bytes]:
    if not isinstance(files, dict) or not files or len(files) > MAX_RESULT_FILES:
        raise CadWorkerError("The CAD worker returned an invalid artifact mapping.")
    total = 0
    for name, payload in files.items():
        _safe_name(name)
        if not isinstance(payload, (bytes, bytearray)):
            raise CadWorkerError("The CAD worker returned a nonbinary artifact.")
        total += len(payload)
        if total > MAX_RESULT_BYTES:
            raise CadWorkerError("CAD artifacts exceed the 512 MB uncompressed limit.")
    return files


def _write_result(path: Path, files: dict[str, bytes]) -> None:
    _validate_files(files)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name])


def _read_result(path: Path) -> dict[str, bytes]:
    # ZIP overhead is bounded separately from its advertised uncompressed files.
    if not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES + 256 * 1024:
        raise CadWorkerError("The CAD worker result is missing or exceeds its transfer limit.")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_RESULT_FILES:
                raise CadWorkerError("The CAD worker returned an invalid artifact count.")
            names = [entry.filename for entry in entries]
            if len(set(names)) != len(names):
                raise CadWorkerError("The CAD worker returned duplicate artifact names.")
            total = 0
            for entry in entries:
                _safe_name(entry.filename)
                total += entry.file_size
                if (
                    entry.is_dir()
                    or entry.compress_type != zipfile.ZIP_STORED
                    or entry.flag_bits & 1
                    or total > MAX_RESULT_BYTES
                ):
                    raise CadWorkerError("The CAD worker returned an invalid artifact archive.")
            files = {entry.filename: archive.read(entry) for entry in entries}
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise CadWorkerError("The CAD worker result could not be read.") from exc
    return _validate_files(files)


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=2)
    else:
        process.wait()


def _stop_all_children() -> None:
    with _children_lock:
        processes = list(_children.values())
    for process in processes:
        try:
            _stop_process(process)
        except (OSError, subprocess.SubprocessError):
            pass


atexit.register(_stop_all_children)


@asynccontextmanager
async def _cad_slot():
    deadline = time.monotonic() + CAD_QUEUE_TIMEOUT_SECONDS
    while not _slots.acquire(blocking=False):
        if time.monotonic() >= deadline:
            raise CadWorkerError("The CAD worker queue timed out.")
        await asyncio.sleep(POLL_SECONDS)
    try:
        yield
    finally:
        _slots.release()


def _worker_command() -> tuple[str, ...]:
    return sys.executable, "-I", str(Path(__file__).resolve())


def _diagnostic(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_DIAGNOSTIC_BYTES + 1)
        if len(raw) > MAX_DIAGNOSTIC_BYTES:
            return "Worker diagnostic exceeded its limit."
        value = json.loads(raw)
        kind = value.get("error_type")
        return (
            kind
            if isinstance(kind, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", kind)
            else "Worker failed."
        )
    except (OSError, ValueError, TypeError):
        return "Worker failed."


async def execute_cad(project: dict) -> dict[str, bytes]:
    """Run one isolated CAD job, yielding continuously to the API event loop.

    Tests may replace the trusted zero-argument _worker_command hook. Project
    data never controls that command. All such workers use this same process,
    queue, deadline, bounded-result and cleanup path; there is no thread fallback.
    """
    raw = json.dumps(project, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES:
        raise CadWorkerError("The CAD project exceeds the 8 MB worker input limit.")
    async with _cad_slot():
        with TemporaryDirectory(prefix="museautolab-cad-") as directory:
            root = Path(directory)
            source, result, diagnostic = (
                root / "project.json",
                root / "cad.zip",
                root / "error.json",
            )
            await asyncio.to_thread(source.write_bytes, raw)
            process = None
            try:
                options = (
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                process = subprocess.Popen(
                    [*_worker_command(), str(source), str(result), str(diagnostic)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    cwd=Path(__file__).resolve().parents[1],
                    **options,
                )
                with _children_lock:
                    _children[process.pid] = process
                deadline = time.monotonic() + CAD_TIMEOUT_SECONDS
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise CadWorkerError("The CAD worker timed out.")
                    await asyncio.sleep(POLL_SECONDS)
                if process.returncode != 0:
                    raise CadWorkerError("The CAD worker failed: " + _diagnostic(diagnostic))
                return await asyncio.to_thread(_read_result, result)
            finally:
                if process is not None:
                    # Reap on success, failure, timeout and task cancellation. Terminating
                    # OCC happens outside this interpreter, keeping heartbeat reads usable.
                    await asyncio.to_thread(_stop_process, process)
                    with _children_lock:
                        _children.pop(process.pid, None)


def main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        return 2
    source, result, diagnostic = map(Path, arguments)
    try:
        if source.stat().st_size > MAX_INPUT_BYTES:
            raise CadWorkerError("Input limit exceeded.")
        project = json.loads(source.read_bytes())
        if not isinstance(project, dict):
            raise CadWorkerError("A project object is required.")
        # This import is deliberately confined to the child process.
        from app.cad_exports import build_cad_files

        files = build_cad_files(project)
        _write_result(result, files)
        return 0
    except BaseException as exc:
        try:
            diagnostic.write_text(
                json.dumps({"error_type": type(exc).__name__[:80]}), encoding="utf-8"
            )
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main(sys.argv[1:]))
