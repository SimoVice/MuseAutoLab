# Keeping a project consistent as it changes

MuseAutoLab develops custom laboratory automation setups from a user's needs.
This review exercises its liquid-handling adapter: the same project moves from
tubes to a plate, changes a supplier product, takes another recipe and gains an
inspection module. The question is whether the model, costs and instructions
still describe the same accepted design after each edit.

The check ran on 2026-11-01–02 with the real application, Muse Spark Contributor
and public US supplier retrieval. Laboratory inputs were synthetic. Browser
regression checks used controlled responses separately from the live flow.

[Open the final project](examples/revision-consistency-project.json) through the
app's **Open project** control. The [curated verification record](examples/revision-consistency-verification.json)
contains the recorded scope, usage and artifact hash. A new server obtains its
own prices and estimates; the portable file is not a trusted price report.

## What changed

A recipe edit used to discard still-current supplier observations and request
new allowances for unchanged hardware. The verified subtotal could disappear
and the planning range could jump even though the shopping list was identical.

Accepted revisions now retain observations and estimates for unchanged purchase
scopes. Product identity, source, quantity, pack size and relevant geometry must
match. Original observation times and expiry remain intact. New parts need new
prices; expired observations do not become current by editing or reopening a
project. A failed estimate for additional parts leaves the valid existing
allowances visible and offers an explicit retry.

Repeating the existing bench width alongside a recipe edit could also invalidate
the accepted layout. Geometry is now reconsidered when the constraint actually
changes. The inspection guide reports the complete assembly footprint and asks
the user to check both bench dimensions and clearance.

The [workspace review](workspace-quality-review.md) covers readable chat scrolling,
text contrast, mobile navigation and the revised initial 3D view.

## Observed journey

| Change | Consistency checked |
| --- | --- |
| Describe recurring laboratory work | General discovery gathers needs; the engineering comparison waits for an explicit platform choice. |
| Choose Jubilee and a tube rack | Pinned source identity, declared tube dimensions, proposed rack and instruction parts agree. |
| Switch to a 96-well plate | The named Corning reference and holder replace the rack. Three preparations occupy A1, B1 and C1; switching containers does not create 96 samples. |
| Select TipOne, then Opentrons | The selected product changes its actual envelope and openings. The proposed 0.24 mm placement change is accepted explicitly; other parts and the recipe are preserved. |
| Check US prices | Supplier observations, missing prices and model planning allowances remain separately labelled in USD. |
| Ask about software | Platform-specific guidance and downloadable protocol templates refer to the current design. A guidance question preserves the recipe and layout. |
| Change the recipe | Stock/diluent calculations update while the accepted hardware remains unchanged. The downloaded logical preview agrees with the assigned wells. |
| Add inspection | Nine components and three purchase groups are added; the existing platform, labware and recipe remain intact. |
| Save and reopen | Canonical geometry and recipe are rebuilt from the portable project. Only matching observations already owned by the running server can be reused. |

The final recipe uses a 5 mg/mL stock, targets of 1, 0.2 and 0.1 mg/mL, and
150 µL per preparation. Stock/diluent pairs are **30/120, 6/144 and 3/147 µL**.
The downloaded local preview was actually executed; it does not control hardware.

The corrected live check repeated two recipe edits, 200 µL then 150 µL, followed
by confirmation and Save/Open. All retained the hardware, supplier scopes,
estimate identifier and original timestamps/expiry. No additional price-model
request was made for either recipe or reopening.

At that check, four of fifteen purchase groups had fresh supplier observations
totaling **USD 386.97**. Eleven labelled model allowances added **USD 1,320–5,290**,
for a covered planning range of **USD 1,706.97–5,676.97**. These dated observations
and planning assumptions are not a current quotation or complete build budget.

## Scope of the result

The inspection example occupies approximately **483.1 × 832.7 mm** before extra
mounting and motion clearance. Its stated 800 × 800 mm bench is therefore too
shallow. The existing automatic constraint check covers width; the footprint
notice and guide now make the required depth review explicit. This is not an
automatic two-dimensional fit or collision check.

The recorded journey contains preserved continuations: a development reload
interrupted the first browser attempt after its model response succeeded, and
two later harness stops concerned ambiguous or collapsed controls. These are
distinguished from the pricing defect found in the captured project data. It is
not presented as one uninterrupted clean run.

The first post-fix live recipe request was rejected because the model paraphrased
a bench constraint instead of copying its cited source span. The accepted project
and prices stayed unchanged. The model instruction now explicitly requires the
same literal span in both fields; the strict validator was retained. One retry
of the exact user request passed, followed by the second recipe and Save/Open.
The rejected response and its reported usage remain part of the test record.

The complete recorded work used **27 Contributor responses and 461,044 reported
tokens**: thirteen chat requests, two secondary design proposals and twelve cost
estimates across the original flow and its continuations. This includes the
rejected application response. Every provider response had usage; reused
estimates were counted only once. Three supplier refreshes were performed across
the original journey and two post-fix checks.

The final regular regression suite passed **1,043 tests**. Ruff across the app,
tests and scripts, and the production build/typecheck passed. Browser and 3D
checks are documented in the workspace review. Four outdated test expectations
or mock signatures were corrected after the broader run exposed them; they
covered new protocol files, the estimate-call signature and discarded empty
price reports. The existing large JavaScript bundle advisory remains.

A separate full CAD export completed in **228.969 seconds**, producing forty
files. The audit found an old sentence in `extensions.md` implying MuJoCo support
for the selected Jubilee platform. The document generator now states that this
platform has no simulation adapter. A corrected forty-one-file archive was
built from the original export, with an explicit provenance record: all twenty-one
CAD, simulation and project files are byte-identical. Price-report JSON data is
unchanged; only its serialization differs. This was a document-only repackage,
not another CAD run. The standalone source-CAD regression suite was not rerun.

Independent review passed 2,145 captured-data assertions and 306 archive checks,
including every manifest hash and size. These counts describe consistency checks,
not separate laboratory experiments. Original and corrected archive hashes are
recorded in the linked verification JSON.

These checks establish digital consistency within the implemented adapters.
They do not establish physical fit, calibrated pipetting, a commissioned robot
controller, complete build cost or arbitrary laboratory-machine generation.
