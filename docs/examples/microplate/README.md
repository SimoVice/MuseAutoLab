# Recorded microplate example

These files are digital review evidence for one synthetic tube-to-96-well example.
They do not record printed hardware, a physical plate fit, calibration or laboratory operation.

Open [the tube setup](../microplate-tube-setup.json) with the application's **Open project** control,
then describe the desired switch in ordinary chat. This before file is a deterministic synthetic
200 µL-per-tube setup, **not a fresh model result**. [The plate project](../microplate-project.json)
is the actual recorded second-round result, subsequently confirmed at revision 16. Both files
are byte-identical copies of their recorded originals. The plate has 96 wells; only the three
existing targets use A1, B1 and C1 at 200 µL each. The switch does not create 96 preparations.

## Small CAD subset

- [plate-holder.step](plate-holder.step) and [plate-holder.stl](plate-holder.stl): custom proposed
  holder only. Review the actual plate skirt, printer/material assumptions, locating method and
  first-article fit before fabrication or use.
- [plate-reference.step](plate-reference.step): schematic geometry derived from the pinned
  Opentrons software definition. **Do not fabricate this reference as a laboratory plate.**
  It is not manufacturer CAD or proof of compatibility with an exact commercial SKU.
- [geometry-report.json](geometry-report.json): original package geometry scope and unverified
  interfaces; `fabrication_ready` is false.
- [package-manifest.json](package-manifest.json): byte-identical manifest of the complete recorded
  archive. It inventories 31 files, including large files **not distributed in this small subset**.
  Its entries are archive paths, not links promising those omitted files exist here.

The reference definition and its Apache-2.0 license are already in the repository:
[definition](../../../app/data/labware/corning_96_wellplate_360ul_flat.json),
[provenance](../../../app/data/labware/provenance.json),
[license](../../../app/data/labware/LICENSE.txt). The imported Jubilee foundation and its
CC-BY-4.0 attribution remain separate; see [third-party notices](../../../THIRD_PARTY_NOTICES.md).
The holder is a custom proposal, not upstream Jubilee or manufacturer CAD.

## Evidence and retained failures

[microplate-verification.json](../microplate-verification.json) is the authoritative curated record
of byte hashes, model usage, package checks and limitations. Round 1 passed the original narrow
structural audit (8/8), but manual review rejected stale/contradictory user-visible prose. Round 2
recorded 7/8 automatically; the N2 reply explicitly said the old rack “stays as-is”, which the
evaluator failed to recognize. Manual review accepted all eight; strict request/response replay
passed 8/8 with
zero new model calls. Original failures and response digests are retained rather than overwritten.
The two fresh live rounds consumed 16 calls and 303,633 reported tokens in total; replay usage is
historical and is not counted again. These are developer-defined cases, not a held-out benchmark.

The original final package verification took 415.86 seconds across export, download, STEP
reopening and digital probes. It verified 861 solids (809 source solids), a separate holder and
schematic reference, and all 96 digital wells. This is not a CAD-only latency measurement.
An earlier verification timeout was not proof of CAD failure: the original job was later found
ready. The real UI capture also retains an initial timeout during concurrent CAD and a later
successful capture without new chat, price or CAD requests.

The small files here remain from that original package. A separate isolated-CAD run passed
the complete package/solid checks and 555 independent API reads, all below 2 seconds
(maximum 0.329 seconds). Its complete export/download/verification took 519.36 seconds.
The curated JSON records both runs separately; final software checks are recorded there too.
No supplier refresh, purchase or physical test is implied by these artifacts.

Actual result screenshots: [plate and card](../../images/microplate-switch.png),
[instructions](../../images/microplate-instructions.png). They show the recorded project,
not mocked provider responses. The separate before setup must always be labelled synthetic.
