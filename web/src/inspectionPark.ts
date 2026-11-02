import type { Component, InspectionFrame, Project } from './types';

type Box = { min: number[]; max: number[] };
type Point = [number, number];
const radians = (value: number) => value * Math.PI / 180;
const degrees = (value: number) => value * 180 / Math.PI;
const shortest = (a: number, b: number) => ((b - a + 540) % 360) - 180;
const byId = (parts: Component[], id: string) => parts.find((part) => part.id === id);
const box = (center: number[], size: number[], margin = 0): Box => ({
  min: center.map((value, axis) => value - size[axis] / 2 - margin),
  max: center.map((value, axis) => value + size[axis] / 2 + margin),
});
const union = (boxes: Box[]): Box => ({ min: [0, 1, 2].map((i) => Math.min(...boxes.map((b) => b.min[i]))), max: [0, 1, 2].map((i) => Math.max(...boxes.map((b) => b.max[i]))) });
const segmentHits = (a: Point, b: Point, obstacle: Box, radius: number): boolean => {
  let lo = 0, hi = 1;
  for (const [axis, coordinate] of [[0, 0], [2, 1]] as const) {
    const v = b[coordinate] - a[coordinate], min = obstacle.min[axis] - radius, max = obstacle.max[axis] + radius;
    if (Math.abs(v) < 1e-9) { if (a[coordinate] < min || a[coordinate] > max) return false; continue; }
    const t0 = (min - a[coordinate]) / v, t1 = (max - a[coordinate]) / v;
    lo = Math.max(lo, Math.min(t0, t1)); hi = Math.min(hi, Math.max(t0, t1));
    if (lo > hi) return false;
  }
  return true;
};
const angles = (frame: InspectionFrame): [number, number] | null => {
  const upper = byId(frame.components, 'inspection-upper-link')?.geometry?.primitives[0]?.rotation_y_deg;
  const fore = byId(frame.components, 'inspection-forearm')?.geometry?.primitives[0]?.rotation_y_deg;
  return Number.isFinite(upper) && Number.isFinite(fore) ? [upper!, fore!] : null;
};

/** Canonical branch matches the source compiler's leftmost-elbow selection. */
function solve(start: Point, target: Point, lengths: [number, number]): { elbow: Point; q1: number; q2: number } | null {
  const [l1, l2] = lengths, dx = target[0] - start[0], dz = target[1] - start[1];
  const d = Math.hypot(dx, dz);
  if (d < 1e-9 || d > l1 + l2 || d < Math.abs(l1 - l2)) return null;
  const q = Math.acos(Math.max(-1, Math.min(1, (d * d - l1 * l1 - l2 * l2) / (2 * l1 * l2))));
  return [q, -q].map((q2) => {
    const q1 = Math.atan2(dz, dx) - Math.atan2(l2 * Math.sin(q2), l1 + l2 * Math.cos(q2));
    return { elbow: [start[0] + l1 * Math.cos(q1), start[1] + l1 * Math.sin(q1)] as Point, q1, q2 };
  }).sort((a, b) => a.elbow[0] - b.elbow[0])[0];
}

/** Return a checked illustrative park pose, or null when the available geometry is insufficient. */
export function chooseInspectionPark(project: Project): InspectionFrame | null {
  const inspection = project.inspection_extension, cold = project.cold_transfer_extension;
  const sample = project.design.components.find((part) => part.id === cold?.payload_component_id);
  if (!inspection || !cold || !sample?.geometry || !inspection.pose_frames.length || !inspection.checks.length || inspection.checks.some((check) => !check.passed) || !cold.checks.length || cold.checks.some((check) => !check.passed)) return null;
  const first = inspection.pose_frames[0], parts = first.components;
  const shoulder = byId(parts, 'inspection-shoulder'), upper = byId(parts, 'inspection-upper-link'), elbow = byId(parts, 'inspection-elbow');
  const fore = byId(parts, 'inspection-forearm'), wrist = byId(parts, 'inspection-wrist'), camera = byId(parts, 'inspection-camera'), neck = byId(parts, 'inspection-camera-mount');
  const gripper = byId(cold.components, 'cold-transfer-gripper'), shaft = byId(cold.components, 'cold-transfer-shaft'), carriage = byId(cold.components, 'cold-transfer-carriage');
  const lengths = inspection.proposal.link_lengths_mm, initialAngles = inspection.pose_frames.map(angles);
  if (!shoulder || !upper || !elbow || !fore || !wrist || !camera || !neck || !gripper || !shaft || !carriage ||
      lengths.length !== 2 || lengths.some((v) => !Number.isFinite(v) || v <= 0) || initialAngles.some((v) => !v) ||
      [...cold.pickup_mm, ...cold.storage_mm, cold.transfer_height_mm].some((v) => !Number.isFinite(v))) return null;
  const valid = (part: Component) => [...part.position, ...part.size].every(Number.isFinite) && part.size.every((v) => v > 0);
  if (![shoulder, upper, elbow, fore, wrist, camera, neck, gripper, shaft, carriage].every(valid)) return null;
  const validPrimitive = (p: NonNullable<Component['geometry']>['primitives'][number]) =>
    p.position.length === 3 && p.size.length === 3 && [...p.position, ...p.size].every(Number.isFinite) && p.size.every((v) => v > 0) && Number.isFinite(p.rotation_y_deg ?? 0);
  const containedGeometry = (part: Component) => Boolean(part.geometry?.primitives.length) && part.geometry!.primitives.every((p) => {
    if (!validPrimitive(p)) return false;
    const yaw = radians(p.rotation_y_deg ?? 0), c = Math.abs(Math.cos(yaw)), s = Math.abs(Math.sin(yaw));
    const extents = [c * p.size[0] + s * p.size[2], p.size[1], s * p.size[0] + c * p.size[2]];
    return extents.every((size, i) => Math.abs(p.position[i]) + size / 2 <= part.size[i] / 2 + 0.01);
  });
  if (![shoulder, elbow, wrist, camera, neck].every(containedGeometry)) return null;
  for (const [link, length] of [[upper, lengths[0]], [fore, lengths[1]]] as Array<[Component, number]>) {
    const p = link.geometry?.primitives[0];
    if (!p || !validPrimitive(p) || p.kind !== 'box' || Math.abs(p.size[0] - length) > 0.01 || p.position.some((n) => Math.abs(n) > 0.01)) return null;
  }
  const gripPrimitives = gripper.geometry?.primitives, plateLength = project.labware_plate?.profile.source_dimensions_mm[0];
  if (!gripPrimitives?.length || !['gripper-bridge', 'gripper-jaw-left', 'gripper-jaw-right'].every((id) => gripPrimitives.some((p) => p.id === id)) ||
      !Number.isFinite(plateLength) || plateLength! <= 0 || Math.abs(shaft.size[0] - 11) > 0.01 || Math.abs(shaft.size[2] - 11) > 0.01 ||
      [0, 2].some((i) => Math.abs(gripper.position[i] - cold.pickup_mm[i]) > 0.01 || Math.abs(carriage.position[i] - cold.pickup_mm[i]) > 0.01)) return null;
  for (const p of gripPrimitives) {
    if (!validPrimitive(p) || Math.abs(p.rotation_y_deg ?? 0) > 0.01) return null;
    const closed = p.id === 'gripper-jaw-left' ? -plateLength! / 2 - (p.position[0] + p.size[0] / 2)
      : p.id === 'gripper-jaw-right' ? plateLength! / 2 - (p.position[0] - p.size[0] / 2) : 0;
    const opened = closed + (p.id === 'gripper-jaw-left' ? -10 : p.id === 'gripper-jaw-right' ? 10 : 0);
    if (Math.max(Math.abs(p.position[0] + closed), Math.abs(p.position[0] + opened)) + p.size[0] / 2 > gripper.size[0] / 2 + 0.01 ||
        [1, 2].some((i) => Math.abs(p.position[i]) + p.size[i] / 2 > gripper.size[i] / 2 + 0.01)) return null;
  }
  const plate = sample.geometry.primitives.filter((p) => p.id.startsWith('reference-plate-'));
  if (!plate.length || !plate.every((p) => validPrimitive(p) && Math.abs(p.rotation_y_deg ?? 0) < 0.01)) return null;
  const plateAt = (point: number[]) => union(plate.map((p) => box(p.position.map((n, i) => n + point[i]), p.size, 5)));
  const pickupPlate = plateAt(cold.pickup_mm), storedPlate = plateAt(cold.storage_mm);
  // Declared gripper envelope contains its open jaws; the shaft extends to the carriage.
  const overheadGrip = box(gripper.position, gripper.size, 5);
  const bridge = gripPrimitives.find((p) => p.id === 'gripper-bridge')!;
  const shaftTop = carriage.position[1] - carriage.size[1] / 2;
  const shaftBottom = gripper.position[1] + bridge.position[1] + bridge.size[1] / 2;
  if (shaftTop <= shaftBottom) return null;
  const overheadShaft = box([cold.pickup_mm[0], (shaftTop + shaftBottom) / 2, cold.pickup_mm[2]], [shaft.size[0], shaftTop - shaftBottom, shaft.size[2]], 5);
  const sweepObstacles = [pickupPlate, storedPlate, overheadGrip, overheadShaft];
  const lowGrip = [...gripper.position]; lowGrip[1] += Math.min(cold.pickup_mm[1], cold.storage_mm[1]) - cold.transfer_height_mm;
  const shiftedGrip = [...gripper.position]; shiftedGrip[0] += cold.storage_mm[0] - cold.pickup_mm[0];
  const shiftedLow = [...lowGrip]; shiftedLow[0] = shiftedGrip[0];
  const corridor = union([pickupPlate, storedPlate, overheadGrip, overheadShaft, box(lowGrip, gripper.size, 5), box(shiftedGrip, gripper.size, 5), box(shiftedLow, gripper.size, 5), box(carriage.position, carriage.size, 5), box([cold.storage_mm[0], carriage.position[1], cold.storage_mm[2]], carriage.size, 5)]);
  const x0 = shoulder.position[0], z0 = shoulder.position[2];
  const l1 = lengths[0], l2 = lengths[1];
  const radius = (part: Component) => Math.hypot(part.size[0], part.size[2]) / 2;
  const beamRadius = (part: Component) => (part.geometry?.primitives[0]?.size[2] ?? Infinity) / 2;
  const intersects = (a: number, b: number, obstacle: Box, margin: number): boolean => {
    const ax = x0 + l1 * Math.cos(radians(a)), az = z0 - l1 * Math.sin(radians(a));
    const wx = ax + l2 * Math.cos(radians(b)), wz = az - l2 * Math.sin(radians(b));
    const check = (part: Component, p: Point, q: Point, r: number) => part.position[1] + part.size[1] / 2 >= obstacle.min[1] && part.position[1] - part.size[1] / 2 <= obstacle.max[1] && segmentHits(p, q, obstacle, r + margin);
    return check(upper, [x0, z0], [ax, az], beamRadius(upper)) || check(elbow, [ax, az], [ax, az], radius(elbow)) ||
      check(fore, [ax, az], [wx, wz], beamRadius(fore)) || check(wrist, [wx, wz], [wx, wz], radius(wrist)) ||
      check(camera, [wx, wz], [wx, wz], radius(camera)) || check(neck, [wx, wz], [wx, wz], radius(neck));
  };
  const bounds = cold.assembly_bounds;
  if (!bounds || ![...bounds.min_mm, ...bounds.max_mm].every(Number.isFinite) || bounds.min_mm.some((value, i) => value >= bounds.max_mm[i])) return null;
  const workspaceWidth = project.summary.workspace_width_mm;
  if (workspaceWidth != null && (!Number.isFinite(workspaceWidth) || bounds.max_mm[0] - bounds.min_mm[0] > workspaceWidth + 1e-6)) return null;
  const withinBounds = (a: number, b: number, margin: number): boolean => {
    const ax = x0 + l1 * Math.cos(radians(a)), az = z0 - l1 * Math.sin(radians(a));
    const wx = ax + l2 * Math.cos(radians(b)), wz = az - l2 * Math.sin(radians(b));
    const contains = (part: Component, p: Point, q: Point, r: number, extra = margin) =>
      Math.min(p[0], q[0]) - r - extra >= bounds.min_mm[0] && Math.max(p[0], q[0]) + r + extra <= bounds.max_mm[0] &&
      part.position[1] - part.size[1] / 2 >= bounds.min_mm[1] && part.position[1] + part.size[1] / 2 <= bounds.max_mm[1] &&
      Math.min(p[1], q[1]) - r - extra >= bounds.min_mm[2] && Math.max(p[1], q[1]) + r + extra <= bounds.max_mm[2];
    return contains(shoulder, [x0, z0], [x0, z0], radius(shoulder), 0) &&
      contains(upper, [x0, z0], [ax, az], beamRadius(upper)) && contains(elbow, [ax, az], [ax, az], radius(elbow)) &&
      contains(fore, [ax, az], [wx, wz], beamRadius(fore)) && contains(wrist, [wx, wz], [wx, wz], radius(wrist)) &&
      contains(camera, [wx, wz], [wx, wz], radius(camera)) && contains(neck, [wx, wz], [wx, wz], radius(neck));
  };
  const sourceAngles = initialAngles as [number, number][];
  // The viewer reconstructs links from yaw and length. Reject malformed frames
  // whose canonical joints, heights, envelope dimensions or rigid links differ.
  const close = (a: number, b: number) => Number.isFinite(a) && Math.abs(a - b) < 0.01;
  for (let i = 0; i < inspection.pose_frames.length; i++) {
    const frame = inspection.pose_frames[i], current = new Map(frame.components.map((part) => [part.id, part]));
    const [a, b] = sourceAngles[i];
    const ex = x0 + l1 * Math.cos(radians(a)), ez = z0 - l1 * Math.sin(radians(a));
    const wx = ex + l2 * Math.cos(radians(b)), wz = ez - l2 * Math.sin(radians(b));
    for (const base of [shoulder, upper, elbow, fore, wrist, camera, neck]) {
      const part = current.get(base.id);
      if (!part || !valid(part) || !close(part.position[1], base.position[1]) || !close(part.size[1], base.size[1])) return null;
      if (part.id !== upper.id && part.id !== fore.id && (!close(part.size[0], base.size[0]) || !close(part.size[2], base.size[2]))) return null;
    }
    for (const [id, x, z] of [[shoulder.id, x0, z0], [upper.id, (x0 + ex) / 2, (z0 + ez) / 2], [elbow.id, ex, ez], [fore.id, (ex + wx) / 2, (ez + wz) / 2], [wrist.id, wx, wz], [camera.id, wx, wz], [neck.id, wx, wz]] as Array<[string, number, number]>) {
      const part = current.get(id)!;
      if (!close(part.position[0], x) || !close(part.position[2], z)) return null;
    }
    for (const [id, length, baseline] of [[upper.id, l1, upper], [fore.id, l2, fore]] as Array<[string, number, Component]>) {
      const primitive = current.get(id)?.geometry?.primitives[0], reference = baseline.geometry?.primitives[0];
      if (!primitive || !reference || !close(primitive.size[0], length) || !close(primitive.size[1], reference.size[1]) || !close(primitive.size[2], reference.size[2])) return null;
    }
  }
  const shoulderPoint: Point = [x0, z0];
  const offsets = [120, -120, 170, -170, 220, -220, 280, -280, 340, -340];
  for (const dz of offsets) for (const dx of [0, -80, 80, -160, 160]) {
    const target: Point = [cold.pickup_mm[0] + dx, cold.pickup_mm[2] + dz];
    const solved = solve(shoulderPoint, target, lengths);
    if (!solved) continue;
    const park: [number, number] = [-degrees(solved.q1), -degrees(solved.q1 + solved.q2)];
    if (intersects(park[0], park[1], corridor, 5) || !withinBounds(park[0], park[1], 5)) continue;
    let safe = true;
    // Check every possible starting pose from the supported inspection sweeps and
    // every shortest-angle park/unpark path. Inflate each obstacle by a bound on
    // the maximum unsampled endpoint displacement, not merely sampled points.
    const n = 32;
    for (let k = 0; k < sourceAngles.length && safe; k++) {
      const a = sourceAngles[k], b = sourceAngles[Math.min(k + 1, sourceAngles.length - 1)];
      const da = shortest(a[0], b[0]), db = shortest(a[1], b[1]);
      const margin = (l1 * radians(Math.abs(da) + 180) + l2 * radians(Math.abs(db) + 180)) / (2 * n) + 5;
      for (let i = 0; i <= n && safe; i++) {
        const start: [number, number] = [a[0] + da * i / n, a[1] + db * i / n];
        const p = shortest(start[0], park[0]), q = shortest(start[1], park[1]);
        // Reject paths near a shortest-arc discontinuity, including between samples.
        if (Math.abs(p) + Math.abs(da) / n >= 179.99 || Math.abs(q) + Math.abs(db) / n >= 179.99) { safe = false; break; }
        for (let j = 0; j <= n && safe; j++) {
          const firstAngle = start[0] + p * j / n, secondAngle = start[1] + q * j / n;
          if (!withinBounds(firstAngle, secondAngle, margin)) { safe = false; break; }
          for (const obstacle of sweepObstacles) if (intersects(firstAngle, secondAngle, obstacle, margin)) { safe = false; break; }
        }
      }
    }
    if (!safe) continue;
    const result: InspectionFrame = structuredClone(first);
    const resultParts = new Map(result.components.map((part) => [part.id, part]));
    const setPosition = (id: string, x: number, z: number) => { const part = resultParts.get(id)!; part.position[0] = x; part.position[2] = z; };
    setPosition('inspection-elbow', solved.elbow[0], solved.elbow[1]);
    for (const id of ['inspection-wrist', 'inspection-camera', 'inspection-camera-mount']) setPosition(id, target[0], target[1]);
    for (const [id, from, to, angle, length] of [
      ['inspection-upper-link', shoulderPoint, solved.elbow, park[0], l1], ['inspection-forearm', solved.elbow, target, park[1], l2],
    ] as Array<[string, Point, Point, number, number]>) {
      const part = resultParts.get(id)!; part.position[0] = (from[0] + to[0]) / 2; part.position[2] = (from[1] + to[1]) / 2;
      const primitive = part.geometry!.primitives[0]; primitive.rotation_y_deg = angle;
      const c = Math.abs(Math.cos(radians(angle))), s = Math.abs(Math.sin(radians(angle))), width = primitive.size[2];
      part.size[0] = c * length + s * width; part.size[2] = s * length + c * width;
    }
    result.camera_mm = [target[0], camera.position[1], target[1]];
    result.target_mm = [target[0], first.target_mm[1], target[1]];
    result.joint_angles_deg = { shoulder: degrees(solved.q1), elbow: degrees(solved.q2) };
    return result;
  }
  return null;
}
