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

## 2026-10-28: Bounded MuJoCo motion/contact simulation

Added an ideal rigid XYZ head with position actuators, force limits, gravity, project-derived collision envelopes and assumed consumable proxies. Recorded MuJoCo states drive a separate 3D replay with pause/reset/seek and explicit playback speeds. A diagnostic obstacle produces a measured simulated contact and an early stop. Results retain project/revision/scenario, input/source hashes, engine version, numerical checks and explicit assumptions. The crossbar/carriage guide contact is omitted; head/post, tool/frame, head/deck and head/container collision checks remain enabled.

Added asynchronous simulation jobs and revision-gated report/model downloads. Project packages now have four real generation stages and 22 files, including the nominal MJCF model, result, trajectory, standalone runtime and rerun script. Source and snapshot hashes bind the exported inputs to the computation. Results/jobs are process-local.

Contributor on OpenCode Go produced initial physics helpers, job/API/export integration and the UI, then reviewed edge cases and generated HTTP/browser tests. Codex revised the runtime to require real MuJoCo integration with explicit failures, corrected coordinate/planning/replay and concurrency issues, and integrated the tests. An expanded user authorization allowed unpublished/future product source in later Contributor reviews. One provider connection failure received one successful retry; no credentials or private parent records were included.

Verification: 137 Python tests, lint, frontend build, real browser normal/obstacle replay and two project downloads, selected cooling geometry, stale-result rejection, six-target bounds and standalone exported reruns. The final two-target wide/compact/cold fixtures completed 68 waypoints with no unexpected contact and at most 3.079 mm following error under the assumed model. The diagnostic obstacle stopped the wide fixture at 2.632 simulated seconds with a 2.283 N contact. These are model results, not measurements of built hardware or liquid handling. No new dependencies or direct Meta API calls were required.


## 2026-10-28: Image-based labware inspection with human review

Added explicit still-photo analysis using the Meta multimodal API, local camera preview/capture, canonical metadata-free image handling, selectable normalized image regions, manual correction/addition and rack association, scene acknowledgement and a separate six-file inspection report. Original observations and timestamped human decisions are preserved. Results are bound to project and observation versions; duplicate images reuse jobs, with bounded inference and no continuous camera uploads. Main CAD packages retain their existing scope.

Four scoped OpenCode Go tasks explicitly used `opencode-go/muse-spark-1.3-contributor` with low effort for the vision client/tests, jobs/API/tests, UI and browser verification. Codex reviewed/integrated their outputs, corrected image caps before decoding, strict review values and mapping persistence, versioned downloads, presence semantics, embedded SVG presentation, video attachment/cleanup and stale asynchronous state. All inputs were authorized product source; credentials and private parent records were excluded.

Pillow 13.0.0 is now a direct pinned backend requirement; Python lock/hash files are updated. The bundled example photo is third-party CC BY-SA 4.0 material, attributed separately; it is not an original hackathon asset or MuseAutoLab hardware. Live checks used Contributor on the public example and a synthetic blank image, not private laboratory images. The crowded-photo result was approximate and partial; recognition accuracy and metric registration remain unvalidated.


Final verification: 168 Python tests passed, including image/EXIF/caps/strict-schema boundaries and atomic human-review/version checks; lint, frontend build and locked-environment checks passed. The camera browser flow used a synthetic canvas-backed MediaStream (the Windows headless Chrome fake device ended immediately), with real capture, track shutdown, API jobs, reviews and ZIP downloads. The baseline CAD/physics browser flow also passed. Visual review used a replay of the recorded live Meta response and the actual downloaded annotated SVG. Two successful direct Meta checks consumed a reported 2,762 prompt and 2,825 completion tokens; the earlier invalid attempt's usage was unavailable. No accuracy benchmark or physical camera/hardware result is claimed.


## 2026-10-28: Start the demonstration from an empty workspace

Changed the opening to an empty design area and chat, with no preset 3D machine, price, component list or task details. A supported requirement recorded by the real API reveals the existing parametric concept; an unstructured greeting does not. Added New project to clear the visible workspace, stop camera capture and focus a fresh composer. Removed the seeded example button. The underlying supported machine architecture and backend initialization are unchanged.

OpenCode Go Contributor low effort produced the bounded UI revision; Codex reviewed it, adjusted first-load focus/offline messaging/header, updated browser checks and integrated documentation. Both browser suites passed: typed-request reveal, existing CAD/MuJoCo/export flow and camera reset/track cleanup. Lint and frontend build passed. One synthetic real Meta Contributor request from the blank screen produced three deterministic dilution recipes after extraction; usage reported 2,093 prompt and 470 completion tokens. This is a supported flow check, not arbitrary CAD generation or laboratory validation.


## 2026-10-28: General laboratory automation discovery and workflow-specific engineering

Generalized the product entry and project model: objective, process, materials, equipment and constraints are recorded in a versioned brief, with explicit workflow capabilities. Generic inspection/transport projects support conceptual discussion and a revision-specific JSON brief, without a preset pipetting rig or dilution interview. The liquid preparation demonstrator reveals its existing 3D/cost/camera functions when selected; concentration/volume controls wait for actual quantities. Changing workflow invalidates confirmation and clears scoped preparation values. Other machinery is not represented as implemented CAD or simulation.

Three bounded OpenCode Go tasks explicitly used Muse Spark Contributor low effort for domain/workflow state, model/API integration and UI. Codex removed partial-workspace fallbacks, ensured derived capabilities reach the frontend, preserved source grounding and transactional updates, corrected workflow confirmation/version guards and added cross-workflow browser/parameter-isolation checks. No dependency was added. Generic model context excludes the liquid template's geometry, plan and catalogue. The user can provide detailed quantities later or all at once; completed supported requests invite review rather than repeat the interview.


Validation: 192 Python tests and the general-platform, existing CAD/physics and camera browser suites passed, along with lint/build and unchanged lock/package consistency checks. Real Contributor UI checks covered general vial transport/label inspection and aliquoting discovery without quantities. One later parameter turn failed strict validation with unchanged project state; its raw body/usage was unavailable. A bounded direct diagnostic retry passed, and a separate fully specified live UI request produced three correct recipes and reset. Four successful direct calls reported 9,691 prompt and 3,018 completion tokens; the failed attempt is additional. These observations are not a general workflow benchmark, arbitrary CAD result or hardware validation.

## 2026-10-28: Shared detailed concept geometry

Replaced the liquid demonstrator's box-only CAD and separate viewer details with one serialized primitive model. Frame sections, carriage/holder, tapered pipette, open racks with actual through-holes, waste, controller and optional cold enclosure now derive from the same revision in the interactive view, animated/replayed head and STEP. The sample insert follows one to six targets without shrinking its outer envelope. Stable component IDs, layout dimensions, component choices and the 22-file package are preserved. Appearance colors are illustrative; the commercial cooler detail is conceptual, not supplier CAD.

The CAD report includes exact primitive manifests, measured bounds and separate component/solid counts. Volumes explicitly sum potentially overlapping solids, not net material or mass. The editable exported model includes its own builders; source and provenance are frozen at import for reproducible process behavior. Physics validates detail bounds but retains conservative component-envelope contacts and separate consumable proxies. The assembly guide and package README explain this distinction.

Three scoped native GPT-6.1 Terra xhigh tasks implemented shared geometry/CAD, the viewer and physics validation under the user's specific 3D model preference. Codex reviewed/integrated the output, requested fixes for rotated CAD primitives, disconnected frame sections and a cold-lid gap, strengthened package checks and updated documentation. No dependencies, direct Meta requests or OpenCode Go tasks were added for this phase.

Verification: 206 Python tests, Ruff, frontend build, a browser flow with real CAD/MuJoCo downloads and exact primitive-manifest checks, five visual browser configurations and direct mesh selection passed. Four six-target cases (wide, compact, DIY cold and commercial cold) exported/reopened valid CAD and completed the nominal physical model with zero unexpected contact and at most 3.079 mm following error. CAD checks measure through-holes, orientation and frame/enclosure connectivity, and rerun exported source. Multiview STEP images and browser views were inspected. These are digital checks on the assumed model; labware fits, materials/process, sealing, transmissions, mounting, thermal control and hardware operation remain unverified. The robotic arm remains future work.
