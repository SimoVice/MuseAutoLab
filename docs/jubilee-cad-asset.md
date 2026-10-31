# Jubilee source assembly

![Current chat-only source-CAD workspace](images/chat-source-cad.png)

Actual application screenshot with explicit offline model fixtures. Source meshes,
the API, geometry compilation and saved/reopened state are real; the screenshot
is not a live Meta or hardware result. Live synthetic model outputs are recorded
separately in [the chat example](examples/chat-foundation-live.json).

The pinned, losslessly compressed Jubilee V2.2.2 STEP in `app/assets` is the
upstream work by Joshua Vasquez / Machine Agency, University of Washington,
licensed CC BY 4.0. The adjacent license and provenance manifest give the exact
revision, URLs, checksums, measured envelope, and modifications. Include both
with any redistribution or exported assembly that includes this geometry.

The viewer uses two approximations tessellated from that STEP: the static root
children and the upstream `build_plate_assembly`. The latter can move down by
0–150 mm as a bounded digital proposal; this does not establish a physical
travel limit, connecting mechanism, fit, or collision-free motion. The rest of
the source assembly retains its original geometry and positions. The original
STEP remains the CAD source, and the preview may omit small features; neither
view is evidence of a working machine. User-added fixtures and tools are
separate concepts and their interfaces are unverified.

## Parked tool and proposed bed position

The conceptual pipette and carriage now park at a fixed height in the frame;
they do not follow the bed. The compiler checks the vertical envelopes of the
five deck components against the bottom of that parked pipette, with a proposed
10 mm margin. It lowers the bed only as needed, within the layout's 95–150 mm
drop range, and rejects a layout that cannot meet this screen at 150 mm. For the
standard 80 mm waste bin, the minimum drop is 127.5 mm. The Opentrons 300 µL
tip-rack software reference is 64.49 mm high, so it fits below that parked
position in this envelope check. This checks neither moving tool paths nor
actual travel, source CAD collisions, mounting, tips, pickup or operation.

Jubilee projects now save with compiler version 8. Opening an older source-based
project with an accepted layout rebuilds the bed and parked head, preserves the
compatible layout and modules, and creates a new draft for review and
reconfirmation. The original saved file is not changed. The screenshot above
records an earlier version and does not show this change.

## Verified full export

The synthetic integration fixture produced a 396,887,598-byte expanded workstation
STEP and 408,150,757 bytes of CAD/source files. Its CAD-only ZIP was 80,215,348 bytes,
below the 128 MiB archive cap; the uncompressed set was below the 512 MiB cap. Other
layouts/modules can change these sizes. The compact native-reference writer
attempted during development did not preserve the changed bed pose after reopening
and is not used.

The full eight-test source suite passed in 703.10 seconds on the tested Windows
host. It reopened the actual STEP, checked validity, solid count, source and bed
bounds, executed the standalone regeneration script, reopened that output and
rechecked the bed. A changed source gzip was rejected by its raw STEP hash. These
are digital geometry checks, not mechanical travel, mounting or collision tests.

## Reproduce the viewer meshes

To regenerate the viewer assets, install the repository's locked Python and
web dependencies, then from the repository root run:

```
python scripts/prepare_jubilee_mesh.py
node scripts/simplify_jubilee_mesh.mjs static
node scripts/simplify_jubilee_mesh.mjs bed
```

These commands write scratch files in `.local/upstream-cad`. Compare their
hashes and bounding boxes to the manifest before replacing distributed assets.
The simplifier uses the meshoptimizer package present in the web dependency
lock, and the measured preview error is an approximation, not a manufacturing
tolerance. The source STEP and attribution must accompany downstream use.
