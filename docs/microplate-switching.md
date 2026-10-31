# Change labware with one message

The Jubilee sample module supports a reversible change between the existing tube
rack and a named 96-well reference. The ordinary design chat is the request surface.
The change updates the model, destination addresses, capacity checks, part list,
build instructions and portable project together.

## Demonstration sequence

Use **Open project** with the [synthetic tube setup](examples/microplate-tube-setup.json)
for the before state. Its current recipe is 200 µL; the historical conversation
contains an earlier 2 mL recipe because setup was changed deterministically for
this test. The [confirmed plate result](examples/microplate-project.json) can also
be reopened without inference. [Evidence and failures](examples/microplate-verification.json)
describe exactly which parts used the real model.

Start with an accepted Jubilee project and a preparation volume that fits both
formats. **200 µL per target** is a synthetic demonstration input, not a validated
working-volume recommendation. Container capacity and preparation volume are
different: a 1.5 mL tube may contain a 200 µL preparation.

1. Focus the sample rack in the model.
2. Send **“Replace the sample tubes with a 96-well plate.”**
3. Inspect the 8 × 12 array, marked A1 corner and assigned wells. Three existing
   preparations remain three preparations: A1, B1 and C1 in the reference's
   column-major order. The remaining wells stay unassigned.
4. Open **Build instructions** for the selected profile, volume check, holder
   fabrication/fit and placement guidance. Review the revised project before
   confirming and generating the CAD package.
5. Send **“Restore the previous tube rack.”** to recover its stored dimensions
   and position. Explicit changes to the recipe are retained.

If the old recipe contains 2 mL per target, a format-only change displays the plate
as a draft with a volume conflict. Confirmation and confirmed-package generation
remain blocked. Request a new volume explicitly, for example:
**“Switch to a 96-well plate with 200 µL per well.”** The application
does not silently shrink a recipe to make it fit.

## Selected reference and geometry

The initial profile is **Corning 96 Well Plate 360 µL Flat**, from the
[official Opentrons software definition](https://github.com/Opentrons/opentrons/blob/95a8a37922cfd5f46ad26c983bcc1659fa13b6e1/shared-data/labware/definitions/2/corning_96_wellplate_360ul_flat/1.json).
The definition and Apache-2.0 license are bundled unchanged with their revision
and hash. A generic 96-well request selects this visibly named reference. It does
not establish compatibility with every 96-well plate or an unspecified Eppendorf
product. Different plate families need a reviewed profile.

The reference supplies a 127.76 × 85.47 × 14.22 mm envelope, 96 named wells at 9 mm
pitch and a 360 µL reference maximum. Its schematic wells use the supplied
6.86 mm diameter and 10.67 mm depth. This is a software-derived representation,
not manufacturer CAD. A1 lies at positive model Z; columns increase along X and
rows A–H proceed toward negative Z. Verify the actual marked corner before use.

The separate shallow holder uses the maximum base footprint in
[ANSI/SLAS 1-2004](https://www.slas.org/SLAS/assets/File/public/standards/ANSI_SLAS_1-2004_FootprintDimensions.pdf),
plus 0.4 mm functional clearance per side and an assumed 0.3 mm total FDM pocket
undersize allowance. Its pocket is 129.36 × 87.08 mm, with a 2.5 mm floor, 3 mm
walls and a 2 mm lip. The standard's base footprint does not specify the entire
plate body or prove actual flange fit. Material and printer settings remain open.

The compiler may move only the sample module to the closest checked position
within the accepted insert, maintaining its modeled edge/neighbor clearances.
The original machine geometry remains fixed. An existing inspection proposal
retains its dimensions and mounting choice; its illustrated joint poses are
recomputed for the moved target. This is geometry, not a collision or coverage test.

## Output and limits

The confirmed package separates **`cad/plate-holder.step` / `.stl`** from
**`cad/plate-reference.step`**. The holder is a single fused part, printed with its
flat bottom down. The reference plate is schematic and is not a fabrication file
for laboratory labware. The package retains source definition, license, geometry
report, full workstation and self-contained regeneration source.

Compiler 6 stores the reviewed profile binding and prior rack inputs; opening a
project rebuilds canonical geometry and checks its placement. Earlier tube-only
projects retain compiler 5 behavior. A plate and custom tube rack cannot both
occupy the sample module.

The current adapter is for Jubilee. Plate procurement, holder fabrication and
mounting remain unpriced. Actual fit, retention, lid/body clearance, material and
cleaning suitability, pipette range/access, calibration and liquid handling are
unverified. A reference maximum is not a validated working volume. Operating
animation is disabled for this module until a corresponding adapter exists.
