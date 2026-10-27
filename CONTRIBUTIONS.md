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

## 2026-10-27: Natural quantity notation and conversational corrections

Fixed rejection of equivalent inputs such as `mg/ml`, `250ul`, decimal commas and shared-unit target lists. Quantity normalization preserves numerical meaning and meaningful prefix distinctions, while source checks accept equivalent formatting without accepting invented values. The summary uses canonical units; chat now returns calculated recipes or actionable correction messages and can explain the recorded plan. Follow-up corrections preserve other parameters, and unanswered optional questions are not repeatedly prompted.

Added normalization, source-integrity and API regression tests and exercised informal notation through the browser. Synthetic live Contributor checks covered a three-target request, a volume correction and explanations of the current plan.

## 2026-10-27: Refrigerated bay and sourced component comparison

Added a configurable cold-storage proposal through chat and controls, with an attached 3D bay, explicit temperature target, manual sample transfer and depth changes derived from the selected envelope. Added a dated catalogue of primary supplier prices, selectable alternatives, quantities, pros/cons, availability notes, source links and a partial subtotal. Component choices, cooling geometry, cost and confirmation state share the project revision.

Added catalogue, cooling-domain, API and source-notation regression checks. Browser checks exercise cooling activation, cheaper driver selection, a commercial cooling alternative and its starting price, unsupported-temperature rejection and choice preservation through disable/re-enable. A synthetic live Meta/browser flow exercised the compact layout plus cooling addition. Implementation tasks used Muse Spark Contributor through OpenCode Go; output was reviewed, simplified and integrated locally.

The catalogue is a reproducible snapshot, not a live feed or a complete build quotation. Five groups remain unpriced. Cooling performance, full hardware compatibility, sample transfer automation and physical feasibility remain unverified.

## 2026-10-27: Revision-specific downloads and illustrated assembly sequence

Added asynchronous local project-file generation with real CAD/document/archive stages, revision-gated ZIP and individual downloads, per-file hashes, immutable confirmed snapshots and retryable failures. The interface compacts the viewer after confirmation, presents the generated files and selects components while stepping through assembly guidance.

The package includes labelled STEP concept envelopes, a custom deck blank in STEP/STL, editable build123d source, a geometry report, standalone illustrated HTML, assembly JSON, selected-component and preparation CSV files, runnable logical preview code and proposed camera/arm extension documentation. All derive from the same revision and selections. Edits block older downloads, including work that completes after an edit.

Four implementation tasks explicitly used Muse Spark 1.3 Contributor through OpenCode Go with low effort and public baseline inputs. Their outputs were reviewed and corrected before integration. Verification covered 121 Python tests, lint, frontend build, STEP export/import and measurements, standalone script execution, guide rendering and a real browser flow downloading two packages and checking hashes/stale revisions. The AI provider was stubbed during that browser check.

CAD represents concept envelopes; deck mounting holes, mechanisms, labware fits, wiring, material/process choices and hardware operation remain unresolved. Assembly steps describe a proposed sequence with design gates. The robot arm and camera are future extensions, with no hardware or compatible reserved space demonstrated. Saved-project import is not implemented.
