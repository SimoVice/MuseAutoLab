# US pricing and project instructions

MuseAutoLab keeps an accepted design, supplier observations and build guidance
connected to the same project revision. Pricing is a read-only check of reviewed
public US supplier listings, in USD. It does not order parts.

![Actual app, loaded source model and partial US supplier coverage](images/us-pricing-workspace.png)

Recorded project reopened in the real app on 2026-10-30. The capture uses actual
supplier observations: eight of fifteen groups priced, USD 591.86 partial subtotal.
These are dated observations, not guaranteed current prices or a complete quotation.

## Use the product

1. Develop or reopen a supported design. Open **Parts & pricing** below the model.
2. Choose **Refresh US prices**. The app retrieves supported supplier listings,
   verifies their product identity and shows quantity, pack, availability, source
   and observation time. Opening the panel alone does not contact suppliers.
3. Review the partial subtotal and each missing price. Jubilee's original platform
   expands into a reviewed set of non-overlapping candidate kits plus an explicit
   unpriced remainder. Kit contents are not added a second time as loose parts.
4. Open **Build instructions**, or ask in chat how to source and assemble the design.
   Step navigation highlights the relevant component in the model. The guide uses
   the accepted dimensions, positions, selected variants and official references.
5. Download the pricing CSV/JSON and instruction HTML/Markdown/JSON immediately.
   These documents do not require a model call or a heavy CAD export. A full
   confirmed-project package includes the same guide and its bound price report.

## What the numbers mean

The subtotal includes freshly observed, available listed items only. Unknown parts
are not assigned zero cost. The interface separates expired last-known prices and
dated original catalog references from fresh offers. A short 15-minute cache avoids
repeated supplier requests; its original observation timestamps remain visible.
An open tab rechecks the saved report at expiry or when returning to the window,
without automatically querying suppliers. Use **Refresh US prices** for a new
supplier check.

The US market setting specifies source listings and currency. It does not determine
shipping eligibility, destination-specific sales tax, duties or lead time. Those
costs, custom fabrication, assembly, validation and unspecified hardware are excluded.
Coverage counts procurement groups, not every physical part or the percentage of
the complete machine's cost.

Jubilee candidates trace back to the [official BOM navigation](https://jubilee3d.github.io/machines/jubilee_2/bom.html)
and its linked V2.2.2 shopping list. The list is living source material: old prices
are not used as live prices. For example, the current motor kit contains documented
supplier replacements, and a matched left/right mount set is one purchase unit.
Candidate offers retain compatibility notes; they do not change the canonical CAD.
The assembled OT-2 route remains a configuration and quotation checklist, with no
legacy Jubilee motor/frame BOM or fabricated price.

## How instructions are generated

The instruction builder compiles a structured guide from the canonical project,
source bindings and optional current procurement report. It records prerequisites,
part IDs, selected variants, placement, source links, checks and specific engineering
tasks with completion criteria. Original Jubilee assembly uses upstream booklets;
OT-2 setup uses manufacturer installation and calibration instructions. Cooling and
inspection steps appear only when their accepted components exist.

The current guide is a technical review and setup aid. Custom mounting, actuation,
loads, tolerances and hardware validation still require engineering work. **Review
step**, **Follow source guide** and **Design required** distinguish these scopes.
No invented fasteners, tightening values or calibrated operating instructions are
inferred from a schematic. Muse Image is separate presentation artwork and does not
author the technical geometry or this guide.

![Revision-specific insert step, source links and concrete unresolved interface work](images/build-instructions-step.png)

## Continuity and implementation

Reports belong to a runtime project ID and revision, with a separate report ID.
Changing the design invalidates the prior report. Reopening a portable project
rebuilds its geometry under a new runtime ID and requires a new price check. This
prevents old prices from appearing to be newly verified. Reports are process-local;
download them before restarting the server if an observation must be retained.

Only server-owned supplier URLs are fetched. The adapters bound time, response size
and concurrency, reject unexpected redirects and validate exact product identity,
USD currency, variants and pack quantities. Failed or ambiguous pages stay unknown;
there is no unrestricted web crawling or model-generated supplier URL. See
[verification](verification.md) for the actual software, supplier and browser checks.

## Parametric tube rack

The Jubilee sample rack can be replaced through ordinary chat by a rim-supported
one-piece rack. Its top plate and two legs form a single connected solid; tubes hang
from their rim above the deck. Only the sample rack changes. The inspection arm's
geometry/proposal is retained; its derived target plane follows the new rack height.

The required input dimensions are user declarations, not verified measurements:

| Input | Measurement definition |
| --- | --- |
| Maximum body diameter | Widest tube section that must pass through the support hole |
| Minimum support-rim diameter | Smallest diameter at the underside bearing surface; a closed cap diameter is not a substitute |
| Maximum closed-cap envelope | Circular envelope including the rim, closed hinge and protrusions; open-cap motion is not covered |
| Below-rim length | Distance from the underside of the support rim to the lowest tube tip |
| Positions and columns | Explicit rack capacity and arrangement, separate from liquid volume or preparation target count |

Optional explicit requests can constrain centre spacing, radial clearance and
maximum rack width/depth/height. Inputs retain the literal message source. No
vendor SKU, dimension, material performance or print price is inferred from a tube
family or nominal liquid capacity. Invalid requests preserve the accepted project.

Default calculation assumptions are 0.4 mm radial clearance, a **diametral** bore
deviation of ±0.3 mm, at least 0.4 mm of rim bearing at the assumed maximum bore,
4 mm top thickness, 3 mm end walls and 3 mm nominal clearance below the tip. The
CAD bore equals maximum body diameter plus twice the requested radial clearance
plus 0.3 mm. These are first-article design choices, not measured printer capability.

For example, the **synthetic** values 11 mm body, 14 mm rim, 15 mm closed-cap envelope,
40 mm below-rim length, six positions and three columns produce a 55.7 × 43 × 33.9 mm
rack (width × height × depth), 12.1 mm bores and 15.8 mm spacing. These numbers do not
describe any specific commercial 1.5–2 mL tube.

The same accepted revision supplies `cad/tube-rack.step`, `cad/tube-rack.stl`,
`cad/tube-rack-fit-coupon.step` and `cad/tube-rack-fit-coupon.stl`. The rack retains
its upright engineering orientation; in the slicer put the broad top plate down
with both legs pointing upward. The coupon is a flat plate with the identical bore
and top thickness. Check the coupon with the actual tube and printer before the
full part; do not scale the STL to correct a fit. The generated CAD source reproduces
these artifacts from the same specification.

The scoped parts list contains one custom printed rack, while the remaining generic
fixtures are listed separately. PETG is only a proposed dry-fit prototype material;
printer settings, material suitability, cleaning and the cost of fabrication/rework
remain open. The guide's fit steps and acceptance checks are instructions for future
work, not records that those checks have been performed.

The rack rests on the insert in the digital model. Retention, loaded stability,
source-machine attachment, tool travel and liquid handling are separate unresolved
interfaces. Custom-rack operating animation is therefore unavailable. This module
does not establish arbitrary fixture design or an OT-2 labware adapter.
