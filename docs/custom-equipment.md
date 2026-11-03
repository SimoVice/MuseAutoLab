# Design and review custom laboratory equipment

[Back to MuseAutoLab](../README.md) · [Platform and scope](platform.md)

Describe what happens to the samples, which items move, the equipment you already
have and the space available. Explain what a successful operation looks like.
MuseAutoLab uses that brief to propose an assembly you can inspect and revise.

## Develop the proposed assembly

Give the purpose and practical constraints first. Add dimensions, sample types,
motion or interfaces when they matter. A critical ambiguity can produce a
clarifying question. A design proposal contains named components, their roles,
original geometry, assembly instructions, checks and an ordered operating
sequence. Request revisions through the same chat.

The compiler validates the proposal before replacing the accepted design. It
keeps component identities, source selections and the generated outputs connected
to one revision. Save the project to retain its brief and reopenable design.
Downloaded concept project data are also included for the local controller.

Drag the interactive model to rotate it, scroll to zoom, or use its rotation
buttons. **Reset view** restores the camera. Select an operation in **Assembly
and operation** to review it; **Play**, **Pause**, **Next step** and **Reset**
control the sequence. **Preview movement**, when available, jumps from a
stationary instruction to the first moving operation.

A component may translate or rotate with its attached children while
the remaining assembly stays fixed. Independent motion steps illustrate an
out-and-back movement from rest. Explicitly linked rotary index operations
continue from the preceding indexed pose and hold the next pose; they do not
return home between those linked operations. Planned pauses mark positions
along the travel. Their timing is
illustrative; sensor readings and process outcomes are not simulated.
Reduced-motion mode provides manual sequence navigation.

## Understand the geometry and sources

The shared concept compiler composes boxes, upright cylinders and spheres in
millimetres. Components can form an attachment hierarchy. Dimension bounds,
parent relationships, workspace width and conservative interference checks
constrain the proposal. Each authored turn is bounded to 180 degrees in either
direction, with an explicit axis and local pivot. Linked index operations can
continue through successive turns.

Under **Working positions**, inspect which instrument axis was checked against
which sample feature and at what point in the motion. Only the positions listed
have passed this geometric check. A sensor still needs calibration and a camera
still needs its field of view and focus tested on the physical setup.

The fitting pass can move a proposed mount or add a visible spacing bracket to
join two parts. Added brackets have their own geometry, parts entries and assembly
checks. Their fasteners, strength and fabrication details require review.

These are original concept solids. The system does not import manufacturer CAD
for this path, infer a complete fastener specification, generate tolerances or
prove structural strength. Intersecting primitives within one component remain
separate mesh shells. STL or OBJ output does not establish printability or
manufacturability. Cables, loads, joints, tool reach, access and process quality
need engineering review and physical checks.

Source links come from the reviewed reference library and supported catalog
candidates. A source identifies a possible product or useful open project; it
does not make the custom geometry a copy of that product or prove compatibility.
The guide links each source by its readable title. Custom parts with no suitable
reference remain explicitly custom. Additional hardware and consumables can
appear in the parts list without a model.

An additional supply without a selected source may show **Search US catalog**.
This opens a search for that item's name. It is a navigation shortcut, not a
reviewed product, a compatibility check or evidence of a current price.

Supplier observations and model planning estimates remain distinct. A missing
price is not a zero cost, and the parts list is not a supplier quotation or a
verified complete bill of materials.

Download **Parts list** or the complete package after checking costs. The CSV
retains available supplier prices, dates and source links alongside separate
model ranges for the listed quantities. Opening the portable project on another
server starts a fresh price check. Keep the CSV when you need the dated record.

## Download one coherent package

Choose **Download project package (ZIP)** in the custom-equipment workspace.
The package contains files from the displayed revision:

- `guide.html`: readable parts, sources, assembly sequence, operating steps and
  software commissioning instructions.
- `parts.csv`: named modeled parts and additional supplies, quantities, sources
  and available local models.
- `machine.stl` and `parts/`: the complete concept mesh and individual part meshes.
- `project.json`: compiled design and revision data for the controller.
- `controller.py`: standalone Python sequence software.
- `gateway-config.json`: a disabled template for an optional device integration.

Individual downloads are also available. Keep the extracted folder structure
together so the guide's relative model and software links work offline. All
model files describe the proposed geometry, not a validated fabrication package.

Editable STEP files are separate downloads for the assembly or an individual
part. They require the optional CAD installation and support at most 200
primitive solids per file. Curves remain curved solids, with named components;
touching or overlapping solids within a component are fused where possible.
This does not add tolerances, joints, material specifications or a fabrication
drawing. STEP files are omitted from the ZIP to keep that package independent
of the optional CAD installation.

To reopen a design in the application, choose **Save project** and retain that
portable project file, then use **Open project**. The ZIP's `project.json` is
compiled controller input; it is not the application's reopenable saved format.

## Add a proposed housing without redesigning the mechanism

Request a rectangular cover or shroud in chat, including any required clearance
or access opening. The optional enclosure operation adds actual side walls and
a roof, with an open bottom and optionally one open side. It reserves the
selected parts' complete proposed travel and includes their attached children.
Walls expand around encountered parts on the same base when necessary, while
the modeled base must support the resulting wall footprints.

The accepted mechanism, operating steps and software remain unchanged. A cover
that cannot fit its existing support is rejected. A repair can propose a smaller
checked clearance only when your stated constraints permit it; numerical
suggestions are checked at 0.5 mm intervals. An explicit minimum is not permission
to reduce that minimum. A different base or freestanding support needs a
separate design decision. Fit checks do not establish load capacity, fastening,
light exclusion, ventilation or material suitability.

## Run the local sequence

Install Python 3.12 or newer. Extract the package, open a terminal in that folder
and run:

```powershell
python controller.py project.json --simulate
```

The standalone controller uses only Python's standard library. It checks the
project identity, revision and sequence bindings, then prints ordered simulated
events. It does not open a device connection. Preview translations, rotations
and local pivots describe the concept; they are not calibrated robot positions.
For indexed rotary operations it records the starting pose, incremental turn,
final pose and optional station identity. These describe the proposed sequence,
not measured index positions or device commands.

## Integrate actual equipment through a gateway

The controller includes a working JSON/HTTP client for a separately implemented
device gateway. This defines an integration protocol; it is not an off-the-shelf
vendor driver. The package supplies neither a connected machine nor a
commissioned gateway server.

An engineer must specify the actual device, implement its gateway and map every
named sequence step to an explicit action and parameters in `gateway-config.json`.
Empty or missing mappings are rejected. Model motion is never automatically
converted into hardware commands. The default address is local,
`http://127.0.0.1:8787`; configure the actual endpoint deliberately.

The gateway accepts JSON POST requests at `/prepare`, `/execute` and `/stop`.
Each request contains its schema version, unique request identity, device
identity, project identity and revision. Execution also carries the mapped
action, parameters and step name. A successful response must match those
identities, report acceptance and acknowledge `ready`, `completed` or `stopped`
for the corresponding endpoint. Unknown actions and stale revisions must be
rejected. The gateway must track request identities to prevent duplicate device
actions. The controller does not retry commands automatically.

After supervised commissioning, mark that review in the configuration. Hardware
mode also requires both command options and the requested typed confirmation:

```powershell
python controller.py project.json --gateway-config gateway-config.json --arm-hardware
```

The client validates acknowledgements, applies request timeouts and attempts a
stop after completion or failure. A communication failure cannot guarantee a
physical stop. Device-side limits, interlocks, a communications watchdog,
independent emergency stop and tested recovery remain necessary parts of the
actual integration. A configuration flag is not evidence that those checks
were performed.

Record the exact hardware, wiring, firmware, calibration and acceptance results.
Complete supervised dry runs and process checks before using samples. Software
tests and gateway acknowledgements do not establish physical performance.

## Keep the evidence in scope

The recorded liquid-handling walkthrough is one example of the general platform,
not a required script for every project. New custom designs still depend on the
shared compiler's supported geometry, sources and checks. A valid concept, an
operating animation, a logical sequence and a real laboratory result must remain
separate claims.
