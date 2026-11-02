"""Numerical checks against the actual pinned renderer-only belt mesh."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_belt_rest_pose_fixed_anchors_and_moving_turns():
    program = r"""
import {readFileSync} from 'node:fs';
import {deformJubileeBelts} from './web/src/beltDeformation.ts';
const file = readFileSync('web/public/assets/jubilee-c877bd2-motion-belts.glb');
const jsonLength = file.readUInt32LE(12);
const json = JSON.parse(file.subarray(20, 20 + jsonLength).toString());
const access = json.accessors[0], view = json.bufferViews[access.bufferView];
const start = 20 + jsonLength + 8 + (view.byteOffset ?? 0) + (access.byteOffset ?? 0);
const source = new Float32Array(access.count * 3);
for (let i = 0; i < source.length; i++) source[i] = file.readFloatLE(start + 4 * i);
const rest = new Float32Array(source.length), moved = new Float32Array(source.length);
deformJubileeBelts(source, rest, 0, 0);
deformJubileeBelts(source, moved, 35, -28);
const near = (a, b) => Math.abs(a - b) < 0.0001;
let fixed = 0, carriage = 0, crossbar = 0;
for (let i = 0; i < source.length; i += 3) {
  const x = source[i], z = source[i+2];
  if (!near(rest[i], x) || !near(rest[i+1], source[i+1]) || !near(rest[i+2], z))
    throw Error('rest pose');
  if (z <= 162.3863 || z >= 707.0862) {
    if (!near(moved[i], x) || !near(moved[i+2], z)) throw Error('fixed turn moved');
    fixed++;
  }
  if ((Math.abs(x - 255.935) < 0.01 || Math.abs(x - 290.635) < 0.01) &&
      z >= 404.78 && z <= 420.99) {
    if (!near(moved[i], x + 35) || !near(moved[i+2], z - 28)) throw Error('carriage end');
    carriage++;
  }
  if ((x < 58.79 || x > 487.78) && z >= 404.78 && z <= 420.99) {
    if (!near(moved[i], x) || !near(moved[i+2], z - 28)) throw Error('crossbar turn');
    crossbar++;
  }
  if (!near(moved[i+1], source[i+1])) throw Error('height changed');
}
if (!(fixed && carriage && crossbar))
  throw Error(`missing mesh samples ${fixed} ${carriage} ${crossbar}`);
// Both parking directions keep the frame turns fixed and translate the crossbar.
for (const dz of [-140, 140]) {
  deformJubileeBelts(source, moved, 0, dz);
  for (let i = 0; i < source.length; i += 3) {
    const z = source[i+2];
    if ((z <= 162.3863 || z >= 707.0862) && !near(moved[i+2], z)) throw Error('parking anchor');
    if (z >= 404.78 && z <= 420.99 && !near(moved[i+2], z + dz)) throw Error('parking turn');
  }
}
// Re-sampling the original data must not accumulate previous movement.
deformJubileeBelts(source, moved, 0, 0);
for (let i = 0; i < source.length; i++) if (!near(moved[i], source[i])) throw Error('reset');
console.log(JSON.stringify({fixed, carriage, crossbar}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", program],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
