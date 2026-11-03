# Reuse the workstation for another pipetting protocol

The hardware proposal and the current preparation recipe are separate. A new
recipe can reuse compatible hardware; a different tool, vessel or working area
may require a design revision. MuseAutoLab currently calculates direct dilutions
and guides upstream protocol programming. It does not run a physical robot.

## Approve and program

Develop the equipment in the hardware workspace, review the selected design and
choose **Approve design & open software**. Approval of the equipment is separate
from defining a recipe. In **Software & protocols**, enter stock concentration,
target concentrations and final volume with units, then choose **Create protocol**.
The resulting transfer table, Python program and operating preview use that
project revision. Return to hardware design to change the equipment; review and
approve it again if the machine changes.

For a supported Jubilee design with no recipe yet, the 3D operating preview
uses a clearly labelled example. Its example values are not saved as the user's
recipe or included in downloads. A partially entered or invalid saved recipe
does not silently become an example. See [operating previews](operating-previews.md).
The bench-station and custom-equipment paths expose their own supported runners
and controls; other processes may stop at a functional specification rather than
an executable program. See [bench station](bench-station.md) and
[custom equipment](custom-equipment.md).

You can also ask in ordinary chat:

> I want to reuse this workstation for aliquoting and other pipetting protocols.
> What software should I use, and how would I program a new protocol? Keep the
> current design and preparation unchanged.

A software-only question should preserve the recipe and hardware. Natural-language
program changes use the configured Meta service and its allowance; entering a
recipe in the form, local calculation and playback do not require a new model
request. Assistant
replies display headings, lists, emphasis, code and ordinary links as Markdown;
raw HTML and embedded images are not rendered. Unsafe link schemes are excluded.
**Reviewing your request** means a request is pending. **Updating design** appears
only while accepted model changes are being applied, followed by **Design
updated**. Advice that changes no design does not claim a design update. These
states do not report a measured completion percentage or physical operation.

## Choose the programming route

| Selected platform | Recommended starting point | Work still needed |
| --- | --- | --- |
| Jubilee | [Science Jubilee getting started](https://science-jubilee.readthedocs.io/en/latest/getting_started/index.html) and [installation](https://science-jubilee.readthedocs.io/en/latest/getting_started/installation.html): Python machine, tool, deck and labware interfaces with example notebooks. | Commission a compatible controller and calibrated tool/deck/labware interfaces. Map the actual source and destination wells, then parameterize and review a separate notebook or script. Provisional component choices do not establish an integrated controller. |
| Opentrons OT-2 | [Python Protocol API tutorial](https://docs.opentrons.com/python-api/tutorial/), or [Protocol Designer](https://docs.opentrons.com/protocol-designer/about/) for supported visual authoring. | Choose the actual robot, pipette, labware definitions and slots; author the protocol, review simulation and App setup, calibrate and check positions. See [robot/instrument selection](https://docs.opentrons.com/protocol-designer/create-protocol/robot-instruments/). |

For a separately authored Opentrons Python protocol, the documented
[simulation command](https://docs.opentrons.com/python-api/reference/execute-simulate/)
is `opentrons_simulate protocol.py`. It does not accept MuseAutoLab's JSON template
or turn the local preview into an executable robot protocol. Source pages were
checked on 2026-10-31; follow their current installation/version requirements.

Aliquoting, transfers and serial dilutions are useful upstream programming tasks.
Support depends on the actual platform, tool, labware and authored protocol;
their mention does not add those workflows to MuseAutoLab's arithmetic engine.

## Download and preview the current recipe

For a ready liquid-handling recipe, choose **Download Python program** in
**Software & protocols**. The self-contained `program.py` contains the selected
platform, project revision and calculated transfers. Run it with Python 3:

```console
python program.py
```

The program prints the transfer schedule and simulates accumulated destination
volumes in memory. Its generation validates the source protocol and arithmetic.
It has no hardware connection or actuator commands. It does not authenticate a
source, calibrate coordinates or verify liquid-handling performance. Physical
source positions, offsets, rates, mixing and tip policy remain parameters to
define. **Protocol data (JSON)** is available separately; the older paired
`protocol-template.json` and `protocol-preview.py` downloads are also available
through the instruction download API for existing workflows.

## Compare two recipes on the same hardware

Starting with the recorded plate example: 5 mg/mL stock, targets of
0.5/0.25/0.05 mg/mL, and 200 µL per preparation:

1. Approve the hardware, enter the recipe, save the project and download its
   Python program. The three
   destinations are A1/B1/C1; stock/diluent amounts are 20/180, 10/190 and 2/198 µL.
2. Ask: **“Keep the stock at 5 mg/mL. Use target concentrations of 1, 0.2 and
   0.1 mg/mL with 150 µL per preparation. Keep the selected platform, plate,
   tip rack, suppliers and layout unchanged.”**
3. Review the new preparation plan and download its new program. The recorded
   second recipe uses stock/diluent amounts of 30/120, 6/144 and 3/147 µL at the
   same A1/B1/C1 wells. Compare the revision and selected hardware, then rerun
   the local program.
4. Use the selected upstream software to author and review a real protocol.
   Commission the actual setup and perform supervised clearance and dispensing
   checks before using samples.

The recipe change is a new project revision; check the actual pipette's range
for every stock and diluent transfer. Save/Open rebuilds the current derived
guide from the preserved project; old pricing observations do not become fresh.

## Verification scope

The feature check passed **48 focused offline tests** and an isolated
real-app browser flow, covering route guidance, second-recipe continuity,
revision-bound downloads, standalone preview validation and preservation of the
saved project while opening the guide. Desktop/mobile browser checks verified
source links, downloads and no document overflow. Meta was not called in those
checks.

The application also completed two actual Muse Spark Contributor calls through
its in-process API path: a software-only inquiry preserved the whole project,
then the second recipe above produced revision 13 while preserving hardware
geometry and suppliers. Calls took 10.750 and 9.219 seconds and consumed 54,933
tokens in total, with no automatic retry. Open the
[recorded second-recipe project](examples/software-protocol-project.json) and
[verification record](examples/software-protocol-verification.json) for the
retained results and scope. The live API calls and isolated browser checks are
separate evidence; neither establishes hardware execution or measured user
performance. See also [delivery verification](verification.md).
