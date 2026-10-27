# MuseAutoLab

AI-assisted design of modular laboratory workstations, from a researcher's task to an interactive machine proposal and a build package.

## Status

Initialized on **2026-10-27** for the Meta Global AI Developer Hackathon. The prototype collects task parameters through Meta, displays a selectable 3D workstation concept, adapts its layout to a requested width and calculates direct-dilution volumes for review. It supports a proposed cold-storage bay and source-backed component comparisons with partial pricing. After confirmation it can play an illustrative operating animation. Physical simulation, temperature control, file exports and persistent projects are not implemented yet.

The selected demonstrator is a dilution-and-aliquot workstation with pipette, tube and tip handling. It is intended to design the mechanical/electronic architecture and guide a person through assembly. Digital checks do not establish liquid-handling accuracy or hardware performance.

## Intended experience

1. Describe stock/target concentrations, final volumes, equipment, space and budget.
2. Review missing requirements and confirm the parameter summary.
3. Inspect a rotatable, selectable 3D proposal and revise it through conversation.
4. Request a smaller footprint or refrigerated storage; update the design and component data together.
5. Preview the supported operating cycle and inspect the checks actually performed.
6. Generate component options, printable parts, human assembly guidance and supported automation code.

The planned light interface reserves roughly 60% of the design view for the 3D model, with estimated cost below and chat on the right. After confirmation, the model compacts upward to reveal actual generation progress and project files. Camera-based tube/tip presence checks are optional.

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

`uv sync --locked --all-extras` includes the backend, CAD, simulation and default development group. For backend-only use, omit `--all-extras`; the full check below intentionally requires all extras.

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
| Backend | FastAPI 0.162.0, Pydantic 2.14.1, HTTPX 0.28.1, python-dotenv 1.2.4, Uvicorn 0.54.0 |
| CAD extra | build123d 0.13.0, matplotlib 3.11.2 |
| Simulation extra | MuJoCo 3.17.0 |
| Python development | Playwright 1.64.1, pytest 9.1.1, Ruff 0.17.3, uv 0.13.6 |
| Frontend | React/React DOM 19.3.1, React Three Fiber 9.8.2, Drei 10.7.9, Three.js 0.186.1 |
| Frontend development | Vite 8.3.5, React plugin 6.1.2, TypeScript 7.0.2, Tailwind/Vite plugin 4.3.3; exact type packages in the manifest |

The CAD and simulation dependencies are prepared for later work; their presence does not mean workstation CAD export or physics simulation exists. Remotion, camera tooling and additional services are not product dependencies in this revision.

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

Open `http://127.0.0.1:5173`. The local frontend proxies `/api` to the backend. Enter a task in the chat, review the extracted parameters, and confirm them when complete. Try a width of `45 cm` and then a width below `400 mm` to see an available layout and an infeasible constraint. Meta API calls consume the selected model's allowance; the key is used only by the backend. Stop both development servers with `Ctrl+C` in their respective terminals.

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

The browser test uses temporary localhost ports, synthetic messages and a deterministic test-only model response. It does not use an API key or contact Meta. Set `MUSEAUTOLAB_BROWSER_SCREENSHOT` to save an optional screenshot. The suite checks calculated example volumes, an impossible concentration and recovery, width revisions, confirmation, component selection and that the schematic canvas changes while playback runs. It does not establish physical feasibility. Testing with the real API requires valid account access and consumes tokens.

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

Source, required assets, reproducible checks and submission documentation belong in Git. Secrets, environments, `node_modules`, agent files, local skill provenance and caches are excluded. See [Contributions](CONTRIBUTIONS.md) for what this repository implements.
