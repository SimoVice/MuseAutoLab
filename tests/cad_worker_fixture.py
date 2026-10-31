"""Trusted child fixture for isolation/lifecycle tests; never a product geometry claim."""

import argparse
import ctypes
import json
import os
import time
import zipfile
from pathlib import Path


def hold_gil(seconds):
    if os.name == "nt":
        ctypes.PyDLL("kernel32.dll").Sleep(int(seconds * 1000))
    else:
        ctypes.PyDLL(None).usleep(int(seconds * 1_000_000))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--marker")
    parser.add_argument("source")
    parser.add_argument("result")
    parser.add_argument("diagnostic")
    args = parser.parse_args()
    source, result, diagnostic = map(Path, (args.source, args.result, args.diagnostic))
    project = json.loads(source.read_bytes())
    if args.marker:
        with Path(args.marker).open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "phase": "start",
                        "pid": os.getpid(),
                        "time": time.monotonic(),
                        "directory": str(source.parent),
                    }
                )
                + "\n"
            )
    if args.mode in ("gil", "hang"):
        hold_gil(1.25 if args.mode == "gil" else 30)
    if args.mode == "error":
        diagnostic.write_text(
            json.dumps({"error_type": "SyntheticWorkerFailure"}), encoding="utf-8"
        )
        return 1
    if args.mode == "bad-zip":
        result.write_bytes(b"not a CAD result archive")
        return 0
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        name = "../escape.step" if args.mode == "unsafe" else "cad/workstation.step"
        archive.writestr(name, b"offline child CAD fixture: " + project.get("id", "test").encode())
        if args.mode == "duplicate":
            archive.writestr(name, b"duplicate")
    if args.marker:
        with Path(args.marker).open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"phase": "end", "pid": os.getpid(), "time": time.monotonic()}) + "\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
