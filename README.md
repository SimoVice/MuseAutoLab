# MuseAutoLab

Design modular laboratory workstations through conversation, starting from real open hardware CAD.

Meta models interpret the researcher's request, propose checked layouts and design an optional inspection extension. The application retains the original source CAD and performs deterministic arithmetic, geometry compilation and checks. Coding assistants used to build MuseAutoLab are separate from its runtime Meta inference.

## Current demonstrator

The platform starts with the general laboratory problem. Aliquots and dilutions are the first complete digital engineering path; other tasks support discovery and a downloadable project brief. No concentrations, machine or future-module form are preset on the opening screen.

New workstation designs use the actual [pinned Jubilee STEP](https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP), by Joshua Vasquez / Machine Agency, under CC BY 4.0. The fixed source platform has 809 solids and remains unscaled. Meta proposes a custom liquid-preparation insert, component positions and a bounded digital bed pose. See [source provenance and reproduction](docs/jubilee-cad-asset.md), [source policy](docs/source-grounding.md) and [third-party attribution](THIRD_PARTY_NOTICES.md).

This is a working software prototype for digital proposals, not a tested laboratory machine. Tool attachment, bed connections/travel, source/custom collisions, fabrication, electronics and liquid/thermal performance remain unverified. Science Jubilee controls are not installed. The imported platform has no MuJoCo adapter; legacy XYZ simulation results cannot validate it.

## Try the demo

1. Describe the problem: “I spend a lot of time preparing aliquots and dilutions by hand. I want a flexible setup.”
2. Discuss materials, equipment and constraints. For example: “I have a pipette and microcentrifuge tubes.” There is no need to choose concentrations yet.
3. Ask in the same chat: **“Develop the workstation using the real Jubilee CAD base.”** The progress indicator follows the actual Meta/check request. Its short final fill completes before the accepted 3D design appears.
4. Request a revision in chat, for example **“Lower the existing build plate by another 30 mm.”** The frame remains fixed. The compiler accepts or rejects Meta's bounded proposal; it never silently rescales source parts.
5. When wanted, ask **“Now add an inspection arm and camera to this workstation.”** Mentioning it as a possible future example does not add it. The original platform remains and a separate custom sidecar is proposed. The sweep is kinematic, with no camera coverage, mounting or collision validation.
6. Choose concentrations and final volume with Meta when useful. For example, 10 mg/mL stock, 1 mg/mL target and 1 mL per tube produce a deterministic 100 µL stock + 900 µL diluent plan. These are example inputs, not opening defaults. The calculator uses independent direct dilutions; tube capacity, pipette ranges, mixing and dead volume are unchecked.
7. Review the collapsed **Preparation plan** and confirm. Under **Project details**, inspect sources/components, play an illustrative preview or generate the revision-specific CAD/documents package. Photo inspection appears only after an explicit photo request or an accepted inspection extension, under its own collapsed section; only Analyze photo sends the selected image to Meta.

The left side contains the brief or interactive model, with a compact partial cost/selection summary. Secondary details stay collapsed. All development, cooling and expansion requests use the same chat; there are no permanent arm/camera/cooling request fields. A rejected change preserves the previous project. Quantity-only edits preserve accepted geometry. A new layout clears an earlier inspection extension so it can be designed against the new arrangement.

The fixed source envelope is approximately **483.1 × 612.7 × 564.4 mm** (width × depth × height). A width below 483.1 mm is rejected for this foundation. Meta may propose a **240–300 × 260–300 mm** custom insert and **95–150 mm** downward bed pose. These are bounded digital design choices, not validated travel or mounting limits. The camera/arm/cold sidecars add their own assembly bounds. Arbitrary CAD architectures and source-part editing are not implemented.

## Save and export

**Save project / Open project** use a portable JSON file, capped at 256 KB. Compiler version 3 records the known foundation ID, proposed pose and accepted proposals, then rebuilds canonical geometry on opening without a Meta call. It accepts no arbitrary mesh URLs, CAD paths or executable code. Version 1/2 files preserve inputs and recent conversation, but clear their incompatible old design/extension and ask for a new design in chat. New openings get a fresh runtime ID and retain lineage; old jobs/results are not restored. Browser-local resume is convenience, not cloud storage or a backup.

After confirmation, **Project details → Generate project files** performs real CAD, document and archive work. The package contains the full workstation STEP, custom deck STEP/STL, standalone build123d regeneration source, original source STEP gzip, license/provenance, source bindings, preparation/BOM data, assembly guidance and file hashes. The viewer uses simplified source meshes; the original STEP is the geometric authority. The SVG is a custom-parts layout view and omits source geometry. Simulation records `not_run` for this imported foundation.

Full source CAD exports are substantially larger/slower than the former concept boxes and can take several minutes on first use. Progress advances only after actual stages; it does not show invented percentages. Packages have a 128 MiB ZIP cap and 512 MiB uncompressed cap. Downloads are restricted to the current revision. Known prices are partial dated catalogue observations; unpriced groups remain unknown, and a zero known subtotal displays “Pricing pending”. This is not a complete quotation.

## Reproducible toolchain

| Tool | Pinned version | Purpose |
| --- | --- | --- |
| Python | **3.12.14** | Backend, CAD, physics and Python checks |
| uv | **0.13.6** | Locking and synchronizing the Python environment |
| Node.js | **24.14.1** | Frontend tooling |
| npm | **11.18.0** | Frontend installation from its lockfile |

Git is required to clone the repository. The first installation needs internet access and disk space for CAD dependencies. Environment checks make no model requests and need no API key. Native Windows x64 is the initial verification target; other operating systems are not claimed as tested.

All project Python packages belong in the root **`.venv`**. JavaScript packages belong in **`web/node_modules`**, the Node.js equivalent of a local dependency environment. Neither directory is committed. The setup below requires no global Python or npm package installation.

Version authorities:

- [`.python-version`](.python-version) and [`.node-version`](.node-version) pin interpreters.
- [`pyproject.toml`](pyproject.toml) pins direct Python dependencies; [`uv.lock`](uv.lock) locks the resolved graph and artifact hashes.
- [`requirements.txt`](requirements.txt) is a generated, hashed export including CAD, simulation and development packages. Do not edit it manually.
- [`web/package.json`](web/package.json) pins direct JavaScript packages and npm; [`web/package-lock.json`](web/package-lock.json) locks transitive versions and integrity.
- [`web/.npmrc`](web/.npmrc) enforces matching engines and exact dependency saves. Sources are the public PyPI and npm registries.

## Setup on Windows PowerShell

Install Python 3.12.14 and Node.js 24.14.1 first, with npm 11.18.0. These commands assume the Python launcher `py` is available; otherwise substitute the full path to Python 3.12.14.

```powershell
git clone https://github.com/SimoVice/MuseAutoLab.git
Set-Location MuseAutoLab

py -3.12 -c "import platform; assert platform.python_version() == '3.12.14'"
node --version
npm.cmd --version

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "uv==0.13.6"
.\.venv\Scripts\uv.exe sync --locked --all-extras

Push-Location web
npm.cmd ci
Pop-Location
```

Use `npm.cmd` to avoid PowerShell script-policy issues. Activation is optional: explicit executable paths select the environment without changing the system execution policy. Preserve an existing `.venv`; synchronize it instead of recreating it.

If the installed npm version differs, bootstrap the pinned CLI locally from the repository root, then repeat the frontend commands. This changes only the current shell's search path:

```powershell
npm.cmd install --prefix .local/npm-cli --no-save --package-lock=false --ignore-scripts --no-fund "npm@11.18.0"
$localNpmBin = (Resolve-Path .local/npm-cli/node_modules/.bin).Path
$env:Path = "$localNpmBin;$env:Path"
npm.cmd --version
```

Repeat the search-path assignment in a new shell if using this local CLI. Do not run a global npm upgrade as part of reproduction.

`uv sync --locked --all-extras` includes the backend, CAD, simulation and default development group. For chat-only use, omit `--all-extras`; project-file generation and the full checks below require both CAD and simulation extras. MuJoCo 3.17.0 remains pinned. Camera image processing adds Pillow 13.0.0 as a direct requirement (already present transitively in the CAD environment).

For an unreliable connection, retry with lower concurrency while preserving the lock:

```powershell
$env:UV_CONCURRENT_DOWNLOADS = "3"
$env:UV_HTTP_TIMEOUT = "120"
.\.venv\Scripts\uv.exe sync --locked --all-extras
```

The uv cache stays in ignored `.local/uv-cache`. Setup does not modify a populated `.env`.

### Other operating systems

With the same tool versions, use `python3.12 -m venv .venv`, `.venv/bin/python -m pip install "uv==0.13.6"`, `.venv/bin/uv sync --locked --all-extras`, and `npm ci` inside `web`. Platform-specific dependencies and OpenGL drivers still need verification.

## Verify the installation

Run from the repository root:

```powershell
.\.venv\Scripts\uv.exe lock --check
.\.venv\Scripts\uv.exe pip check
.\.venv\Scripts\python.exe scripts\check_environment.py
.\.venv\Scripts\ruff.exe check scripts

Push-Location web
npm.cmd ls --all
npm.cmd run check:environment
Pop-Location
```

The Python check verifies virtual-environment isolation and direct versions, exports/reopens a small STEP solid, and advances a minimal MuJoCo scene on the CPU. The frontend check compares installed versions with the manifest/lockfile and performs headless React/R3F/Three.js imports. Expected result: `"status": "passed"` from both scripts and successful dependency checks.

These are **environment checks**. They do not launch the product, test browser/WebGL rendering, validate a workstation cycle or verify a laboratory result. The temporary CAD solid is removed automatically. No API key is loaded and no inference is sent.

Verified on 2026-10-27 on Windows x64: the primary environment and a separate clean reconstruction passed the Python/CAD/physics and frontend checks. The reconstruction installed from unchanged lockfiles, also accepted the hashed requirements export, and preserved the original configuration without copying credentials. This verifies the dependency baseline, not full application reproducibility.

## Local Meta configuration

Create the local file without overwriting an existing configuration:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

| Variable | Template value | Purpose |
| --- | --- | --- |
| `MODEL_API_KEY` | Empty | Your own Meta Model API key |
| `META_API_BASE_URL` | `https://api.meta.ai/v1` | Provider endpoint |
| `META_MODEL` | `muse-spark-1.3-contributor` | Default for suitable tests |

The backend reads these variables; environment verification does not use them. Keep credentials server-side and out of browser bundles. Never commit `.env` or put an API key in a `VITE_` variable.

Contributor is the default for suitable tests; use `muse-wonder-1.0` when complexity or an observed quality failure justifies it. Account/model access and billing are external prerequisites. Contributor inputs/responses may be used for training: use shareable or synthetic inputs. Model access is not included in dependency setup.

## Locked dependency groups

| Group | Direct packages |
| --- | --- |
| Backend | FastAPI 0.162.0, Pydantic 2.14.1, HTTPX 0.28.1, python-dotenv 1.2.4, Uvicorn 0.54.0, Pillow 13.0.0 |
| CAD extra | build123d 0.13.0, matplotlib 3.11.2 |
| Simulation extra | MuJoCo 3.17.0 |
| Python development | Playwright 1.64.1, pytest 9.1.1, Ruff 0.17.3, uv 0.13.6 |
| Frontend | React/React DOM 19.3.1, React Three Fiber 9.8.2, Drei 10.7.9, Three.js 0.186.1 |
| Frontend development | Vite 8.3.5, React plugin 6.1.2, TypeScript 7.0.2, Tailwind/Vite plugin 4.3.3; exact type packages in the manifest |

## Run locally

After setup and local `.env` configuration, run in two PowerShell terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location web
npm.cmd run dev
```

Open http://127.0.0.1:5173/. The frontend proxies `/api` to the backend. Meta requests consume the configured allowance; credentials stay in the backend. Active sessions and generated jobs are process-local. Stop each server with Ctrl+C; save the project first if needed.

## Verify the product

```powershell
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_foundation_exports.py
.\.venv\Scripts\python.exe -m pytest tests/test_foundation_exports.py -q
.\.venv\Scripts\ruff.exe check app tests scripts
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe tests/browser_foundation.py
```

The first Python command runs the regular regression suite; the second runs the source-CAD checks, including a full export/reopen and standalone regeneration. That integration test reads expanded source geometry twice and requires substantial time and memory (several GiB on the verified Windows host). Run it separately from quick UI iteration. Both check sets are required for source/export changes.

The current Chrome flow uses explicit offline Meta fixtures, the real API/compiler and real locally served Jubilee meshes. It checks discovery without presets, future examples without action, progress-before-reveal, chat design/revision/expansion, width rejection/rollback, late dilution arithmetic, confirmation, collapsed details, saved/reopened state and mobile layout. Set `MUSEAUTOLAB_BROWSER_SCREENSHOT` to an absolute path for an optional screenshot. It does not establish physical operation.

`browser_smoke.py` and the former design/evolution/source entry points now delegate to the consolidated foundation flow. `browser_platform.py` verifies generic discovery and workflow switching; `browser_vision.py` retains the detailed photo/review/archive/camera-track scenarios, opening the tool through chat. The Python suite retains arithmetic, API, catalogue, legacy physics, vision review, source, export and storage regression checks. Legacy direct `/design` endpoints/compiler fixtures remain for compatibility testing; the current UI's `/messages` development path selects the real source foundation.

The shareable [live Meta example](docs/examples/chat-foundation-live.json) records synthetic future-example, source-layout, bed revision and inspection requests. It distinguishes actual model choices from deterministic checks and preserves rejection evidence. Results are nondeterministic and are integration checks, not model accuracy or laboratory validation.

## Boundaries

Implemented: general discovery, bounded Meta liquid-workstation/inspection proposals, imported source CAD, checked custom geometry, direct-dilution calculations, interactive 3D, optional real-photo analysis with human review, local portable state and revision-specific exports.

Not implemented: arbitrary robot synthesis, fabrication-ready interfaces, calibrated hardware control, pipetting/temperature validation, arm dynamics/collision simulation, full Jubilee physics, live procurement, model selection, dictation or generated instruction illustrations. Photo detections are image regions, not calibrated world coordinates or measured volumes. Historic live checks and screenshots in older documents describe their recorded version; this README and the current source asset documentation describe today's interface.

## Updating requirements deliberately

Normal reproduction uses `sync --locked` and `npm ci`, preserving the selected graph. To change dependencies, update exact direct pins intentionally, regenerate locks, rerun checks and review the diff together:

```powershell
.\.venv\Scripts\uv.exe lock
.\.venv\Scripts\uv.exe sync --locked --all-extras
.\.venv\Scripts\uv.exe export --locked --all-extras --format requirements-txt --output-file requirements.txt

Push-Location web
npm.cmd install --package-lock-only --ignore-scripts
npm.cmd ci
Pop-Location
```

Alternatively, install the hashed export with `.\.venv\Scripts\uv.exe pip sync --require-hashes requirements.txt` in the pinned Python environment. `uv.lock` remains the authority. Regenerate the export whenever the Python graph changes.

Do not use unpinned installs, `npm update`, automatic upgrades or an unrecorded global package to repair a reproduction failure.
