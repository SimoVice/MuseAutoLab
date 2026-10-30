# MuseAutoLab — submission draft

Prepared 2026-10-30. Adaptable entry text, not a submitted entry or a transcription
of the event's actual form. Verify field names, length limits and declarations in
the entrant's account before pasting. Bracketed items remain unresolved.

## Project and access

- **Project:** MuseAutoLab
- **Repository:** [https://github.com/SimoVice/MuseAutoLab](https://github.com/SimoVice/MuseAutoLab)
- **Entrant / team:** [TO CONFIRM: actual entrant identity and credited team members]
- **Track:** Indie Developer Track — proposed; selection and eligibility unverified.
- **Theme:** Push the Frontier — proposed; actual form choices unverified.
- **Video:** [Three-minute captioned MP4](https://raw.githubusercontent.com/SimoVice/MuseAutoLab/main/docs/video/museautolab-demo.mp4) — 180 s, 1080p, English captions, no narration. Confirm the form accepts this host.
- **Hosted product:** None currently provided. Local review instructions are below.
- **Application revision shown and tested:** [`81ef2ebf1581536505cbe8f71ac4b6d704614980`](https://github.com/SimoVice/MuseAutoLab/commit/81ef2ebf1581536505cbe8f71ac4b6d704614980). Subsequent delivery commits add documentation, evidence and media; record the actual submitted commit in the entry receipt.

## Short pitch

MuseAutoLab turns a researcher's laboratory task into a sourced, editable automation
proposal, with interactive 3D, consistent engineering files and modular expansion.

## Problem and product

For a researcher preparing aliquots and dilutions by hand, choosing an automation
route involves equipment, space, assembly effort and unresolved engineering details.
MuseAutoLab makes those decisions visible in one conversational project.

The researcher describes the task and available equipment, compares a buildable
open-hardware route with an assembled instrument, and explicitly chooses before
design begins. They can revise a supported layout, save and reopen it, then request
an inspection-arm/camera concept on the same Jubilee project. Concentrations and
volumes enter when relevant; deterministic arithmetic produces the preparation plan.
Confirmation unlocks revision-specific CAD, source records and an illustrated guide.

The current result is a working digital prototype. Dilution/aliquot preparation is
the complete engineering demonstrator; other laboratory tasks support discovery
and project-brief planning.

## How Meta is used

The demonstrated runtime uses `muse-spark-1.3-contributor` to interpret needs,
propose reviewed platform options and reasons, and supply bounded layout or
inspection-extension proposals.
The application validates structured outputs, checks supported constraints and keeps
the last accepted project when a change fails. Meta does not invent the source
machine CAD or execute arbitrary generated code. Separately requested photo analysis
uses a supplied image and human review; the virtual camera is not a real photograph.

## Architecture and original contribution

A FastAPI/Pydantic backend owns versioned project state and server-side Meta access.
Deterministic geometry and arithmetic feed a React/TypeScript/Three.js viewer,
portable JSON and build123d CAD/document exports from the same accepted revision.
The catalogue currently supports original pinned Jubilee STEP and an OT-2 schematic
grounded in published dimensions and pinned official deck data.

Our contribution is the implemented needs-to-choice workflow, bounded proposal
validation, source-aware revisions, rollback, project continuity, expansion and
coherent outputs. Jubilee's original design remains attributed to Joshua Vasquez /
Machine Agency; the OT-2 route does not contain manufacturer machine CAD.
[Contribution history](../CONTRIBUTIONS.md) and [third-party notices](../THIRD_PARTY_NOTICES.md)
separate new integration from upstream work. Development used Codex review/integration,
GPT-6.1 Sol, GPT-6.1 Terra and OpenCode Go Contributor assistance; these development
tools are distinct from runtime Meta inference.

## Evidence and review access

The [dated verification record](verification.md) reports 415 regular Python tests,
8 separate source-CAD tests, six offline browser flows and a clean locked Windows
reconstruction. The video project's actual package contains 25 files and was generated
in 137.757 s; its STEP reopened as valid with 863 solids across 19 components. The
[October 30 fresh-run appendix](examples/delivery-third-rehearsal.json) now records
a third complete varied Meta journey plus an impossible-width rejection preserving
the confirmed project. Three fresh paths completed across the dated sessions; the
first preceded final parser hardening and was replayed offline on the final checks,
while the second and third used the final backend live. Earlier failures remain
recorded; recovered runs and replay are not additional fresh successes or a
reliability benchmark. The [video project](examples/demo-video-project.json) is
provided separately so its quantities and exports can retain their own lineage.

Reviewers can follow the [locked setup](../README.md#setup-on-windows-powershell),
start the [local servers](../README.md#run-locally), and open
[`examples/demo-video-project.json`](examples/demo-video-project.json) without an API key. This
rebuilds a recorded real-Meta project locally and supports actual local exports.
Fresh conversation requires the reviewer's own configured Meta access. See the
[reviewer guide](demo-guide.md) for the exact distinction between recorded review,
offline fixtures and live inference. No hosted demo is implied.

## Current limits and next step

Neither current platform has physics or hardware control. Cooling, inspection
sweeps and liquid-handling geometry are digital concepts; mounting, collision
clearance, camera coverage and laboratory performance remain unverified. Supplier
prices are partial dated observations. No measured time saving, physical operation
or universal machine generation is claimed. The next engineering step is physical
interface, calibration and liquid-handling validation after the digital proof.

## Form completion placeholders

[TO VERIFY: actual required fields, length limits, video/access requirements,
entrant/track eligibility and declarations. Map this draft to the verified form;
do not infer its requirements from these headings.]

## Public event information checked 2026-10-30

The [official Meta event page](https://dev.meta.ai/events/global-hackathon) and
[Cerebral Valley submission route](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit)
publicly state a November 4, 2026, 21:00 Eastern Time deadline (November 5, 03:00 CET)
and describe the Indie track. The unauthenticated submission route exposed the
landing/sign-in page, not the actual form. These sources do not verify this entrant's
acceptance, selected track, declarations, exact fields or mandatory hosted access.
Recheck the authenticated form and any updated organizer instructions before submission.
