"""Partition the pinned STEP into rigid preview groups without cutting source geometry.

Run from the repository root, then run prepare_jubilee_motion_glb.mjs for each
output group. These meshes are only a viewer approximation; CAD exports continue
to use the original STEP. Parent locations are applied to every extracted child.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from build123d import import_step
from OCP.BRep import BRep_Builder
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer
from OCP.TopoDS import TopoDS_Compound

from app.upstream_cad import original_step_bytes

out = Path(".local/upstream-cad")
out.mkdir(parents=True, exist_ok=True)
source = out / "jubilee.STEP"
source.write_bytes(original_step_bytes())
print("Importing pinned STEP assembly...", flush=True)
assembly = import_step(source)
print("STEP imported; partitioning source children...", flush=True)
xy = next(c for c in assembly.children if c.label == "jubilee_xy_frame_assembly_Centered_Carriage")
gantry = next(c for c in xy.children if c.label == "crossbar_with_carriage_center")
assert len(xy.children) == 39 and len(gantry.children) == 6
assert xy.children[5].label == "crossbar_with_carriage_center"
assert [xy.children[i].label for i in (14, 15, 16, 27, 28, 31)] == [
    "twist_lock_assembly",
    "carriage_coupling_plate_assembly",
    "carriage_back_plate_assembly",
    "upper_belt_centered",
    "lower_belt_centered",
    "carriage_Spring_Guide_Capture",
]
assert gantry.children[0].label == "crossbar_assembly_Aluminum_Crossbar"
assert gantry.children[1].label == "carriage_center_assembly"
# Keep every original child exactly once. The source's static belt solids remain
# separate because their changing shape is not represented by a rigid transform.
fixed = [
    c
    for c in assembly.children
    if c.label not in ("jubilee_xy_frame_assembly_Centered_Carriage", "build_plate_assembly")
]
fixed += [
    c.moved(xy.location) for i, c in enumerate(xy.children) if i not in (5, 14, 15, 16, 27, 28, 31)
]
crossbar = [
    c.moved(gantry.location).moved(xy.location) for i, c in enumerate(gantry.children) if i != 1
]
carriage = [gantry.children[1].moved(gantry.location).moved(xy.location)]
carriage += [xy.children[i].moved(xy.location) for i in (14, 15, 16, 31)]
belts = [xy.children[i].moved(xy.location) for i in (27, 28)]
groups = {"fixed": fixed, "crossbar": crossbar, "carriage": carriage, "belts": belts}
for name, children in groups.items():
    print(f"Tessellating {name} ({len(children)} child shapes)...", flush=True)
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for child in children:
        builder.Add(compound, child.wrapped)
    BRepMesh_IncrementalMesh(compound, 0.8, False, 0.5, True)
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    writer.Write(compound, str(out / f"motion-{name}.stl"))
    print(f"Indexing {name} mesh...", flush=True)
    raw = np.fromfile(out / f"motion-{name}.stl", dtype=np.uint8, offset=84).reshape(-1, 50)
    vertices = raw[:, 12:48].copy().view("<f4").reshape(-1, 3)
    unique, indices = np.unique(vertices, axis=0, return_inverse=True)
    unique.astype("<f4").tofile(out / f"motion-{name}-vertices.bin")
    indices.astype("<u4").tofile(out / f"motion-{name}-indices.bin")
    print(name, len(children), len(indices) // 3, flush=True)
