"""Recreate intermediate meshes for the pinned Jubilee viewer assets.

Run from the repository root; output is scratch under .local/upstream-cad.
The exact STEP remains the source of CAD export, not these meshes.
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
assembly = import_step(source)
bed = [child for child in assembly.children if child.label == "build_plate_assembly"]
if len(bed) != 1:
    raise ValueError("Expected one original build plate assembly.")
groups = {"bed": bed, "static": [c for c in assembly.children if c.label != "build_plate_assembly"]}
for name, children in groups.items():
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for child in children:
        builder.Add(compound, child.wrapped)
    BRepMesh_IncrementalMesh(compound, 0.8, False, 0.5, True)
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    writer.Write(compound, str(out / f"{name}.stl"))
    raw = np.fromfile(out / f"{name}.stl", dtype=np.uint8, offset=84).reshape(-1, 50)
    vertices = raw[:, 12:48].copy().view("<f4").reshape(-1, 3)
    unique, indices = np.unique(vertices, axis=0, return_inverse=True)
    unique.astype("<f4").tofile(out / f"{name}-vertices.bin")
    indices.astype("<u4").tofile(out / f"{name}-indices.bin")
