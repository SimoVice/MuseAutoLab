# Liquid handling: the first implemented engineering path

[Back to the platform](../platform.md) · [Documentation map](../README.md)

MuseAutoLab's first deeply implemented use case is preparing aliquots and direct
dilutions. It demonstrates how a laboratory task can connect to a sourced machine
choice, editable layout, component selection, assembly guidance and software
planning. These adapters and examples do not define every MuseAutoLab project.

## Start from the process

> I spend a lot of time preparing aliquots and dilutions by hand.
> I want a flexible setup.

The conversation establishes materials, equipment, space and willingness to build
before asking for relevant stock concentrations, targets and preparation volumes.
Missing stock is asked for, rather than invented. Review the preparation plan and
choose a platform before confirming a supported design.

## Two routes, different starting points

| | Jubilee | Opentrons OT-2 |
| --- | --- | --- |
| Starting point | Original, pinned source STEP from Machine Agency | Schematic enclosure and official deck software data |
| Design work | Custom insert/layout, dimension-driven racks, plate holder | Supported labware positions on the deck |
| Deliverables | Source CAD, custom-part files and assembly guidance | Schematic layout, configuration, purchasing and setup guidance |

Jubilee source solids stay unscaled. Its viewer meshes are simplified previews;
the original STEP remains the geometry authority. The OT-2 view is a schematic,
not imported manufacturer fabrication CAD. Jubilee also has a cold-bay concept
and an explicitly requested camera/inspection-arm concept; their interfaces and
engineering performance still need validation.

[Source and adapter details](../source-grounding.md) · [Jubilee CAD provenance](../jubilee-cad-asset.md)

## Revise the supported setup

- **Tube racks:** declare actual tube and supporting-rim dimensions to develop a
  custom rack and fit coupon. Nominal tube volume alone does not establish fit.
  See [dimension-driven parts and build guidance](../procurement-and-instructions.md).
- **Tube-to-plate changes:** replace the sample rack with the named Corning 96 Well
  Plate 360 µL Flat reference, or restore the stored rack, through ordinary chat.
  Existing preparation quantities stay unchanged unless explicitly revised;
  incompatible volume blocks confirmation. The plate uses a pinned Opentrons
  software definition and a separate custom holder, not manufacturer CAD.
  See [plate switching](../microplate-switching.md).
- **Tip-rack choices:** compare the reviewed USA Scientific / TipOne 96 Tip Rack
  200 µL and Opentrons 96 Tip Rack 300 µL profiles. The selected profile changes
  geometry, sources and guides together. Printer access and measured dimensions
  are required before developing a printed holder for purchased tips.
  See [tip-rack alternatives and limits](../tip-rack-options.md).
- **Sourcing and costs:** inspect supported US catalog listings in USD, dated
  observations, planning estimates and unpriced work. A partial subtotal is not a
  complete build cost. See [pricing and instructions](../procurement-and-instructions.md).

Model proposals remain bounded by the implemented adapters and checks. A rejected
change preserves the accepted project; successful changes create a new revision
and invalidate outdated generated files.

## Reuse the design for another recipe

Use the [operating preview](../operating-previews.md) to inspect a supported
Jubilee preparation before building it. The animated sequence follows the
current tube holes or plate wells and selected tip rack. Playback and inspection
remain digital illustrations, with no robot connection or collision validation.

The recorded example starts from synthetic inputs: 5 mg/mL stock, targets of
0.5, 0.25 and 0.05 mg/mL, and 200 µL per preparation. A second recorded recipe keeps
the selected hardware and suppliers while changing targets to 1, 0.2 and 0.1 mg/mL
and preparation volume to 150 µL. These are software examples, not validated
laboratory protocols.

**Software & protocols** explains the selected platform's upstream programming
route. Download a protocol template and standalone local preview to inspect the
logical schedule. The preview does not run a robot or generate a commissioned
control integration. See [software, recipes and remaining programming work](../software-and-protocols.md).

## Open an example or follow the walkthrough

After [starting the app](../getting-started.md), download a JSON file and choose
**Open project**. Recorded projects use synthetic laboratory inputs and can be
inspected without configuring Meta. With a key configured, the app may request a
fresh planning estimate; stored supplier observations remain dated.

- [Plate project with a second recipe](../examples/software-protocol-project.json).
- [Revised project with inspection](../examples/revision-consistency-project.json) and its [consistency check](../revision-consistency.md).
- [12-position tube rack](../examples/parametric-tube-rack-project.json).
- [Confirmed plate project](../examples/microplate-project.json).
- [Tube-rack STEP](../examples/tube-rack/tube-rack.step) and [fit coupon](../examples/tube-rack/tube-rack-fit-coupon.stl).
- [Plate and holder CAD](../examples/microplate/README.md).
- [Conversation walkthrough](../demo-guide.md) and [recorded end-to-end flow](../presentation-flow.md).

## What has and has not been established

Software checks, real model calls, supplier observations and export checks have
separate records in [verification](../verification.md). Neither platform has a
physics or hardware-control adapter. Fit, tool access, mounting, calibration,
liquid handling, thermal performance and complete build cost still require
verification. No measured laboratory time saving is claimed.

Jubilee is by Joshua Vasquez / Machine Agency, used under CC BY 4.0. Official
Opentrons software references retain their own attribution and terms. Consult
[third-party notices](../../THIRD_PARTY_NOTICES.md) before reusing source assets.
