# Modular bench station

[Platform scope](platform.md) · [Verification](verification.md)

This bounded non-liquid adapter develops an ordered station for one to four
distinct operations: **weigh**, **print a label**, **read a barcode**, and
**visually inspect**. It is a digital equipment-layout concept with manual
handoffs. It does not execute an automated laboratory process.

## Develop the station in chat

Start a new project and explicitly request the desired operation sequence, for
example: “Design a bench station to weigh items, print labels, read their barcodes
and visually inspect them, on a 900 mm wide bench.” Supported revisions can
reorder or explicitly remove operations. Requests to change an existing accepted
liquid-handling machine into this different station require a new project.

The station view shows conceptual module envelopes and their reserved functional
surfaces, an ordered workflow, equipment-selection guidance, sourcing candidates
and constraints. Width changes recompile the layout; a width too small for a
module and its reserved surface is rejected. Packing may add rows and increase
depth, so verify the required depth separately. These are application-defined
planning allocations, not manufacturer dimensions, physical fit checks or CAD
ready for fabrication.

Candidate links include OHAUS Scout SPX6201 AM, Zebra ZD421, Zebra DS2278 and an
Adafruit Raspberry Pi Camera Module 3. Selection requires verification of the
specific configuration, accessories and operating requirements. Camera purchasing
also needs a compatible host, cable, lighting, stand and sample support. Prices
in the site panel remain separate from the unpriced plan rows; retrieved listings
and model estimates are distinct and neither constitutes a complete station quote.

## Download and use the local runner

Download the layout SVG, plan JSON and Python runner from the station panel.
Keep the downloaded filenames as `plan.json` and `run.py`, or adjust the commands
to their actual names. Python 3 is required; the runner needs no extra packages,
network access or connected instrument.

To check the plan without entering sample data:

```powershell
python run.py --plan plan.json --output check.json --dry-run
```

This writes ordered pending human checkpoints with `not_executed` status and no
observations. To collect operator-entered observations:

```powershell
python run.py --plan plan.json --output record.json
```

The terminal asks for operator and item identifiers, then each selected operation.
Mass is manually entered in grams; barcode input may come from keyboard/HID or
manual entry and must match the item identifier. Printing and application require
explicit confirmation. Visual review records predefined visible criteria, a human
pass/fail decision and notes. Failed inspection stops subsequent operations.
These records identify their input plan by SHA-256 and retain project/revision
metadata. They are operator-entered evidence, not validated instrument acquisition.

For a printable local label file, use:

```powershell
python run.py --plan plan.json --output record.json --label-output label.html
```

This requires a plan containing the printing operation. At that step the runner
creates escaped **plain-text** HTML using the item identifier; it generates no
barcode. Open `label.html` locally and use the browser's print dialog. Its
**60 × 30 mm media size is an example**: check actual media, 100% print scale,
readability, fit and adhesive suitability before use. Identifiers are bounded to
80 characters and exclude control characters. Confirm printed/applied/readable
only after those actions have actually happened. No command is sent to a printer.

Output paths must be new and distinct from the input plan and from each other.
An interrupted interactive run retains a partial JSON record. If label creation
has completed, that record retains the label path, hash and physical confirmation
status. Inspect its status and pending event before treating any sequence as
complete. Dry-run mode does not create a label or request physical confirmation.

## Engineering limits

The SVG is a dimensioned planning drawing; there is no fabrication STEP/STL
export for this station. The viewer is schematic, and the layout checker only
checks allocated rectangular surfaces against the recorded width and each other.
Verify actual dimensions, bench depth/load, open-cover access, cables, mounting,
safety, measurement requirements and equipment integration separately. There is
no automatic transfer, label applicator, camera acquisition, image classifier,
hardware control, calibrated weighing integration or validated throughput.
