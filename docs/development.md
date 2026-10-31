# Development

[Back to MuseAutoLab](../README.md) · [Installation and configuration](getting-started.md)

The backend lives in `app/`, the React/Three.js interface in `web/`, and regression and browser checks in `tests/`. Run commands below from the repository root, using the pinned environment.

## Verify the product

```powershell
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_foundation_exports.py
.\.venv\Scripts\python.exe -m pytest tests/test_foundation_exports.py -q
.\.venv\Scripts\ruff.exe check app tests scripts
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe tests/browser_foundation.py
.\.venv\Scripts\python.exe tests/browser_engineering.py
.\.venv\Scripts\python.exe tests/browser_platform.py
.\.venv\Scripts\python.exe tests/browser_vision.py
.\.venv\Scripts\python.exe tests/browser_scene_focus.py
.\.venv\Scripts\python.exe tests/browser_project_files.py
.\.venv\Scripts\python.exe tests/browser_multimodal.py
.\.venv\Scripts\python.exe tests/browser_scene_accessibility.py
.\.venv\Scripts\python.exe tests/browser_resources.py
.\.venv\Scripts\python.exe tests/browser_labware.py
.\.venv\Scripts\python.exe tests/browser_microplate.py
.\.venv\Scripts\python.exe tests/browser_presentation.py
```

The first Python command runs the regular regression suite; the second runs the source-CAD checks, including a full export/reopen and standalone regeneration. That integration test reads expanded source geometry twice and requires substantial time and memory (several GiB on the verified Windows host). Run it separately from quick UI iteration. Both check sets are required for source/export changes.

The current Chrome flow uses explicit offline Meta fixtures, the real API/compiler and real locally served Jubilee meshes. It checks discovery without presets, future examples without action, progress-before-reveal, chat design/revision/expansion, width rejection/rollback, late dilution arithmetic, confirmation, collapsed details, saved/reopened state and mobile layout. Set `MUSEAUTOLAB_BROWSER_SCREENSHOT` to an absolute path for an optional screenshot. It does not establish physical operation.

`browser_engineering.py` checks comparison, no CAD before selection, both actual adapter routes, the exact per-tube prompt, unchanged layout, setup guidance and save/reopen. `browser_smoke.py` and the former design/evolution/source entry points delegate to the foundation flow. `browser_platform.py` checks generic discovery/workflow switching; `browser_vision.py` retains photo/review/archive/camera-track scenarios. Legacy direct `/design` endpoints/compiler fixtures remain for compatibility testing; current `/messages` development requires an explicit platform choice.

`browser_project_files.py` uses explicit offline export responses to check both platform labels, reconnect after an interrupted status request without another export POST, explicit sandboxed guide reading and project reset. It does not generate heavy CAD or call Meta.

`browser_resources.py` checks pricing coverage, failed refresh recovery, expiry and
focus/visibility rereads without automatic supplier calls, candidate/source labels,
instruction navigation, real document download, revision/report guards, saved-project
reopening and mobile layout. Catalog responses are controlled fixtures; the separate
[live supplier and Meta record](examples/procurement-instructions-verification.json)
contains actual observations.

`browser_microplate.py` checks a tube-to-plate message, occupied well addresses,
volume conflicts, rejected requests, rack restoration, portable recovery and
mobile layout. Its model responses are explicit offline fixtures. The separate
[microplate evaluation record](examples/microplate-verification.json) retains
the actual Meta calls, failures, corrections and CAD/API responsiveness measurements.

The shareable [live Meta example](examples/chat-foundation-live.json) records synthetic future-example, source-layout, bed revision and inspection requests. It distinguishes actual model choices from deterministic checks and preserves rejection evidence. Results are nondeterministic and are integration checks, not model accuracy or laboratory validation.

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
