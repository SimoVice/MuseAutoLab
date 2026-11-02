"""Compare the rigid preview partitions with the original static tessellation.

Both sides use the same pinned STEP and meshing parameters. This geometric
comparison is not a collision or motion feasibility test.
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(".local/upstream-cad")


def stats(paths):
    minimum = np.full(3, np.inf)
    maximum = np.full(3, -np.inf)
    volume = area = 0.0
    count = 0
    for path in paths:
        raw = np.fromfile(path, dtype=np.uint8, offset=84).reshape(-1, 50)
        for start in range(0, len(raw), 100000):
            v = (
                raw[start : start + 100000, 12:48]
                .copy()
                .view("<f4")
                .reshape(-1, 3, 3)
                .astype("float64")
            )
            minimum = np.minimum(minimum, v.min(axis=(0, 1)))
            maximum = np.maximum(maximum, v.max(axis=(0, 1)))
            volume += np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6
            area += np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum() / 2
            count += len(v)
    return {
        "triangle_count": count,
        "min_mm": minimum.tolist(),
        "max_mm": maximum.tolist(),
        "signed_volume_mm3": volume,
        "surface_area_mm2": area,
    }


original = stats([ROOT / "static.stl"])
partitioned = stats(
    [ROOT / f"motion-{name}.stl" for name in ("fixed", "crossbar", "carriage", "belts")]
)
result = {"original": original, "partitioned": partitioned}
print(json.dumps(result, indent=2))
(ROOT / "motion-partition-check.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
assert np.allclose(original["min_mm"], partitioned["min_mm"], atol=0.01, rtol=0)
assert np.allclose(original["max_mm"], partitioned["max_mm"], atol=0.01, rtol=0)
assert np.isclose(
    original["signed_volume_mm3"], partitioned["signed_volume_mm3"], rtol=1e-5, atol=1
)
assert np.isclose(original["surface_area_mm2"], partitioned["surface_area_mm2"], rtol=1e-5, atol=1)
