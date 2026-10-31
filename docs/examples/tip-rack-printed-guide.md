# Build and setup instructions

Project d22a1381-3c5f-47e7-984e-e5300da957c8 · revision 15 · jubilee

Review-ready document; not an assembly completion or physical validation record

mm; X right, Y up, Z depth; canonical component centers

## Review this revision and selected configuration

Status: ready

Prerequisites: None

- Use project d22a1381-3c5f-47e7-984e-e5300da957c8 revision 15; compare part IDs, selected variants and quantities below with the project model.
- Review the proposed layout before buying or fabricating. Geometry instances and procurement group quantities are different counts; an imported platform is one assembly.
- No current US procurement report is attached; historical sourcing prices are not a current complete machine quotation.

Checks:

- Project ID and revision match the model and downloaded files.
- Ready labels mean document review readiness, never completed assembly.

## Inventory the original Jubilee platform

Status: reference_only

Prerequisites: design-review

- Keep the source platform at the pinned revision and retain its CC-BY-4.0 attribution.
- Open the upstream BOM and assembly booklets. Separate purchased, fabricated and already-owned upstream parts before ordering; confirm the booklet revision matches the parts.
- foundation-jubilee: center \[0, 282.2, 0\] mm; envelope \[483.1, 564.4, 612.7\] mm.

Checks:

- Pinned source and upstream inventory are recorded; no custom insert included as upstream hardware.

Part foundation-jubilee: 1 geometry instance.
- Selected upstream-platform: source-cad (Pinned Jubilee V2.2.2 CAD / BOM); procurement group quantity 1. [Catalogue/source](<https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP>)

Source: [Jubilee V2.2.2 hardware](<https://github.com/machineagency/jubilee/tree/c877bd2e889560c83da2a68479641a4f7f0d9b83>) · checked 2026-10-28
Only the identified STEP asset is imported. Custom inserts/tools/mounts, proposed bed pose, connections and hardware operation remain unverified. The legacy XYZ simulation does not validate Jubilee.
Attribution: Joshua Vasquez / Machine Agency; CC-BY-4.0.

Source: [Jubilee 2 hardware assembly index](<https://jubilee3d.github.io/machines/jubilee_2/hardware_assembly.html>) · checked 2026-10-30
Live documentation navigation and linked booklets; not pinned to the CAD revision. Electronics and tools sections remain TODO.


Source: [Jubilee 2 upstream BOM navigation](<https://jubilee3d.github.io/machines/jubilee_2/bom.html>) · checked 2026-10-30
Links the upstream sheet; not a complete price or compatibility verification.


## Follow the upstream mechanical build sequence

Status: reference_only

Prerequisites: source-parts

- Use the upstream frame booklets for original subassemblies: outer frame, aluminum motor plates, pulley corners, crossbar, toolchanger lock/carriage, lower frame, CoreXY and Z axis.
- Follow the original instructions and their inventory for each subassembly; do not derive screws, tolerances or tightening values from the simplified envelope diagram.
- foundation-jubilee: center \[0, 282.2, 0\] mm; envelope \[483.1, 564.4, 612.7\] mm.

Checks:

- Original frame and bed subassemblies are identified against the matching upstream booklets.

Part foundation-jubilee: 1 geometry instance.
- Selected upstream-platform: source-cad (Pinned Jubilee V2.2.2 CAD / BOM); procurement group quantity 1. [Catalogue/source](<https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP>)

Source: [Jubilee 2 hardware assembly index](<https://jubilee3d.github.io/machines/jubilee_2/hardware_assembly.html>) · checked 2026-10-30
Live documentation navigation and linked booklets; not pinned to the CAD revision. Electronics and tools sections remain TODO.


Source: [Jubilee 2 outer frame booklet](<https://jubilee3d.github.io/machines/jubilee_2/instructions/outer_frame.html>) · checked 2026-10-30
Official page links the illustrated frame PDF; check revision before building.


Source: [Jubilee 2 CoreXY booklet](<https://jubilee3d.github.io/machines/jubilee_2/instructions/corexy_frame.html>) · checked 2026-10-30
Official page links the illustrated CoreXY PDF; not a custom pipette adapter.


Source: [Jubilee V2.2.2 hardware](<https://github.com/machineagency/jubilee/tree/c877bd2e889560c83da2a68479641a4f7f0d9b83>) · checked 2026-10-28
Only the identified STEP asset is imported. Custom inserts/tools/mounts, proposed bed pose, connections and hardware operation remain unverified. The legacy XYZ simulation does not validate Jubilee.
Attribution: Joshua Vasquez / Machine Agency; CC-BY-4.0.

## Review the proposed bed pose and custom insert

Status: needs_design

Prerequisites: upstream-frame

- Proposed bed drop: 120.0 mm from the pinned STEP pose; deck origin: \[-1.6, 252.9, -6.1\] mm in application coordinates.
- Retain the unscaled source frame. Use the insert's canonical dimensions and position below to prepare an interface drawing, not a drill pattern inferred from the preview.
- foundation-jubilee: center \[0, 282.2, 0\] mm; envelope \[483.1, 564.4, 612.7\] mm.
- base: center \[-1.6, 258.9, -6.1\] mm; envelope \[300, 12, 300\] mm.

Checks:

- Insert drawing references the source bed and leaves source geometry unchanged.

Part foundation-jubilee: 1 geometry instance.
- Selected upstream-platform: source-cad (Pinned Jubilee V2.2.2 CAD / BOM); procurement group quantity 1. [Catalogue/source](<https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP>)

Part base: 1 geometry instance.

Required deliverable: Specify insert material, attachment datums, fasteners and removable access.
Complete when: A reviewed drawing/BOM defines the bed-to-insert joint and fabrication tolerances.

Required deliverable: Check the proposed bed pose over required travel with tooling and cables.
Complete when: Record physical clearance and attachment checks before moving hardware.

Source: [Jubilee V2.2.2 hardware](<https://github.com/machineagency/jubilee/tree/c877bd2e889560c83da2a68479641a4f7f0d9b83>) · checked 2026-10-28
Only the identified STEP asset is imported. Custom inserts/tools/mounts, proposed bed pose, connections and hardware operation remain unverified. The legacy XYZ simulation does not validate Jubilee.
Attribution: Joshua Vasquez / Machine Agency; CC-BY-4.0.

## Resolve the pipette mount and actuation

Status: needs_design

Prerequisites: frame

- Use the selected pipette/adapter envelopes and exact positions below. Compare the actual pipette with the documented Science Jubilee tools; reference availability does not make this custom mount compatible.
- carriage: center \[-1.6, 499.9, -6.1\] mm; envelope \[75, 70, 65\] mm.
- pipette: center \[-1.6, 404.9, -6.1\] mm; envelope \[28, 155, 28\] mm.

Checks:

- Pipette retention, plunger/tip actuation and full travel are checked against actual parts.

Part carriage: 1 geometry instance.

Part pipette: 1 geometry instance.
- Selected pipette: custom (Custom pipette and tip handling); procurement group quantity 1.

Required deliverable: Measure the actual pipette and design its retention, actuation and tool interface.
Complete when: Review dimensioned adapter drawings, actuator selection and collision/force checks.

Source: [Science Jubilee laboratory tools](<https://github.com/machineagency/science-jubilee/tree/bb918fa78f300f57cc379a80731cfca7bdb55c66>) · checked 2026-10-28
No Science Jubilee control code or CAD is installed in MuseAutoLab. A reference workflow is not a compatible ready-made adapter or verified liquid-handling result.
Attribution: Machine Agency; MIT (repository); upstream hardware has separate licensing.

## Review the tube envelope and custom rack geometry

Status: ready

Prerequisites: design-review

- Use the actual tube intended for this dry fit. A 1.5–2 mL label is not a dimensional specification and no supplier SKU is inferred.
- Declared maximum body diameter: 12 mm; minimum support rim diameter: 15 mm; maximum closed cap envelope: 18 mm; underside-of-rim to tip height: 40 mm.
- Check body diameter over every section that passes through the hole; measure the minimum underside bearing rim, and the maximum closed cap including rim and closed hinge protrusions. Open-cap motion is not modeled.
- The rack has 12 positions in 3 rows and 4 columns; envelope \[81.5, 43, 56.7\] mm (width, height, depth), CAD bore 13.1 mm and pitch 18.8 mm.
- The rack is one custom printed bridge with a perforated top and two end legs, no floor and no fasteners. The original Jubilee source geometry and separate source rack are unchanged.
- The bore includes 0.4 mm radial clearance plus a 0.3 mm diameter allowance for an assumed FDM bore deviation of ±0.3 mm. These process assumptions have not been measured on your printer.
- sample-rack: center \[68.4, 286.4, -71.1\] mm; envelope \[81.5, 43, 56.7\] mm.

Checks:

- The declared measurements match the intended tube and recorded input sources.
- Calculated worst-case rim land is 0.8 mm, at least 0.4 mm; this is a geometric calculation, not a physical fit result.

Part sample-rack: 1 geometry instance.
- Selected labware-rack: rim-rack-v1 (Custom rim-supported tube rack); procurement group quantity 1.

## Prepare the fit coupon and print the one-piece rack

Status: ready

Prerequisites: rack-inputs

- Confirm this revision and generate its project files. Use the rack-only cad/tube-rack.step or cad/tube-rack.stl; they retain the upright engineering orientation.
- In the slicer rotate the rack so the broad top plate lies flat on the print bed, with both end legs pointing upward. Do not scale the part to correct fit.
- Before a full rack, print cad/tube-rack-fit-coupon.stl with the same 13.1 mm bore and 4 mm plate thickness, using the intended printer and settings. The supplied coupon is flat; place its broad face on the print bed. The STEP counterpart is cad/tube-rack-fit-coupon.step.
- PETG is a proposed material for a dry fit prototype only. Choose printer settings and material suitability separately; no sterilization, chemical resistance or laboratory temperature performance is established.
- Inspect the slicer preview for continuous walls and an unobstructed bore. After the coupon is accepted, print one complete rack, cool it before removal and remove loose strings without enlarging its support holes.
- sample-rack: center \[68.4, 286.4, -71.1\] mm; envelope \[81.5, 43, 56.7\] mm.

Checks:

- The slicer uses the correct revision, millimetres and top-plate-down orientation.
- One rack is required; material, printing and rework costs remain unpriced.

Part sample-rack: 1 geometry instance.
- Selected labware-rack: rim-rack-v1 (Custom rim-supported tube rack); procurement group quantity 1.

## Measure the first article and dry fit the actual tubes

Status: needs_design

Prerequisites: rack-print

- Record printer, material, settings, part revision and actual tube identity. Use a suitable dimensional gauge or caliper; record bore and body variation instead of relying on the rendered model.
- Measure bores in perpendicular directions through the support zone. The proposed bore band is 12.8–13.4 mm. For the largest tube body, actual minimum radial clearance must be at least 0.4 mm; use (smallest measured bore − largest body diameter) / 2.
- Use (smallest measured rim − largest measured bore) / 2 to verify at least 0.4 mm radial bearing land. The rim must seat evenly and retain the tube without the body being forced through or the rim falling through.
- Dry fit one empty, closed tube first; then all 12 positions. The nominal tube-tip clearance above the bench is 3 mm. Verify every tip stays clear, the rack stands flat, closed caps do not interfere, and tubes can be removed by hand.
- Reject or revise through chat if the coupon or first article misses the criteria. No successful print, fit or laboratory operation is recorded by generating this guide.
- sample-rack: center \[68.4, 286.4, -71.1\] mm; envelope \[81.5, 43, 56.7\] mm.

Checks:

- First-article records show bore band, minimum radial clearance and rim land met.
- All positions retain the intended empty tubes and leave tips clear of the bench.
- Open hinge motion, loaded-rack strength and liquid handling remain unchecked.

Part sample-rack: 1 geometry instance.
- Selected labware-rack: rim-rack-v1 (Custom rim-supported tube rack); procurement group quantity 1.

Required deliverable: Record coupon and first-article measurements before accepting the printed rack.
Complete when: Retain tube identity, dimensions, bore/rim clearance measurements and an all-position dry-fit record; any failure triggers a revised rack.

## Place the accepted rack and resolve its deck retention

Status: needs_design

Prerequisites: rack-fit, frame

- After the physical dry fit, place the rack at the canonical sample-rack position below. The one-piece rack has no integrated deck fasteners.
- Define how the rack is located and retained on the custom insert, without altering the imported Jubilee frame. Check access and travel using the actual tool, loaded tubes and cables before powered operation.
- Tube centers and rack geometry are a placement proposal. The current system does not calibrate pipette approach, tip reach or liquid-handling accuracy.
- sample-rack: center \[68.4, 286.4, -71.1\] mm; envelope \[81.5, 43, 56.7\] mm.

Checks:

- A reviewed locating/retention method and measured tool clearances exist.
- Rack fabrication fit is tracked separately from machine commissioning.

Part sample-rack: 1 geometry instance.
- Selected labware-rack: rim-rack-v1 (Custom rim-supported tube rack); procurement group quantity 1.

Required deliverable: Design and verify the insert-to-rack locating and retention interface.
Complete when: Record actual deck datum, retention details, tool access and clearance checks before moving the machine with the rack installed.

## Print and measure a tip-holder fit coupon first

Status: needs_design

Prerequisites: design-review

- This part is a holder for purchased disposable tips. Never print disposable tips from these files. Printer access was declared by the user; printer model, build envelope, material, settings and cleaning need review.
- Use tip-rack-fit-coupon.stl from this revision's CAD package before the full holder. Print the top face on the bed and inspect the slicer preview.
- Declared body maximum 6 mm; supporting rim minimum 9 mm and maximum 10 mm; below-rim height 35 mm. Nominal volume was not used for fit.
- Assumed bore 7.1 mm, pitch 10.8 mm. Verify coupon retention, clearance and bearing with the actual tip. Revise dimensions if it binds, falls through or rocks.
- tip-rack: center \[-71.6, 283.9, 28.9\] mm; envelope \[73.1, 38, 45.5\] mm.

Checks:

- Coupon dimensions and tip fit recorded before printing the full holder.
- Printer/material/settings and cleaning requirements reviewed.

Part tip-rack: 1 geometry instance.
- Selected tip-rack-options: custom_printed_tip_rack (Printed holder for purchased tips); procurement group quantity 1.

Required deliverable: Check the coupon and record actual fit on the intended printer.
Complete when: A measured coupon, tip identity and fit record exist.

## Fabricate and dry-check the full tip holder

Status: needs_design

Prerequisites: tip-rack-coupon, frame

- After coupon acceptance, print tip-rack.stl with the same validated setup. Inspect all holes/supports; dry-fit bought tips in all positions.
- Use the canonical tip-rack placement below. Design locating/retention on the Jubilee insert; check actual pipette pickup, strength and clearances. This design does not verify sterility, fit or laboratory suitability.
- tip-rack: center \[-71.6, 283.9, 28.9\] mm; envelope \[73.1, 38, 45.5\] mm.

Checks:

- All-position retention, deck attachment and tool access physically checked.

Part tip-rack: 1 geometry instance.
- Selected tip-rack-options: custom_printed_tip_rack (Printed holder for purchased tips); procurement group quantity 1.

Required deliverable: Verify the printed holder/deck interface with actual tips and pipette.
Complete when: Retain all-position dry-fit, attachment and pickup/clearance checks.

## Match the remaining labware to the layout

Status: needs_design

Prerequisites: frame

- Compare the numbered layout and positions below with actual rack, tube, tip and waste dimensions. Keep each component ID attached to its source/destination role.
- On OT-2 use the assigned software slots with supported labware definitions; on a custom insert specify locating features and removable access before fabrication.
- The custom sample rack has its own input, print, first-article and placement steps above; this step covers the remaining source, tip and waste fixtures.
- source-rack: center \[-71.6, 286.9, -71.1\] mm; envelope \[95, 44, 70\] mm.
- tip-waste: center \[-71.6, 304.9, 103.9\] mm; envelope \[55, 80, 55\] mm.

Checks:

- Actual labware, capacity, access and locating method match the accepted placements.

Part source-rack: 1 geometry instance.
- Selected fixtures: custom (Custom printed fixtures and labware); procurement group quantity 1.

Part tip-waste: 1 geometry instance.
- Selected fixtures: custom (Custom printed fixtures and labware); procurement group quantity 1.

Required deliverable: Record exact labware/tip definitions and verify fit at every assigned position.
Complete when: Approved labware IDs and a recorded fit/position check replace the proxy assumptions.

## Specify the custom control and power interfaces

Status: needs_design

Prerequisites: motion-pipette

- The shown enclosure is a placement proposal. Select the actual controller, actuators, supply and protection before preparing a schematic.
- Use the upstream controller-specific wiring/configuration for the original platform. Do not treat legacy motor/driver selections as a replacement Jubilee controller BOM.
- controller: center \[68.4, 289.9, 43.9\] mm; envelope \[90, 50, 80\] mm.

Checks:

- A reviewed schematic and I/O/interface list exist for the actual hardware.

Part controller: 1 geometry instance.
- Selected power: custom (Custom power, wiring and protection); procurement group quantity 1.

Required deliverable: Define controller/driver interfaces, power sizing, wiring and stop behavior.
Complete when: Reviewed schematics identify actual parts, connectors, protection and firmware boundaries.

Source: [Jubilee V2.2.2 hardware](<https://github.com/machineagency/jubilee/tree/c877bd2e889560c83da2a68479641a4f7f0d9b83>) · checked 2026-10-28
Only the identified STEP asset is imported. Custom inserts/tools/mounts, proposed bed pose, connections and hardware operation remain unverified. The legacy XYZ simulation does not validate Jubilee.
Attribution: Joshua Vasquez / Machine Agency; CC-BY-4.0.

## Resolve the selected cooling module interface

Status: needs_design

Prerequisites: racks

- Selected cooling variant: diy-peltier; requested target: 8.0 C. Use the recorded envelope and manual transfer workflow; the target is not a measured sample temperature.
- cold-storage: center \[0, 80, 411.3\] mm; envelope \[150, 120, 130\] mm.

Checks:

- Module, sample holder and manual access fit the proposed layout.

Part cold-storage: 1 geometry instance.
- Selected cooling: diy-peltier (Adafruit Peltier assembly with heatsink and fan (1335)); procurement group quantity 1. [Catalogue/source](<https://www.adafruit.com/product/1335>)
- Selected temperature-sensor: probe (Adafruit waterproof DS18B20 probe (381)); procurement group quantity 1. [Catalogue/source](<https://www.adafruit.com/product/381>)
- Selected power: custom (Custom power, wiring and protection); procurement group quantity 1.

Required deliverable: Specify thermal block/sample holder, mounting, supply and condensation management.
Complete when: Record reviewed interfaces and a sample-temperature verification plan for the selected configuration.

## Resolve the accepted inspection sidecar

Status: needs_design

Prerequisites: frame, racks

- Keep the accepted sidecar, mast, two links and camera at the canonical placements. Use inspection-module.json for the digital poses and dimensions.
- Kinematic reach screening does not verify load, collision clearance, cable routing or image coverage.
- inspection-mount: center \[161.6, 254.9, 421.3\] mm; envelope \[140, 24, 210\] mm.
- inspection-mast: center \[161.6, 457.4, 456.3\] mm; envelope \[42, 385, 42\] mm.
- inspection-shoulder: center \[161.6, 664.9, 456.3\] mm; envelope \[58, 30, 58\] mm.
- inspection-upper-link: center \[107.5, 664.9, 329.9\] mm; envelope \[141.2, 26, 267\] mm.
- inspection-elbow: center \[53.5, 664.9, 203.5\] mm; envelope \[58, 30, 58\] mm.
- inspection-forearm: center \[61, 664.9, 66.2\] mm; envelope \[50.9, 26, 276.5\] mm.
- inspection-wrist: center \[68.4, 664.9, -71.1\] mm; envelope \[40, 30, 40\] mm.
- inspection-camera-mount: center \[68.4, 632.7, -71.1\] mm; envelope \[12, 34.2, 12\] mm.
- inspection-camera: center \[68.4, 609.9, -71.1\] mm; envelope \[25, 11.5, 24\] mm.

Checks:

- The arm does not change the accepted base platform; measured image calibration is separate.

Part inspection-mount: 1 geometry instance.
- Selected inspection-mount: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-mast: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-shoulder: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-upper-link: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-elbow: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-forearm: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-wrist: 1 geometry instance.
- Selected inspection-arm: unselected-concept (Hardware selection pending); procurement group quantity 1.

Part inspection-camera-mount: 1 geometry instance.
- Selected inspection-camera: unselected-concept (Camera Module 3 + custom mount (integration pending)); procurement group quantity 1. [Catalogue/source](<https://www.raspberrypi.com/products/camera-module-3/>)

Part inspection-camera: 1 geometry instance.
- Selected inspection-camera: unselected-concept (Camera Module 3 + custom mount (integration pending)); procurement group quantity 1. [Catalogue/source](<https://www.raspberrypi.com/products/camera-module-3/>)

Required deliverable: Design the sidecar attachment, joint hardware, actuators and camera/host cable route.
Complete when: Reviewed load/interface drawings and actual clearance/image-coverage checks exist.

Source: [Raspberry Pi Camera Module 3, standard lens](<https://www.raspberrypi.com/products/camera-module-3/>) · checked 2026-10-28
Schematic envelope, not vendor CAD. The custom bracket is separate; host, cable, field of view and calibration are unresolved. Browser photo capture is not a CSI hardware driver. Price is unknown.
Attribution: Raspberry Pi Ltd; Manufacturer documentation; no vendor CAD redistributed.

## Complete the handover checks before physical operation

Status: needs_design

Prerequisites: source-parts, upstream-frame, frame, motion-pipette, rack-inputs, rack-print, rack-fit, rack-placement, tip-rack-coupon, printed-tip-rack, racks, controller, cold-bay, inspection-extension

- Review every engineering task and retain the upstream build/setup records for the actual configuration.
- Review preparation.csv and automation/preview.py as a logical liquid-transfer trace only. MuseAutoLab has no control/physics adapter for the selected Jubilee or OT-2 route.
- Physical operation needs an approved hardware integration and process verification record.

Checks:

- All custom engineering tasks have named deliverables and verification records.
- Actual liquid handling has been checked before using valuable samples.

Required deliverable: Prepare a hardware commissioning and liquid-transfer verification procedure.
Complete when: Record actual calibration, dry-run/clearance and dispensing checks before release.
