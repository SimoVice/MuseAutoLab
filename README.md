<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="MuseAutoLab — custom laboratory automation. One project connects design, components and build guidance.">
</p>

# MuseAutoLab

**Custom laboratory automation, designed around your needs.**

MuseAutoLab is a platform for designing custom laboratory automation setups around
a researcher's tasks, equipment and constraints. Describe the process you want to
automate, explore suitable approaches and develop the project through conversation.
The goal is to connect the equipment design, component choices, assembly guidance
and software needed to put the setup to work.

The setup can evolve as the research changes. The platform keeps the project brief,
selected sources, design revisions and supported deliverables connected, so a change
can be reviewed in the context of the whole project.

[**Start a new project →**](#try-it-yourself) · [How the platform works](docs/platform.md) · [Explore the documentation](docs/README.md)

## From a research task to an automation setup

You do not need to choose a machine or specify a recipe before you begin.
Start with the work you want to improve.

1. **Describe the process.** Explain the task, materials, existing equipment,
   working space and practical constraints. MuseAutoLab helps develop the brief
   and asks for task-specific details when they matter.
2. **Explore a suitable approach.** Compare available foundations and tradeoffs,
   including building around an open design or using existing equipment. Review
   the proposal and choose an approach before detailed design begins.
3. **Develop the connected project.** Refine the design in chat and inspect its
   supported 3D layout, component choices, cost information, assembly instructions
   and software guidance. Review and confirm changes before generating a package.
4. **Evolve the setup.** Save the project, revisit a design choice or adapt the
   setup to another task. Supported changes carry their sources and revision
   history into the related outputs.

## One project, modular engineering support

The conversation captures the researcher's needs. Meta models help explore options
and propose changes; application checks determine which changes can become an
engineering design. Supported adapters connect a selected machine foundation,
components and task to the appropriate geometry, calculations, guides and exports.
Accepted revisions keep those outputs tied to the same project.

This modular architecture separates the platform's purpose from any single
laboratory workflow. **Liquid handling is the first deeply implemented use case.**
Other tasks can currently develop a discovery brief; arbitrary machine CAD,
components and control are not yet implemented. New engineering paths need their
own adapters and checks.

[Platform architecture and scope](docs/platform.md) · [Source-grounding policy](docs/source-grounding.md)

## Try it yourself

**Start with your own task.** The application runs locally; there is no hosted demo
to sign into.

1. Follow the [Windows setup](docs/getting-started.md#setup-on-windows-powershell)
   and [start the two local servers](docs/getting-started.md#run-locally).
2. Add your own [server-side Meta configuration](docs/getting-started.md#local-meta-configuration).
3. Choose **New project** and describe the laboratory process you want to automate,
   the equipment you have and the constraints that matter. The available
   engineering depth depends on the task and supported adapters.

Spark/Wonder selection, editable Muse Voice dictation and optional Muse Image
presentation artwork are available through the configured account. Model-backed
actions use your allowance; generated artwork does not replace engineering CAD.

For a look without configuring a Meta key, download the
[recorded liquid-handling project](docs/examples/software-protocol-project.json)
and choose **Open project**. It uses synthetic laboratory inputs. Inspect the
layout and guides, expand the 3D view and select **Selected part only**.

## Current engineering depth: liquid handling

![Actual MuseAutoLab 3D view: Jubilee source machine with custom deck modules and an inspection-arm concept](docs/images/presentation-workstation.png)

*An implemented example: Jubilee source CAD with custom deck modules and an
inspection-arm concept. Physical fit and operation remain unverified.*

The current engineering path develops aliquoting and direct-dilution setups.
It supports a sourced choice between Jubilee and an Opentrons OT-2 schematic,
bounded layout revisions, dimension-driven holders, reviewed labware alternatives,
US supplier listings in USD and separately labelled planning estimates. Supported
exports include revision-specific design files, instructions and logical protocol
previews. [Operating previews](docs/operating-previews.md) animate the supported
Jubilee preparation sequence and inspection concept directly in the 3D workspace,
with playback tied to the current recipe and selected labware.

Neither route has a physics or hardware-control adapter. Fit, mounting, tool
access, calibration, liquid handling, thermal performance and complete build cost
remain unverified. A logical protocol preview does not command a robot, and no
measured laboratory time saving is claimed.

[Explore the liquid-handling use case](docs/use-cases/liquid-handling.md) · [Recorded walkthrough](docs/presentation-flow.md) · [Verification record](docs/verification.md)

<a id="setup-on-windows-powershell"></a>

## Run locally

The pinned toolchain is **Python 3.12.14 · uv 0.13.6 · Node.js 24.14.1 · npm 11.18.0**.
Windows x64 is the verified target. With those tools installed, a fresh checkout starts with:

```powershell
git clone https://github.com/SimoVice/MuseAutoLab.git
Set-Location MuseAutoLab
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "uv==0.13.6"
.\.venv\Scripts\uv.exe sync --locked --all-extras
npm.cmd --prefix web ci
```

Then run each server in its own terminal from the repository root:

**Terminal 1 — backend API at `127.0.0.1:8000`.** Keep this terminal running.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend website at `127.0.0.1:5173`.** Keep this terminal running too.

```powershell
$env:MUSEAUTOLAB_API_TARGET = "http://127.0.0.1:8000"
npm.cmd --prefix web run dev -- --port 5173 --strictPort
```

**Open the website in your browser: [http://127.0.0.1:5173/](http://127.0.0.1:5173/).**
Port 8000 serves the API; port 5173 serves the interface and forwards `/api` requests
to port 8000. If either port is occupied, follow the
[port troubleshooting guide](docs/getting-started.md#if-a-port-is-already-in-use).

Keep an existing `.venv` and synchronize
it rather than recreating it. The [complete setup guide](docs/getting-started.md)
includes version checks, a local npm fallback, safe `.env` setup and installation
verification. For chat-only use, the CAD/simulation extras are optional.

## Go deeper

- [Platform](docs/platform.md) — product workflow, modular architecture and supported scope.
- [Documentation map](docs/README.md) — walkthroughs and engineering references.
- [Liquid handling](docs/use-cases/liquid-handling.md) — the first implemented engineering path and its examples.
- [Development](docs/development.md) — regression checks, browser flows and locked dependency updates.
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [software acknowledgements](docs/software-acknowledgements.md) — sources and their terms.

Software checks, real model calls and supplier observations are recorded separately
in the [verification record](docs/verification.md). Older videos and screenshots
retain the scope of the version they show.

Jubilee is by Joshua Vasquez / Machine Agency, used under CC BY 4.0. Official
Opentrons software references retain their own attribution and terms. See the
notices before reusing source assets.
