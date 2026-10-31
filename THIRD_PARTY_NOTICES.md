# Third-party geometry and source references

MuseAutoLab includes original Jubilee hardware CAD by **Joshua Vasquez / Machine
Agency, University of Washington**, under the **Creative Commons Attribution 4.0
International license (CC BY 4.0)**. This geometry has its own license; do not infer
that MuseAutoLab owns it or that a software license overrides it.

- Upstream project: https://github.com/machineagency/jubilee
- Pinned revision: `c877bd2e889560c83da2a68479641a4f7f0d9b83`
- Original file: `frame/cads/STEP/jubilee.STEP`
- Source: https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/frame/cads/STEP/jubilee.STEP
- License notice: https://github.com/machineagency/jubilee/blob/c877bd2e889560c83da2a68479641a4f7f0d9b83/license.txt
- License terms: https://creativecommons.org/licenses/by/4.0/
- Original STEP SHA-256: `533417712183775a544802ae29a6f94d50ef0839bc2f24f68bce7a048798afea`

The repository stores this file losslessly compressed as
`app/assets/jubilee-c877bd2.step.gz`, with adjacent attribution and provenance.
The viewer's two GLB files are simplified tessellations of its fixed parts and
original build-plate subassembly. The app reorients the assembly into its
coordinate system, proposes a vertical pose for that subassembly and adds
separate custom parts. It does not rescale source geometry. These modifications
do not establish physical travel, compatible interfaces or working hardware.
Exports include the original compressed source, notice, provenance and assembly
transformation. Preserve attribution, license link and modification notices when
redistributing the source or derived geometry. No upstream endorsement is claimed.

Science Jubilee is cited as a separately licensed integration reference; no
Science Jubilee driver or tool CAD is included. Manufacturer dimensions from
Pololu, Raspberry Pi and Opentrons are documented nominal envelopes, not
redistributed vendor CAD. Their exact scopes, dates, URLs and unresolved interfaces
are in `app/data/design-references-2026-10-28.json` and each project's source bindings.

## Opentrons software deck definition

`app/data/ot2/deck.json` is an unmodified software deck definition from the
Opentrons project, under Apache License 2.0. Its adjacent `LICENSE.txt` preserves
the upstream license; `provenance.json` records retrieval, scope and raw hash.

- Repository: https://github.com/Opentrons/opentrons
- Revision: `95a8a37922cfd5f46ad26c983bcc1659fa13b6e1`
- Path: `shared-data/deck/definitions/3/ot2_standard.json`
- Source: https://github.com/Opentrons/opentrons/blob/95a8a37922cfd5f46ad26c983bcc1659fa13b6e1/shared-data/deck/definitions/3/ot2_standard.json
- License: https://github.com/Opentrons/opentrons/blob/95a8a37922cfd5f46ad26c983bcc1659fa13b6e1/LICENSE
- Raw SHA-256: `f9bde02d43314e42c64d12f1a0d6d4f4aceb448371d37def27de76ff8a308e90`

This is software slot data, not manufacturer machine CAD. MuseAutoLab translates
the slot coordinates into its schematic view, adds custom proxies and uses
separately documented manufacturer enclosure dimensions. Absolute deck pose,
internal mechanisms and labware fit are unverified. No Opentrons control code is
installed and no endorsement or compatibility certification is claimed. Exported
commercial packages retain the deck definition, license and provenance.

## Opentrons software microplate definition

`app/data/labware/corning_96_wellplate_360ul_flat.json` is an unmodified definition
from the same Opentrons revision `95a8a37922cfd5f46ad26c983bcc1659fa13b6e1`, under
Apache License 2.0. The adjacent `LICENSE.txt` and `provenance.json` retain its
license, source URL, retrieval date and raw SHA-256:
`c13f112e52893e781c59ced9e6418ff10a5e2cc4b4877fd9559045f2f475558d`.

[Original definition](https://github.com/Opentrons/opentrons/blob/95a8a37922cfd5f46ad26c983bcc1659fa13b6e1/shared-data/labware/definitions/2/corning_96_wellplate_360ul_flat/1.json).
MuseAutoLab derives schematic plate primitives and adds its own separate holder.
The original definition is not edited. It is software reference data, not
manufacturer CAD, a verified exact commercial SKU, working-volume validation or
endorsement. Plate exports include the definition, provenance and license.

## Opentrons software tip-rack definitions

`app/data/tipracks/` contains two unmodified definitions from the same pinned
Opentrons revision `95a8a37922cfd5f46ad26c983bcc1659fa13b6e1`, under Apache License
2.0. The adjacent `LICENSE.txt` and `provenance.json` retain the licence, URLs,
consultation date and raw hashes. The definitions identify products by USA
Scientific / TipOne and Opentrons; these names do not imply endorsement.

- `tipone_96_tiprack_200ul.json`: `c077e81c6539d40a7c936ea8729aa0e4442240e8980551fc6ae82c662312b31a`
- `opentrons_96_tiprack_300ul.json`: `b2f4fc74c370dfd31d0de6f320ac5c09d6098d02feef51f58091db24718c402c`

MuseAutoLab derives schematic envelopes and opening positions from these software
references. The shallow recess and illustrative finish are application choices,
not manufacturer construction details. The commercial references are not offered
as standalone fabrication parts. Source data does not establish current stock,
exact purchase variant, price, pipette compatibility, deck fixation or physical
fit. Commercial-reference exports retain the selected source, licence and
provenance. The separate custom holder uses user-declared dimensions.

## Multimodal demonstration media

`docs/images/multimodal-reference.png` is an actual view of the attributed Jubilee
foundation and MuseAutoLab custom concepts. `multimodal-illustration.png` is a Meta
Muse Image result generated from that view on 2026-10-30. Original Jubilee design:
Joshua Vasquez / Machine Agency, pinned revision and CC BY 4.0 attribution above.
The generated presentation image changes some mechanical details and is not CAD,
a technical assembly drawing or evidence of a built machine.

## Supplier catalog facts and assembly references

The application links primary Pololu, Adafruit, Filastruder, Mandala Rose Works,
Jubilee and Opentrons pages for factual price, variant, source and instruction
references. It does not redistribute complete supplier pages or upstream booklets.
Supplier names and product identifiers identify their owners' products; inclusion
does not imply endorsement, reserved inventory or certified compatibility. Jubilee
candidate kits reference the living upstream V2.2.2 shopping sheet and retain the
pinned source-CAD attribution above. Generated guides identify their source owners,
licenses, checked dates and the limits of custom adaptations.
