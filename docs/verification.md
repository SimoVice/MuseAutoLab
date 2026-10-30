# Delivery verification — 2026-10-30

The current digital demo passed the software and package checks below. Three varied
fresh Meta journeys have now completed. The third completed through the actual browser
on October 30 after explicit equipment clarification, followed by a real impossible-width
rejection that preserved the confirmed project. The earlier incomplete attempt remains
recorded. These are bounded integration observations, not a model-reliability benchmark
or laboratory validation.

Start with the [reviewer guide](demo-guide.md) and the
[video project](examples/demo-video-project.json). Opening that project and generating
its files need no API key. Fresh conversation requires separately configured Meta
access. The [three-minute captioned video](video/README.md) is available publicly;
the interactive product runs locally.

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

## Video project's actual package

The app reopened the third fresh journey's own saved project and generated a new
package with no Meta credentials configured. Exactly one export request ran. It
retained the same logical project, confirmed revision 9, 120 mm bed pose, 8 °C target,
inspection extension and 200/100/20 µL stock volumes. This is separate from the
earlier recorded example below.

| Property | Observed value |
| --- | --- |
| Generation time | 137.757 s |
| ZIP / expanded size | 80,319,463 / 408,897,507 bytes |
| File count | 25 |
| ZIP SHA256 | `f4f4232e28dacaebf3195ee95d70310cc916756f739a0f6abff2f37e2c23212a` |
| Consistency | All manifest byte sizes/hashes, input identity, project lineage and revision checked |
| Reopened STEP | Valid; 863 solids and 19 named components; original bed and arm/camera present |
| STEP reopen time | 211.34 s; no independent regeneration of this exact final package |
| Guide | Actual iframe and download; 9 SVGs × 19 legend entries within bounds |
| Simulation | `not_run` |
| Page errors / new Meta requests | 0 / 0 |

The uncut export recording is 151.16 s at 1440 × 1000, 25 fps and contains the entire
real generation wait. The edited video identifies any omitted waits. Its portable
project SHA256 is `e57412d1b784d21385987dba00bdec9911cc8ef930de62433287b7452a1c4dc2`.
An initial helper comparison stopped before any export request; it was corrected to
compare persisted extension fields with their rebuilt counterparts. The original input
was unchanged and only one CAD export ran.

## Earlier verified package

The app reopened the earlier recorded real-Meta project, confirmed revision **9**, and generated
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

### October 30: third complete fresh journey

The [new browser rehearsal](examples/delivery-third-rehearsal.json) completed on the
published application code, using 11 Contributor calls: ten for the core journey and
one for a 450 mm width request. That request was rejected with the entire confirmed
project payload unchanged; conversation history retains the rejected request.

The accepted project lowered the original bed from 100 to 120 mm, retained layout
through an 8 °C cold-bay request, reopened correctly, added the arm/camera, calculated
200/100/20 µL stock amounts and reached confirmed revision 9. The browser reported no
JavaScript errors. Its [portable project](examples/demo-video-project.json) is separate
from the earlier revision-9 example; revision numbers alone do not identify a project.

New usage was 71,961 input plus 6,405 output tokens. Across the earlier and new runs,
there were **68 physical attempts**, 67 provider responses and **480,928 reported tokens**
(428,780 input / 52,148 output), plus the same one historical unknown consumption.
The core chat turns totaled 72.437 s; the negative turn took 5.016 s. This excludes
save/reopen/confirmation overhead and CAD export. The actual browser capture retained
measured waits; its source recording is 108.8 s at 1440 × 1000.

This satisfies the proposed count of three varied fresh complete journeys. The first
preceded final parser hardening and was replayed offline through final checks; the
second and third used the final backend live. It is not a claim of three independent
fresh successes on identical historical code or a statistical reliability percentage.

### October 29: initial rehearsals, retained unchanged

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
No Meta calls were made during the package/reconstruction checks. The separate October
30 live browser rehearsal above accounts for its own 11 calls.

## Three-minute demo video

The [MP4 and English captions](video/README.md) use actual captures from the third
fresh journey and its own local reopen/export. The final file is **180.000 s**,
**1920 × 1080**, **30 fps / 5,400 frames**, H.264 and **5,150,399 bytes**, with no
audio stream. Its SHA256 is
`b8963266bbb8ad5564878bceff34b87e5fee3485ab1a1da6bd430ce13f6eb234`.

Full video decoding passed. Twelve frames distributed across the final MP4 were
visually inspected; the chat, bed change and actual guide also received dedicated
readability checks. All 11 source trims remain within their media duration, and
19 caption cues cover 0–180 s contiguously. Shortened waits, the separate negative
check shown out of recording order, and reopened results without new inference are
identified on screen. A narration script is supplied for an optional voiced edition.

The application code remains commit `81ef2ebf1581536505cbe8f71ac4b6d704614980`.
These delivery changes add documentation, evidence and media; they do not change
application code or its dependencies, so the earlier software checks were not rerun.

## Remaining delivery work

Verify the authenticated submission fields, entrant/track eligibility, declarations
and whether the organizer accepts the linked MP4 or requires a particular video host.
An [adaptable submission draft](submission-draft.md) is ready; no event entry has
been sent. Narration can be added after the entrant chooses a voice.
Current Jubilee and OT-2 routes have no physics or hardware-control adapter. CAD validity,
layout checks, kinematic inspection sweeps and dilution arithmetic do not establish
mounting, collision clearance, camera coverage, cooling, liquid handling or laboratory
performance. The final event submission is a separate action.
