# MuseAutoLab

AI-assisted design and simulated assembly of modular laboratory workstations.

MuseAutoLab explores a workflow in which Meta models propose a laboratory configuration, a physics simulator checks the plan, and the model revises it using measured failures. The initial scope is a small set of supported modules and a synthetic, inert handling task.

## Status

Repository initialized on 2026-10-27 for the Meta Global AI Developer Hackathon. This revision contains project documentation and configuration templates. A runnable application, assembly controller, and simulation results are not included yet.

## Intended workflow

1. Describe a task, available modules, and workspace constraints.
2. Generate a structured configuration and assembly plan using a Meta model.
3. Validate the configuration and execute the supported actions in MuJoCo.
4. Return measured errors to the model and verify the revised plan.
5. Display the resulting scene and an explicit verification report.

The planned implementation uses a Python backend with FastAPI, Pydantic, and MuJoCo, together with a React and TypeScript interface using React Three Fiber. The simulator will remain the authoritative source of physical state; the browser will visualize its output.

## Local configuration

Create a local `.env` from the committed template on a fresh checkout:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

Set `MODEL_API_KEY` in `.env` using your own Meta Model API credentials. The template leaves the key empty. Confirm that `META_MODEL` is available to your account before making a request.

| Variable | Purpose |
| --- | --- |
| `MODEL_API_KEY` | Local Meta Model API key |
| `META_API_BASE_URL` | Meta Model API endpoint |
| `META_MODEL` | Model identifier for the planned backend |

These variables define the configuration template. Application startup and configuration loading will be documented when implemented.

## Verification scope

Simulation can assess the geometry, dynamics, and constraints represented in a model. It does not establish real-world assembly reliability, liquid-handling accuracy, biological process quality, or hardware safety. Any idealized gripper, connector, or control assumption must be identified alongside the results.

## Repository contents

Source code, required assets, reproducible checks, and submission documentation belong in this repository. Local secrets, agent instructions, scratch work, generated caches, and uncurated outputs are excluded by `.gitignore`.

See [Contributions](CONTRIBUTIONS.md) for the scope of work recorded in this repository.
