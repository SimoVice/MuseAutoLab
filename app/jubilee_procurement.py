"""Reviewed, non-overlapping candidate purchase units from Jubilee's shopping list.

The pinned V2.2.2 project links a living supplier sheet. These source-linked kits
are candidates for review, not a claim that today's kits reproduce the STEP BOM.
No historical sheet prices are used. Kit constituents are never counted twice.
"""

from app.supplier_catalogs import PRODUCTS

BOM_URL = (
    "https://docs.google.com/spreadsheets/d/1pRzBQxVzL9c4T9b1RrKvSjlSwJJhJ7NcbSV6iJUv0X0/edit?gid=0"
)
BOM_INDEX_URL = "https://jubilee3d.github.io/machines/jubilee_2/bom.html"
PROJECT_REVISION = "c877bd2e889560c83da2a68479641a4f7f0d9b83"
CHECKED_ON = "2026-10-30"

_KITS = (
    (
        "jubilee-motor-kit",
        22,
        "LDO Jubilee six-motor kit with cables",
        "One current six-motor kit (2 XY, 3 Z, 1 toolchanger). Storefront SKU changed from "
        "LDOMotSetJub in the shopping list to LDO-MTR-KIT-JUB. The supplier documents "
        "2022 motor substitutions; check torque, shafts, mounting and electronics against "
        "the pinned design. Legacy Pololu motors are not included or reused.",
    ),
    (
        "jubilee-motion-kit",
        27,
        "Gates Jubilee standard belt/idler/pulley kit",
        "One Standard kit: 5 m belt, two drive pulleys, eight toothed idlers and four smooth "
        "idlers. Shoulder bolts are excluded by the supplier. Check the pinned assembly; "
        "do not add the kit's belt/idler/pulley constituents again.",
    ),
    (
        "jubilee-hardware-kit",
        17,
        "Jubilee fastener hardware kit — Full Set",
        "One Full Set, exact variant 32712442904647. Supplier describes support through "
        "V2.2.2. Reconcile its linked sub-list before adding separate fasteners; "
        "the current guide does not verify completeness or physical fit.",
    ),
    (
        "jubilee-crossbar",
        11,
        "Mandala Jubilee aluminum crossbar",
        "One crossbar, storefront SKU JBXBAR, supplier drawing 041-CRS-02-M61-MRW. "
        "Verify drawing/revision and assembly hardware against the pinned STEP before purchase.",
    ),
    (
        "jubilee-xy-mount-set",
        12,
        "Mandala Jubilee matched left/right motor-mount set",
        "One matched pair, storefront SKU JBSM; includes left and right mounts. "
        "The two plates are one purchase unit, not two sets. Verify drawings "
        "021-LMP-02-M61-MRW and 021-RMP-02-M61-MRW; extra mounting hardware remains unresolved.",
    ),
    (
        "jubilee-frame-kit-black",
        38,
        "Jubilee frame extrusion kit — Black candidate",
        "One proposed Black frame kit, exact SKU JubFrameKitBlack and variant 32712440021063. "
        "This is a procurement candidate, not a canonical geometry/color selection. "
        "Purple is a separate alternative with separate stock; review the exact variant, "
        "cuts, tapped holes and assembly against the pinned source. "
        "Remaining rails, plates, electronics, bed and tools remain unpriced.",
    ),
)


def upstream_candidate_groups() -> list[dict]:
    groups = []
    for option_id, source_row, label, note in _KITS:
        product = PRODUCTS[option_id]
        groups.append(
            {
                "id": f"upstream-platform:{option_id}",
                "label": label,
                "quantity": 1,
                "component_ids": ["foundation-jubilee"],
                "selected_id": option_id,
                "parent_group_id": "upstream-platform",
                "is_candidate": True,
                "source_bom_url": BOM_URL,
                "source_bom_row": source_row,
                "source_project_revision": PROJECT_REVISION,
                "options": [
                    {
                        "id": option_id,
                        "label": label,
                        "supplier": product.supplier,
                        "sku": product.sku,
                        "source_url": product.url,
                        "unit_price": None,
                        "checked_on": CHECKED_ON,
                        "price_kind": "unpriced",
                        "compatibility_note": note,
                    }
                ],
            }
        )
    return groups
