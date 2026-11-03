# See how the proposed setup moves

Operating previews connect the current design to an animated sequence. They help
review where the tool goes, which container it visits and how a different rack,
plate or recipe changes the proposed operation.

![Paused preparation preview with the selected plate, moving Jubilee assemblies and playback controls](images/operating-preview.png)

*Actual workspace capture at a planned transfer to A1. The displayed quantity is
a transfer total, not a measurement or a validated pipetting stroke.*

This is an adapter capability within MuseAutoLab's laboratory automation
platform. The initial preparation adapter covers the Jubilee setup with its
sample rack or supported 96-well plate. An accepted inspection concept has a
separate camera-sweep sequence. Unsupported platforms display a reason instead
of borrowing another machine's animation.

## Try it

The [saved plate and tip-rack example](examples/tip-rack-plate-project.json) can
be opened with **Open project** to inspect the preview without a model request.

1. Develop or open a supported design. A Jubilee preparation preview can run
   before a recipe is supplied, using the clearly labelled example described
   below. Generating CAD files is not required.
2. Select **Play** in **Operating preview**. The status identifies the current
   action, destination and intended transfer volume.
3. Use **Pause** or **Reset**. Expand **Playback details** to scrub the sequence
   or change its speed. The **Sequence** selector appears when the design
   includes a camera inspection or cold-transfer module.
4. Change the recipe, labware or tip-rack product. The preview stops and rebuilds
   against the accepted revision, including the selected holes and well addresses.
5. For an actual ready recipe, download the motion plan from **Playback details**
   to inspect its revision, component/profile bindings, positions and illustrative
   timing. The example sequence has no motion-plan download.

Playback does not edit the project, update costs, request a model response or send
commands to hardware. It starts only on an explicit action. Hiding the browser
or switching away from the model on mobile pauses it without losing the position.

Before any recipe quantity is entered, the example uses a 1 mg/mL stock, a
0.5 mg/mL target and 100 µL final volume in one destination, with 50 µL each of
stock and diluent. These values exist only in the local illustrative preview;
they are not saved as project inputs or included in project exports. Once a
recipe has been started, an incomplete or invalid recipe must be completed or
corrected before a preparation preview is available. A ready recipe uses its
own targets and calculated volumes. Approve the equipment and open **Software &
protocols** to enter or revise those quantities.

## What moves

Selecting the Jubilee platform in chat opens its rotatable source model while
the custom deck layout is being developed. An accepted workstation can run
its preparation preview with the pipette alone.

The preparation sequence shows tip pickup, the stock or diluent source, the
assigned destination and tip disposal. Zero-volume transfers are skipped. For a
plate, destinations follow the occupied well addresses rather than an evenly
spaced approximation; a twelve-position tube rack uses its actual hole centers.
Changing the tip-rack profile changes its visited positions as well as its shape.
Each illustrative tip transfers from its displayed rack slot to the tool and then
to waste; playback and seeking reconstruct available slots from the timeline. If
the supply runs out, a labelled manual refill is shown before reuse. This is an
illustration of a required intervention, not evidence that it took place.

Jubilee's source-derived carriage and crossbar move horizontally. The source bed,
custom deck and its mounted containers move together vertically. The planner
checks the application's 0–150 mm bed-pose envelope and rejects a sequence that
exceeds it. That envelope is a model constraint, not a verified machine travel
specification. The canonical design and STEP export remain at their accepted pose.

Inspection playback follows the accepted pose sequence and maintains rigid link
lengths. It does not capture images or establish a calibrated field of view.

### Transfer a plate into cold storage

With a compatible 96-well plate on an accepted Jubilee layout, try this request.

> Add a gripper to move the prepared 96-well plate into a dedicated refrigerator.

The design gains a top-opening cabinet with a landing shelf and a separate
Cartesian gripper. Select **Cold transfer** and press **Play**. The pipette
carriage and any inspection camera park to clear the pickup path. Inspect the open
jaws as they descend around the plate, then pause after release to see the plate
resting on the shelf. Its holder stays on the deck and the occupied well markers
travel with it. Reset returns the plate to its starting position for another run.

![The parked inspection arm at left and the gripper holding the prepared plate above the open refrigerator at right](images/plate-to-cold-storage.png)

The module can be saved with the project and removed in chat. It currently
supports one rigid plate. The cabinet and gripper are custom concepts with
no selected supplier. Grip force, open-plate handling, travel clearances and
temperature control need physical verification.

## Read the preview correctly

The displayed seconds are **preview time**, not a prediction of cycle time. Tool
approach offsets, disposable-tip representation and action durations are
illustrative. Containers must be open; cap handling and liquid dynamics are not
modeled. A transfer label shows the planned total, not measured dispensing.
Pipette capacity and splitting a transfer into repeated aspiration strokes are
not modeled; the sequence is not an executable liquid-handling protocol.

The source mesh is separated using the assembly hierarchy and spatial association
of nearby disconnected fasteners for rendering, while
the pinned source STEP is unchanged. The [asset provenance](../app/assets/jubilee-c877bd2.motion-preview.json)
records the original revision, license, partitions, transforms and mesh hashes.
The belt preview interpolates the original mesh between fixed frame turns and
moving crossbar/carriage attachments. It preserves the source rest shape but does
not simulate belt tension or pulley contact. The fastener association is an
approximation. Custom tool
attachments, motion clearance, loads, calibration and control still need
engineering verification. The viewer does not establish collision safety or a
successful physical simulation.

Downloaded motion plans explicitly set `execution_enabled` to `false`. They are
review artifacts, not G-code or protocols accepted by a robot controller. The
[software guide](software-and-protocols.md) describes the separate programming
and commissioning work.

## Implementation and verification

The frontend compiles a timeline from the accepted project and samples it using
one shared playback clock. The renderer applies rigid transforms without writing
them back to project geometry. Revision changes reset the preview; unavailable
adapters and invalid pose envelopes cannot be played.

See the [verification record](verification.md#plate-transfer-and-motion-continuity)
for numerical and browser checks. Rebuilding the committed source preview meshes
is optional and memory-intensive (about 22 GB was observed during conversion).
Normal playback loads the prepared assets and does not import the source STEP.
