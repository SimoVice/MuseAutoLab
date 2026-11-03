# Revision-bound parts proposals

`GET /api/projects/{id}/parts?revision=N` returns the same `parts_proposal` view
included in project responses. It is an offline derivation: rendering does not
contact suppliers or generate model estimates. Purchase groups come from the
selected project route, including custom concepts and human-operated stations.

Every line records quantity, unit, effective unit allocation, purchase-group range,
evidence kind/date, source reference, alternatives and integration guidance.
Whole-pack supplier totals and model group totals are used once, without a second
quantity multiplication. Alternatives are excluded from the sum. The total is for
listed scopes; it excludes shipping, tax, labor, engineering and commissioning.

Current supplier observations take precedence over an unobserved budget allowance.
Revision-valid model ranges remain model estimates. Remaining scopes receive an
explicit engineering planning allowance, with its assumptions exposed. A reference
URL identifies equipment to evaluate; it is not evidence for that allowance.
The OT-2 scenario allocates one bundled pipette to its base to avoid charging twice.

## Primary references reviewed on 2026-11-03

| Reference | Consultation | What it supports | What it does not establish |
| --- | --- | --- | --- |
| [Accucold ARS1MLDL2B](https://www.accucold.com/product/ARS1MLDL2B) | Product/specification page | Compact laboratory refrigerator, 115 V/60 Hz; 2–10 °C; cabinet 17.5 × 19.75 × 21.5 inches | Price, automatic door interface, fit to the displayed custom cabinet, suitability for a particular sample |
| [ServoCity 3219-0001-0002](https://www.servocity.com/servo-driven-parallel-gripper-kit-servo-included/) | Product, kit contents and download links | Servo-driven parallel mechanism with included servo; listed $34.99 for the gripper kit alone | Full gantry price, plate opening/retention, payload, travel or compatibility with the project |
| [ServoCity assembly instructions](https://www.servocity.com/content/user_manuals/3219-0001-0002_assembly_instructions.min.pdf) | Link identified on manufacturer product page | Manufacturer's assembly resource for this gripper kit | Instructions for the custom transfer machine; PDF content not independently validated in this increment |
| [Adafruit 5657](https://www.adafruit.com/product/5657) | Product/specification page | Camera Module 3 Standard; listed $29.25, excluding host and optional cables | Complete inspection system cost, field of view, calibrated detection or mounting compatibility |
| [Science Jubilee pipette tool](https://science-jubilee.readthedocs.io/en/latest/building/pipette_tool.html) | Project documentation | Open tool reference mounting OT-2 pipettes to Jubilee | Applicability of the current custom pipette concept; the project advises against buying costly OT-2 pipettes specifically for this tool |
| [Adafruit wall supplies](https://www.adafruit.com/category/137) | Supplier category | Real US catalogue route for power supplies | A selected voltage, current rating, SKU, system wiring or quoted complete electrical price |
| [Protolabs 3D printing](https://www.protolabs.com/services/3d-printing/) | Service page | Real fabrication quotation route | A particular polymer, tolerances, biological suitability, manufacturability or price |
| [Corning 3596](https://ecatalog.corning.com/life-sciences/b2c/US/en/Microplates/Assay-Microplates/96-Well-Microplates/Corning%C2%AE-96-well-Clear-Polystyrene-Microplates/p/3596) | Manufacturer catalogue | Exact 96-well plate purchasing reference; case of 50 | A one-plate procurement price, validated custom holder fit or suitability for every application |
| [Opentrons 300 µL tips](https://opentrons.com/products/opentrons-300ul-tips-1000-refills) | Manufacturer catalogue | Purchasing route for the named tip family | Compatibility with arbitrary manual pipettes or a different volume profile |
| [USA Scientific ACT catalogue](https://www.usascientific.com/act) | Official manufacturer page and exact SKU search | Identifies 1111-0200 as TipOne 200 µL natural tips in stack racks | A current price, pack size or equivalence with the separate RPT family |

Tip-rack routing follows the selected module's actual profile and kind. The
TipOne 200 µL stack-rack proposal uses the USA Scientific reference and a proposed
$30–120 supplier-pack allowance; the OT-2 300 µL profile uses Opentrons and $40–160.
Neither commercial rack exposes a custom fabrication download. The printed-holder
route exposes its own STEP and STL, with $10–150 proposed fabrication plus $20–50
for separately purchased tips. Those bounds are planning scenarios, not researched
vendor quotations; an existing valid supplier/model report retains its own evidence.

Every row has an actionable source or an explicitly labelled supplier search or
fabrication quotation route. These fallback links are not selected SKUs. Software
JSON geometry references remain secondary links, separate from physical purchases.
`selected_product_label` exposes the selected reference alongside the purchase scope.
Unit values are explicitly labelled allocations of the whole group budget; they
are not invented supplier per-piece quotations.

The current tube rack, printed tip rack and plate holder also have direct revision-bound
downloads at `/api/projects/{id}/parts/{component_id}/model.step?revision=N` and
`model.stl`. These export only that canonical custom part using the same CAD builder
as the machine package, without loading the upstream Jubilee assembly. The plate
download contains the custom holder, excluding the reference plate. Custom concept
components retain their existing single-part STEP download links.

These reviewed prices are documentation observations, not live procurement reports.
The default plate purchase scenario uses the manufacturer's listed $282.99 case
of 50 Corning 3596 plates plus a proposed $10–150 holder fabrication allowance,
giving $292.99–432.99 for that scope. It does not divide a case price into an
unavailable single-plate purchase. A retained model estimate keeps its own assumptions.
The refrigerator $900–2,200 and complete custom transfer $300–1,200 ranges are
proposed planning allowances; neither is attributed to a supplier. Their source
references do not replace project geometry. Detailed procurement refresh and
model-estimation behavior remain described in [procurement and instructions](procurement-and-instructions.md).
