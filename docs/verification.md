# Delivery verification — 2026-10-30

The current digital demo passed the software and package checks below. The proposed
gate of three complete fresh Meta journeys remains open: two completed; a third
correctly stopped to request missing equipment information. These are bounded
integration observations, not a model-reliability benchmark or laboratory validation.

Start with the [reviewer guide](demo-guide.md) and the
[recorded project](examples/demo-project.json). Opening that project and generating
its files need no API key. Fresh conversation requires separately configured Meta
access. No hosted product or final submission video is provided by this record.

## Software and reconstruction

| Check | Observed result | Scope |
| --- | --- | --- |
| Regular Python suite, October 30 | **415 passed**, 83.28 s | Backend, state preservation, arithmetic, imports, API, CAD/document boundaries and regressions; excludes the heavy source suite |
| Heavy source-CAD suite, October 29 | **8 passed**, 670.95 s | Original source geometry, STEP export/reopen, bed pose, independent standalone regeneration and altered-source rejection |
| Ruff | Passed | `app`, `tests`, `scripts` |
| TypeScript / Vite production build | Passed | Production frontend compilation |
| Six browser flows | Passed | Foundation, engineering choice, general platform, vision, scene focus and project files; explicit offline Meta fixtures, real app/API where required by each test |
| Isolated Windows reconstruction | Passed | New Python and JavaScript environments from unchanged locks; dependency/environment checks, production build and actual recorded-project open/re-save without credentials |
| Recorded-project browser review | Passed | Revision 9, real local source meshes, retained accepted proposals and 100/50/10 µL stock volumes; no new model request or page error |

The two Python suites contain **423 distinct tests**. Their runtimes are single-host
observations, not performance targets. The isolated environment used the same PC and
permitted existing package caches; it is not a second-machine or cache-cold benchmark.
The no-key review exercised the actual saved-project path rather than substituting
model responses. It does not establish fresh conversational behavior.

An initial restricted installation could not resolve the npm registry; the unchanged
locked installation passed with network access. Earlier restricted test attempts had
temporary-file permission failures. These environment failures remain in local logs.
A FastAPI/Starlette HTTPX deprecation warning and Vite bundle-size warning remain;
they did not fail the checks. No dependency versions were changed for this delivery.

Reproduction commands are in [Verify the product](../README.md#verify-the-product).
The browser project-files test uses controlled export fixtures to exercise reconnect,
guide display and revision guards. A final desktop check at 1440 × 1000 verifies that
opening the guide disables the overlapping sticky model and closing it restores the
normal viewer behavior; the 390 × 844 mobile check also passed. It is separate from
the actual heavy package check.

## Actual final package

The app reopened the recorded real-Meta project, confirmed revision **9**, and generated
the package through its ordinary UI on October 30. No Meta call or export fixture was
used for this check.

| Property | Observed value |
| --- | --- |
| Generation time | 154.44 s |
| ZIP / expanded size | 80,319,470 / 408,898,338 bytes |
| File count | 25 |
| ZIP SHA256 | `78f0453cbdcdb81e135dd0868cc10c1af76d85275e63a861f29a4ac4977bd25c` |
| Package consistency | Manifest hashes and project/revision references matched |
| Reopened STEP | Valid; 863 solids across 19 named components |
| Source pose / expansion | 130 mm recorded bed drop; actual bed geometry and arm/camera group checked |
| Assembly guide | All 19 legend entries inside each of 9 SVG view boxes; actual inline guide and HTML download exercised |
| Standalone guide at 390 px | No horizontal page overflow |
| Browser errors / new Meta calls | 0 / 0 |

The final STEP reopen took 209.239 s. It did not independently regenerate that exact
final package; standalone source regeneration is covered by the separate heavy suite.
This archive hash identifies one observed export. Reopening creates new runtime IDs,
so a newly generated package is not expected to have identical ZIP bytes. The portable
example SHA256 is `29aedcf73b7191698b3d405ae905311fb808b61a3a55d2cd2438b2c555ad7489`.

The approximately 80 MB archive is generated locally, not stored in Git. The repository
contains the portable example and instructions needed to reproduce it. Raw test logs,
original model responses, archives and detailed screenshots are retained locally;
private workspace records and credentials are excluded from publication.

## Real Meta rehearsals

The [curated rehearsal record](examples/delivery-rehearsal-summary.json) preserves the
October 29 outcomes, failures, timings, code fingerprints and usage boundaries:

- 57 physical Contributor attempts; 56 provider responses, all HTTP 200. A valid HTTP
  response does not imply the application accepted its content or completed the journey.
- 356,819 input and 45,743 output tokens reported. One interrupted request has unknown
  consumption; the 402,562 reported total is a lower bound, not billing or credit balance.
- Two complete fresh journeys and one recovered journey. The recovered one does not
  count toward the proposed three-fresh-journey gate.
- The first successful journey's ten recorded responses also passed an offline replay
  through the final parser/compiler checks; replay makes no provider calls and its
  historical token metadata is excluded from live totals. The second fresh run used
  the final backend fingerprints.
- The third fresh scenario omitted explicit equipment ownership. It remained incomplete
  while the application requested clarification; no successful third run is claimed.

Observed failures led to bounded source-text normalization, explicit current layout
context and deterministic checks on requested layout preservation. These guards support
a limited set of preserve/keep/retain/leave clauses, not universal language understanding.
No new Meta calls were made during the October 30 final package/reconstruction checks.

## Remaining delivery work

Complete the third varied fresh journey with required equipment clarified, then capture
and edit the final three-minute story and verify the actual submission fields/access.
Current Jubilee and OT-2 routes have no physics or hardware-control adapter. CAD validity,
layout checks, kinematic inspection sweeps and dilution arithmetic do not establish
mounting, collision clearance, camera coverage, cooling, liquid handling or laboratory
performance. The final event submission is a separate action.
