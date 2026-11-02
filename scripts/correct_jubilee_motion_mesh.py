"""Move disconnected fasteners adjacent to the source gantry into preview groups.

Operates on existing un-simplified pinned STEP tessellations, preserving each
triangle. Geometric association is a preview approximation, not assembly proof.
"""

from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

root = Path(".local/upstream-cad")


def read(name):
    return (
        np.fromfile(root / f"motion-{name}-vertices.bin", "<f4").reshape(-1, 3),
        np.fromfile(root / f"motion-{name}-indices.bin", "<u4").reshape(-1, 3),
    )


verts, faces = read("fixed")
row = np.concatenate([faces[:, 0], faces[:, 1], faces[:, 2]])
col = np.concatenate([faces[:, 1], faces[:, 2], faces[:, 0]])
_, labels = connected_components(
    coo_matrix(
        (np.ones(len(row), dtype=np.int8), (row, col)), shape=(len(verts), len(verts))
    ).tocsr(),
    directed=False,
)
n = labels.max() + 1
low, high = np.full((n, 3), np.inf), np.full((n, 3), -np.inf)
for axis in range(3):
    np.minimum.at(low[:, axis], labels, verts[:, axis])
    np.maximum.at(high[:, axis], labels, verts[:, axis])
# The central components occupy the carriage envelope; the end components
# touch the gantry's two end blocks. Bounds select entire mesh components only.
near = (low[:, 1] > 740) & (low[:, 2] > 395) & (high[:, 2] < 466)
carriage = near & (low[:, 0] > 235) & (high[:, 0] < 311)
crossbar = near & ((high[:, 0] < 75) | (low[:, 0] > 470))
# Assert known pinned tessellation rather than silently classifying a new source.
assert carriage.sum() == 16 and crossbar.sum() == 14, (carriage.sum(), crossbar.sum())
face_labels = labels[faces[:, 0]]
assert np.all(labels[faces] == face_labels[:, None])


def save(name, vertex_array, face_array):
    vertex_array.astype("<f4").tofile(root / f"motion-{name}-vertices.bin")
    face_array.astype("<u4").tofile(root / f"motion-{name}-indices.bin")


save("fixed-corrected", verts, faces[~(carriage[face_labels] | crossbar[face_labels])])
for name, mask in [("carriage", carriage), ("crossbar", crossbar)]:
    old_v, old_f = read(name)
    chosen = faces[mask[face_labels]]
    save(
        name + "-corrected",
        np.concatenate([old_v, verts]),
        np.concatenate([old_f, chosen + len(old_v)]),
    )
print(
    "Reclassified connected components:",
    int(carriage.sum()),
    "carriage,",
    int(crossbar.sum()),
    "crossbar",
)
