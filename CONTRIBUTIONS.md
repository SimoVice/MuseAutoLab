# Contributions

Git history records changes made to MuseAutoLab during development. This file distinguishes implemented work from the intended project direction.

## 2026-10-27: Repository initialization

This revision adds:

- An English project README with the intended workflow and current implementation status.
- A public environment template with an empty API key.
- Git exclusions for secrets, local agent files, temporary work, and generated output.
- Text line-ending rules for cross-platform development.

No application functionality, simulated assembly result, benchmark, or hardware validation is claimed by this initialization. Local `.env` files and agent instructions are not part of the submitted repository.

## 2026-10-27: Reproducible development environment

This revision adds exact interpreter/tool versions, direct dependency pins, Python/npm lockfiles, a generated hashed requirements export, local environment checks, and setup/update instructions. The README reflects the clarified dilution/aliquot demonstrator and human-guided assembly scope. The environment template defaults to Contributor for suitable tests.

The checks exercise dependency installation, a small CAD export/import and a minimal CPU physics step. They do not implement or validate the application or the workstation. External development skills are documented by source revision, while their files and local adaptations remain outside the product repository.

## 2026-10-27: First interactive design prototype

Added a FastAPI backend with server-side Meta Contributor integration, bounded structured extraction and validation of updates against the user's message. Added a versioned, deterministic concept layout that changes with a supported workspace-width constraint, reports infeasible constraints and requires complete parameters for confirmation.

Added the React/Three.js workspace with a rotatable, selectable 3D concept, conversation, parameter summary and unknown cost state. Added domain/API tests and a reproducible browser smoke test with a stubbed model; a separate synthetic live test exercised the real Meta endpoint. Playwright was added as a pinned development dependency.

The supported layouts are illustrative assumptions. No physical mechanism, pipetting calculation, cooling system, sourcing, export package or persistent project is validated or implemented in this revision.

## 2026-10-27: Direct dilution and illustrative operation

Added deterministic direct-dilution calculations with explicit concentration and volume units, missing and impossible input handling, and confirmation gated on a valid plan. Added a preparation table and a controllable 3D operating animation showing schematic visits for stock and diluent transfers. Added arithmetic and browser checks, including invalid-input recovery and a rendered-canvas change during playback. Implementation was assisted by Muse Spark 1.3 Contributor through OpenCode Go and reviewed and integrated locally.

The calculator assumes one tube per target and does not model serial dilution or check tube capacity, pipette limits, mixing, dead volume or laboratory feasibility. The animation is illustrative and does not simulate physics, liquid flow or device control.
