/** Renderer-only deformation of the pinned Jubilee belt tessellation.
 * Source coordinates in mm: belt tips at X 255.935/290.635 are at the carriage;
 * crossbar turns lie at Z 404.786–420.983, fixed end turns at Z <=162.386 or
 * >=707.086. Straight runs interpolate between these measured mesh vertices.
 * This is not belt dynamics, tension, travel-limit or collision verification.
 */
const clamp = (x: number) => Math.max(0, Math.min(1, x));

export function deformJubileeBelts(source: ArrayLike<number>, target: { [index: number]: number }, dx: number, dz: number): void {
  for (let i = 0; i < source.length; i += 3) {
    const x = source[i], y = source[i + 1], z = source[i + 2];
    const crossbarWeight = z < 404.78 ? clamp((z - 162.4) / (404.78 - 162.4))
      : z > 420.99 ? clamp((707.08 - z) / (707.08 - 420.99)) : 1;
    const carriageWeight = Math.min(clamp((x - 58.79) / (255.93 - 58.79)), clamp((487.78 - x) / (487.78 - 290.64)));
    // Only the horizontal crossbar spans are tied to X carriage travel.
    const atCrossbar = z >= 404.78 && z <= 420.99 ? 1 : 0;
    target[i] = x + dx * carriageWeight * atCrossbar;
    target[i + 1] = y;
    target[i + 2] = z + dz * crossbarWeight;
  }
}
