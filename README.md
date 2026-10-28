# MuseAutoLab

AI-assisted design of modular laboratory workstations, from a researcher's task to an interactive machine proposal and a build package.

## Status

Initialized on **2026-10-27** for the Meta Global AI Developer Hackathon. MuseAutoLab is a general laboratory automation platform: describe a repetitive task, map the process and constraints, and develop a project brief through conversation. Volumes, concentrations and other task-specific parameters are collected only when relevant to the chosen workflow.

The first complete engineering demonstrator is a **liquid preparation workstation** for aliquots and dilutions. Its current adapter provides a selectable parametric 3D concept, smaller-footprint/cold-bay revisions, sourced partial costs, direct-dilution arithmetic, image-based labware inspection, bounded MuJoCo motion/contact simulation and revision-specific CAD/document/simulation downloads. Other workflows support discovery, conceptual discussion and brief export. Mechanical execution, liquid/thermal dynamics, arbitrary machine CAD, robot-arm integration and saved-project import are not implemented. Digital outputs do not establish hardware or laboratory performance.

## Project flow

1. Start with a blank workspace and describe **what you want to automate and why**. There is no default dilution interview or preset machine on the opening screen.
2. Discuss the process, materials, existing equipment and constraints. The app records a general project brief; it does not treat mentioning a microscope, pipette, tube or bench width as a complete machine specification.
3. The model proposes a workflow classification. A generic project stays in concept planning; the currently supported liquid preparation adapter reveals its 3D proposal and component options.
4. Supply task-specific parameters when needed. For liquid preparation, concentration/volume details and the preparation table appear after quantities have actually been supplied. If a request already contains those values, they are used directly.
5. Review the module's parameters, confirm the design and run its available simulations or exports. Changes invalidate older revision-specific outputs.

The interface keeps the design/planning area on the left and conversation on the right. A generic project shows its recorded brief without fabricated geometry, machine prices or dilution questions. The liquid adapter provides the interactive 3D workspace, costs and camera; confirmation exposes its physics and build-file controls. **New project** resets visible state, stops camera capture and focuses a fresh composer without making a model call. Older projects remain process-local; there is no saved-project import.

## Supported workflows

| Workflow | Implemented experience | Current boundary |
| --- | --- | --- |
| Discovery / unclassified | General conversation, goal/process/material/equipment/constraint collection | No preset task, quantities, 3D or parts prices |
| General lab automation, such as transport or label inspection | Concept discussion, a revisioned brief and **Download brief** | No automatic CAD, physical simulation or fabricated machine BOM for that workflow |
| Liquid preparation demonstrator | Parametric XYZ workstation, arithmetic, camera review, partial sourced components, MuJoCo and engineering package | One supported architecture; hardware, thermal and liquid-handling performance remain unvalidated |

The capability registry is [`app/workflows.py`](app/workflows.py). Project state has a generic `brief` (`objective`, `process`, `materials`, `equipment`, `constraints`) and a `workflow` descriptor (`kind`, `label`, `status`, `design_available`, `parameters_started`). The older `summary`/`design`/`plan` fields support the liquid adapter; their retained internal template is not presented as evidence of a generic machine. Non-liquid context sent to the model excludes that template's plan, prices and geometry. Generic updates increment the same project revision, and changing away from liquid preparation clears its quantities/confirmation. Brief equipment is mirrored to the legacy equipment field only for that adapter.

`GET /api/projects/{id}/brief?revision=N` downloads a readable `project-brief.json` containing project ID/revision/status, the generic brief and workflow descriptor. Stale revisions return 409. This is a planning artifact and contains no invented CAD/BOM. Generic projects cannot confirm a hardware design or unlock its simulation/build controls by filling irrelevant dilution fields. The registry is an extension point; additional machinery still needs actual design/simulation/export implementations.

## Demonstrate the platform from a problem statement

Begin with a natural request, without quantities. For the liquid demonstrator, a tested synthetic opening is:

> I spend most of my day pipetting aliquots by hand. I want to automate that repetitive work.

The assistant first asks about the process. In a later message, provide the actual preparation details, for example:

> I have a pipette and microcentrifuge tubes. The stock is 10 mg/ml, the target is 1 mg/ml, and I need 1 ml per tube.

The expected deterministic recipe is 100 µL stock plus 900 µL diluent. Then ask **"Fit the workstation into a 450 mm wide space."** and **"Add refrigerated sample storage at 4 C."** as separate revisions. Confirm before running physics or generating files. Another fully specified demonstration can use targets 1, 0.5 and 0.1 mg/mL to show three preparations; parameters need not be in the opening prompt.

For a different workflow, describe moving capped vials between racks and a microscope to inspect labels. The app asks relevant handling/inspection questions and records a general brief, without requiring stock concentrations or revealing the pipetting rig. Scope and available artifacts are visible when relevant. No seeded user message, automatic example request, timed model reveal or hidden API replay is used.

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

CAD export, bounded MuJoCo motion/contact simulation and photo inspection are implemented. Their scope is described below; installed packages alone do not validate hardware. Remotion and external camera services are not required.

## Run the prototype

After installing dependencies and configuring `.env`, start the backend in one PowerShell terminal from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```powershell
Set-Location web
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. The local frontend proxies `/api` to the backend. Describe your automation problem in the chat and refine the general brief. Task-specific design confirmation is available when a supported workflow has its required parameters. Try a width of `45 cm` and then a width below `400 mm` to see an available layout and an infeasible constraint. Meta API calls consume the selected model's allowance; the key is used only by the backend. Stop both development servers with `Ctrl+C` in their respective terminals.

For this first milestone, the model extracts only information supported by the latest message. A deterministic domain module selects between two illustrative layouts: **600 × 370 mm** and **400 × 470 mm**. Widths below 400 mm are marked infeasible for these two concepts and retain the prior geometry. These numbers and component envelopes are assumptions, not supplier specifications. The check concerns modeled width only; real motion, collision clearance, pipetting, cooling and electrical operation have not been validated. Unknown component cost remains unset.

Project state and chat history live in backend memory for the current process. Restarting the backend, refreshing the page or starting a new project creates a new session; saving and reopening a project are planned but not yet available. Confirmation records user acceptance of the displayed parameters and does not execute a laboratory protocol.

### Direct dilution and operating preview

The deterministic calculator applies **C₁V₁ = C₂V₂**: stock volume is target concentration divided by stock concentration, multiplied by final volume; diluent fills the remainder. For example, a 10 mg/mL stock, 1 mg/mL target and 1 mL final volume yield 100 µL stock and 900 µL diluent. The relationship is described in [Thermo Fisher Scientific's dilution guide](https://assets.thermofisher.com/TFS-Assets/LSG/Application-Notes/cms_043004.pdf).

Supported concentration units are `M`, `mM`, `uM`/`µM`, `nM`, `g/L`, `mg/mL` and `ug/mL`/`µg/mL`; volume units are `mL`, `uL`/`µL` and `nL`. Common equivalent notation such as `mg/ml`, `250ul`, `0,5 ml`, spaces around a slash and both micro symbols is normalized in the summary. Molar prefixes retain their meaning: ambiguous `mm` is not guessed to mean `mM`, and `ML` is not treated as `mL`.

Up to six targets can use separate units (`1 mM, 200 uM`) or a shared trailing unit (`1, 2 and 3 mg/ml`). Decimal comma without a following space means a decimal (`1,5 mg/ml`); comma followed by a space can separate targets (`1, 5 mg/ml`). Ambiguous lists require clarification. Molar and mass concentrations cannot be mixed. Missing, unsupported, negative and impossible values prevent confirmation; zero target is allowed. Each target represents one independent tube prepared directly from the original stock, with no serial dilution or replicates. Brief chat corrections preserve the other parameters; calculated recipes or actionable errors are returned in the conversation as well as the preparation table.

The plan is arithmetic, not a validated protocol. Tube capacity, pipette range, mixing, dead volume, reagent compatibility and hardware performance are not checked. The preview illustrates visits to tips, stock/diluent, sample rack and waste for nonzero transfers; it is not a physical simulation, collision check or hardware control. Sample and source positions are schematic. Review all parameters and obtain appropriate laboratory and hardware validation before practical use.

### Refrigerated bay and component choices

Ask for refrigerated storage, for example `Add refrigerated storage at 4 C`, or use the Cold storage controls and apply the settings. The proposed bay extends the custom deck in depth while preserving the other component sizes. Its target is requested/proposed, not measured. The supported target entry range is 2–20 °C; the Opentrons alternative cannot be selected for a target below its stated 4 °C minimum. The DIY proposal has no verified cooling performance. Samples are transferred manually to this attached bay; the pipetting animation does not implement a gripper or transfer into cold storage.

The Component catalogue compares real supplier offers, quantities, availability notes and integration tradeoffs. Changing a selected option updates the same project revision, subtotal and relevant cooling envelope, and returns a confirmed project to draft. Choices persist when the width changes or the bay is disabled and re-enabled. Unknown groups remain unpriced. A selected starting price is marked `from`; all displayed totals are partial and exclude unspecified parts, shipping, taxes, import duties, assembly and validation.

Prices are a dated USD catalogue snapshot checked on **2026-10-27**, not a live supplier feed or a delivered quotation. The data is in `app/data/components-2026-10-27.json`; [component sources](docs/component-sources.md) records primary links, price scope, assumptions and refresh instructions. The configuration endpoint is `POST /api/projects/{id}/configuration` with optional `cooling_enabled`, `cooling_target_c` and `selections` fields. It validates changes under the same project lock as chat. It makes no purchases or supplier requests.

### Physical motion and contact simulation

After confirming the design, choose **Run physics** in the Physical simulation panel. **Normal run** evaluates the supported preparation cycle; **Blocked-path test** inserts a clearly identified synthetic obstacle above the first tip station. The run is computed on the backend CPU using the pinned MuJoCo 3.17.0 engine. No API key, model call, GPU service or hardware is needed for this step.

The model represents one rigid carriage/pipette head on three limited prismatic axes, with position servos, gravity and collision constraints. Fixed component envelopes come from the same project revision as CAD. Assumed tube/tip cylinder proxies match the viewer's rack positions. Each nonzero stock or diluent transfer visits tips, source, sample and waste; aspirate/dispense/eject actions are logical holds **above** their station tops. There is no physical insertion, fluid dynamics or detached-tip handling.

The following are **model assumptions**, not measured hardware or supplier motor capabilities:

| Parameter | Model value |
| --- | --- |
| Moving masses | Carriage 0.45 kg, pipette 0.15 kg, tip 0.001 kg |
| Position control | kp 5000 N/m, kv 100 Ns/m; guide damping 5 Ns/m; gravity uncompensated |
| Actuator force limits | Engine X/Y/Z: 15 / 15 / 20 N |
| Integration | 0.002 s, implicitfast; recorded output at 20 Hz plus terminal state |
| Approach and cruise | Tip 5 mm above station/proxy top; cruise 15 mm above non-frame obstacles |
| Numerical acceptance | Maximum following error 5 mm; stop on unexpected contact above 0.05 N |
| Runtime bounds | At most 300 simulated seconds, 6500 output frames, six targets |

Travel is inferred from the deck and planning height. The crossbar/carriage contact pair represents an ideal guide interface and is explicitly excluded; head/post, tool/frame, head/deck and head/container contacts remain enabled. Mount clearance, real rails/transmissions, cable paths, backlash, rigidity and actual motor sizing are not verified. Four tip positions are logical stations; consumable capacity and replacement are not validated.

The result reports actual integrated states, actuator/contact forces, following error, completed waypoints, engine version, input/source hashes, assumptions and checks. **passed** means the encoded checks passed under those assumptions. **blocked** means a measured simulated contact interrupted the run; later waypoints are not completed. Engine/model errors fail explicitly. No replacement animation or substitute engine is reported as MuJoCo success. See the official [MuJoCo XML reference](https://mujoco.readthedocs.io/en/stable/XMLreference.html#sensor-contact) for the actuator/contact definitions; compatibility was exercised against installed version 3.17.0.

Play/Pause/Reset, the time slider and explicit 1x/2x/4x controls replay calculated states in the 3D viewer. Linear interpolation between recorded samples is for display only. The separate **Play preview** control returns to the illustrative animation. Changing the design clears replay state and blocks old simulation results/downloads until the current revision is confirmed and run again.

The API is `POST /api/projects/{id}/simulations` with `{"scenario":"nominal"}` or `{"scenario":"blocked_path"}`, then `GET /api/projects/{id}/simulations/{job}` and the returned result URL. File attachments use `/api/projects/{id}/simulations/{job}/files/{name}`. Confirmed snapshots are immutable, progress comes from integrated steps, duplicate requests reuse results and computation runs outside the API event loop. Results/jobs remain process-local and are lost on restart.

### Downloadable project files and assembly guide

Confirm the design, then select **Generate project files**. Four completed stages track actual work: CAD generation, document generation, nominal physical simulation and ZIP packaging. Choose **Download project ZIP** or download an individual file. The assembly guide's Previous/Next controls select the corresponding component in the 3D view. A failed or blocked model result remains labelled as such; an available ZIP does not establish physical feasibility.

| Package file | Contents |
| --- | --- |
| `project.json`, `manifest.json` | Confirmed input snapshot, schema version, revision, input hash and per-file SHA-256 hashes |
| `cad/workstation.step`, `cad/workstation.svg` | Labelled concept envelopes and top view derived from the same component positions/sizes |
| `cad/deck.step`, `cad/deck.stl` | Custom deck solid blank; no mounting holes or fabrication-ready interfaces |
| `cad/deck-model.py`, `cad/geometry-report.json` | Editable parametric source, library/source provenance, measured dimensions, validity and open interfaces |
| `assembly-guide.html`, `assembly.json` | Standalone print-friendly illustrated assembly sequence, stable component IDs and design gates |
| `bill-of-materials.csv`, `preparation.csv` | Selected alternatives with quantities, source prices/dates and per-target volumes; unknown prices stay blank |
| `automation/preview.py` | Standard-library-only logical preparation trace; no hardware commands |
| `simulation/model.xml`, `simulation/result.json`, `simulation/trajectory.csv` | Nominal MuJoCo scene, recorded states/checks and flat trajectory for this revision |
| `simulation/engine.py`, `simulation/run.py`, `simulation/README.md` | Standalone source and rerun instructions using the locked MuJoCo environment |
| `extension-plan.json`, `extensions.md`, `README.md` | Proposed camera/arm interfaces, package usage and limitations |

Extract the ZIP and open `assembly-guide.html` in a browser. Open STEP files in a STEP-compatible CAD viewer. Geometry uses millimetres: application `(x,y,z)` with y up maps to CAD `(x,z,y)` with Z up. Decorative tubes/vents in the viewer are not engineered parts. The planning height is a workspace envelope and can exceed the measured CAD height.

Run the extracted logical preview with `python automation/preview.py` (Python 3, no extra packages). To regenerate CAD with exactly **build123d 0.13.0**, use this repository's locked `.venv` and run its interpreter against the extracted `cad/deck-model.py`. It writes STEP/STL files beside the script; geometry is derived from the editable `COMPONENTS_MM` array. Keep the original downloaded package for provenance: modifying generated source requires new checks and hashes.

To rerun the packaged simulation, use that same locked interpreter against the extracted `simulation/run.py`. It loads the packaged `project.json` and scenario and writes `simulation/replay-result.json`. The original result/model/source stay intact. A repeat run on the tested Windows environment reproduced the same numerical metrics; cross-platform bitwise identity is not guaranteed.

Each job uses an immutable copy of one confirmed revision. Edits invalidate confirmation and block old downloads with HTTP 409, including jobs that finish after the edit. Generate again after reconfirming; duplicate requests for the same active or ready revision reuse that job. Failed jobs expose an error and Retry action, never partial downloads. Up to three jobs per project are retained in process memory, with a 50 MB package limit. Restarting the backend loses sessions/jobs. `project.json` preserves the input for inspection; uploading/reopening a saved project in the app is not implemented.

The API exposes `POST /api/projects/{id}/exports`, `GET /api/projects/{id}/exports/{job}`, and the returned download URL; individual attachments use `/api/projects/{id}/exports/{job}/files/{name}`. Generation runs locally without additional Meta requests or supplier calls. The exported snapshot makes inputs and selections inspectable; identical binary output across machines or regeneration is not guaranteed (for example, STEP headers can contain timestamps).

The assembly sequence is a concept design guide. Rail/transmission details, pipette actuation, labware fits, mounting holes, power, wiring and calibration remain unresolved. Process, material and tolerances have not been selected; the deck STL is **not ready for fabrication**. The browser camera/photo inspection is implemented separately from mechanical integration. A camera on an upper-frame mount and robot arm on an external sidecar are future proposals: their load, reach, field of view, power and collision clearances require hardware-specific design. No installed camera/arm or reserved compatible physical space is claimed.

## Test the application

From the repository root, run the backend/domain tests and code checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests scripts
Push-Location web
npm.cmd run build
Pop-Location
```

To exercise the browser flow with a **stubbed AI provider** and the real local frontend/backend domain, install Chrome or point to a local Chromium-compatible executable, then run:

```powershell
$env:PLAYWRIGHT_CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
.\.venv\Scripts\python.exe tests\browser_smoke.py
```

The browser test uses temporary localhost ports, synthetic messages and a deterministic test-only model response. It does not use an API key or contact Meta. Set `MUSEAUTOLAB_BROWSER_SCREENSHOT` to save normal/blocked screenshots. The suite checks the empty opening, a greeting with no design changes, a typed first request, fresh-project reset, calculation/recovery, width revisions, confirmation, component selection, illustrative playback, real MuJoCo normal/obstacle cases, replay controls and mode switching. It downloads two real CAD/simulation packages, verifies revisions/hashes/source provenance/selected cooling geometry, navigates assembly steps and rejects stale downloads/results. Logs use temporary files so Windows pipe buffers cannot block the test server. CAD tests reopen STEP and measure envelopes; physics tests use actual MuJoCo, while job/API boundary tests stub engine functions to isolate concurrency/failure behavior. The exported runtime is rerun and compared in the locked environment. These checks concern the encoded model, not built hardware. Testing with the real Meta API requires account access and consumes tokens.

## Labware photo check

1. Start the backend and frontend above and open the workspace. Photo inspection is available on a draft or confirmed liquid preparation project after that adapter has been selected.
2. In **Labware photo check**, choose **Upload labware photo**, **Load example photo**, or **Use camera**. Camera access requires a secure browser context (localhost is supported), browser permission and a camera. **Capture** freezes a frame and stops the video tracks; **Stop camera**, project changes and leaving the panel also stop them. No microphone or continuous inference is used.
3. Click **Analyze photo** explicitly. Preview/capture/example loading alone makes no Meta request. This sends the normalized photo to the configured Meta model, Contributor by default; Contributor inputs/responses may be used for training. Use photos you can share. No project chat, simulated object list or design geometry is sent with the photo.
4. Select a numbered image region or its card. Review the category, label, normalized bounding box and, for a tip rack, visible contents. **Accept** or **Reject**, then **Save decisions**; corrections can be saved together. **Add missed object** creates a human-authored region. **Accept visible regions** is an explicit bulk human decision, not an automatic confidence filter. Click **Review scene** after all objects have decisions; an empty detection list can also be acknowledged.
5. An optional **Manual 3D association** links tubes to source/sample racks and tips to the tip rack. **Show in 3D** highlights that concept component. This is a human label, not image-to-world calibration; no machine movement or physical registration is inferred.
6. **Download inspection zip** downloads six files: the exact analyzed metadata-free `image.jpg`, a self-contained `annotated.svg` with numbered regions and a legend, current `inspection.json` including the original model output, timestamped `review-history.json`, usage/limits `README.md` and a SHA-256 `manifest.json`. Photos are included only in this explicit inspection download, not the main CAD package.

Uploads accept JPEG/PNG up to 16 MiB in the browser and are resized to at most 1600 px on the longest side. The API accepts only base64 JPEG/PNG data URLs, at most 4 MiB decoded and 16 million source pixels, with both sides at least 32 px. It validates content/type, applies EXIF orientation, removes metadata, flattens transparency on white and creates a canonical JPEG. The returned image is exactly the input sent to Meta. External image URLs and local file paths are not accepted.

The model returns at most 24 regions: tubes, individual pipette tips, tip racks or uncertain labware. Boxes use **0–1000 image coordinates**, origin top left, x right, y down; pixel centers can be obtained by multiplying normalized coordinates by width/height divided by 1000. There are no calibrated metric coordinates, volume/concentration estimates, exact inventory counts or hardware interlocks. Model scores are uncalibrated. Uncertainty, score below the demonstration threshold of 0.85, poor image quality or partial coverage flags an object for review. Even stronger observations require a human decision before final scene review. A rack alone does not prove tips are present; its visible contents must support that observation. **Not observed** does not establish absence.

Jobs, canonical images and reviews are process-local, retaining at most three inspections per project; restart loses them. Duplicate requests for the same canonical image and project revision reuse the active/ready job instead of making another model call. One job per project and at most two model calls globally run concurrently; failures remain visible and retry requires user action. Every read, review and download checks the project revision. Corrections increment an observation version, with stale review/download versions rejected. Changing the design or confirming it clears the panel and requires a new inspection. No new image is acquired or sent automatically.

The bundled example is a laboratory photograph by **Gannu03**, under **CC BY-SA 4.0**, with [source, license and derivative details](web/public/examples/README.md). It is not MuseAutoLab hardware. API request format follows Meta's [image understanding](https://dev.meta.ai/docs/image-understanding) and [vision input cookbook](https://dev.meta.ai/docs/cookbook/vision-input), consulted 2026-10-28. Scores/coordinates are model outputs, not measurements.

For repeatable browser verification with **stubbed chat/vision and a synthetic canvas camera stream**, run:

```powershell
.\.venv\Scripts\python.exe tests\browser_vision.py
```

The real image preparation, jobs, human review and archive generation run in that test. It exercises photo upload/example loading, no automatic analysis, corrections and 3D association, original/audit preservation and hashes, stale versions/revisions, zero-object acknowledgement and video-track shutdown. It uses real browser MediaStream tracks backed by a synthetic canvas feed, not the user's webcam; it never contacts Meta. The built-in headless Chrome fake device ended before its first frame on the tested Windows machine, so the repeatable camera test supplies the source at getUserMedia. Actual webcam/driver compatibility remains to be checked on the target device. Set `MUSEAUTOLAB_VISION_SCREENSHOT` for an optional screenshot. The main `browser_smoke.py` remains the regression test for design/CAD/physics.

A bounded live Contributor check on 2026-10-28 returned 24 approximate regions with partial coverage for the crowded example photo, and zero regions for a synthetic white negative control. The first photo response failed validation with a 2400-token output cap; a single retry with a 6000-token cap succeeded. The discarded response does not establish the exact failure cause. These limited checks establish integration, not detection precision/recall, camera calibration or operation in a laboratory. Results are not deterministic; more varied labeled photos and hardware calibration are future work.

To verify generic discovery, relevant equipment/space context, revisioned brief downloads, deferred liquid parameters and switching workflows, run:

```powershell
.\.venv\Scripts\python.exe tests\browser_platform.py
```

This uses the real API/domain/frontend with deterministic model fixtures and makes no Meta call. Model/source tests also ensure that a general inspection workflow does not receive a hidden liquid preparation plan or accept unrelated liquid parameters. The original CAD/physics and camera browser suites remain regression checks for the liquid adapter. Real model responses are probabilistic and can fail strict source validation; failed turns leave the project unchanged and require a user retry.

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

## Optional development-assistant skills

Skills guide coding assistants. **They are not required to install or run MuseAutoLab**, and are not dependencies of the Meta-powered product. Their files stay outside Git in the assistant's user-level skill directory.

Selected additions:

| Source | Pinned revision | Selected directories |
| --- | --- | --- |
| [EnzeD/r3f-skills](https://github.com/EnzeD/r3f-skills) | `4a11805f097396fb0b893172efd1e359e8051f92` | `skills/r3f-fundamentals`, `skills/r3f-interaction`, `skills/r3f-animation` |
| [K-Dense scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | `a92663a0214b3b9fa1ba6b958284ffd919c00a0c` | `skills/lab-hardware-cad` |
| [Google DeepMind MuJoCo](https://github.com/google-deepmind/mujoco/tree/3.17.0/doc/skills) | `3.17.0` | `doc/skills/python`, `doc/skills/spec_editing`, `doc/skills/rendering` |
| [Remotion skills](https://github.com/remotion-dev/skills) | `30d4553ecd46fbc5212fd0ff006ae43af522158b` | `skills/remotion-best-practices`, including nested references |
| [Vercel agent-skills](https://github.com/vercel-labs/agent-skills) | `6ec269328bc400712ee225a173a14b6b29128df7` | `skills/web-design-guidelines` |

For Codex, ask its built-in skill installer to install those repository paths at the exact revision into the user profile. Copy complete directories, not just `SKILL.md`. Other coding assistants may load the same files; verify their loading rules separately.

Local Codex adaptations: install the MuJoCo directories as `mujoco-python`, `mujoco-spec-editing` and `mujoco-rendering`; adjust sibling links to those names and resolve other documentation links against the pinned upstream source. Move CAD's top-level `compatibility` field to `metadata.upstream-compatibility` and Remotion's top-level `version` to `metadata.upstream-version` if required by the installed validator. Preserve their values/instructions and record original/adapted hashes locally.

Run Python CAD/simulation helpers with the root `.venv`; adapt POSIX example paths on Windows. A separate ignored virtual environment can hold agent-only validation tools (PyYAML 6.0.3), outside the product graph. Existing frontend-design and webapp-testing guidance is also useful; project-specific agent files remain local. A fresh clone can reproduce the product environment without any skills.

## Reproduction boundaries

Dependency versions and environment checks are reproducible. A lockfile does not make model responses, live supplier prices, browser/GPU behavior or physical outcomes deterministic. Implemented scenarios must retain inputs, seeds, model settings, component sources/dates, design revision and artifact provenance with their product fixtures or results.

Use one versioned design for the viewer, CAD, component list, human assembly instructions and automation exports. Distinguish operating animation, geometric checks and physical simulation. Refrigeration geometry alone does not verify temperature control.

## Repository contents

| Path | Purpose |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | Python requirements and reproducible installation |
| `web/package.json`, `web/package-lock.json`, `web/.npmrc` | Frontend requirements and installation policy |
| `scripts/check_environment.py` | Offline Python/CAD/physics environment check |
| `web/scripts/check-environment.mjs` | Offline frontend dependency check |
| `app/` | Local API, Meta integration and versioned concept model |
| `web/src/` | Interactive workstation view and chat interface |
| `tests/` | Domain/API unit tests and local browser smoke test |
| `.env.example` | Public configuration template with empty credentials |
| `CONTRIBUTIONS.md` | Implemented contributions and their scope |
| `docs/software-acknowledgements.md` | Development-tool reference and its scope |

Source, required assets, reproducible checks and submission documentation belong in Git. Secrets, environments, `node_modules`, agent files, local skill provenance and caches are excluded. See [Contributions](CONTRIBUTIONS.md) for what this repository implements.
