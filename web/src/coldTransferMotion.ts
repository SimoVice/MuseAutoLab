import type { Component, InspectionFrame, Project } from './types';
import { chooseInspectionPark } from './inspectionPark.ts';
import type { MotionFrame, MotionPlan } from './motionPlan';
import type { Vec3 } from './operation';

/** Extra positions are in the same millimetre coordinate system as the accepted design. */
export type ColdTransferFrame = MotionFrame & {
  payload_position_mm: Vec3;
  jaw_open: number;
  lid_open: number;
  jubilee_park_mm: [number, number];
  inspection_park_ratio: number;
};
export type ColdTransferPlan = MotionPlan & { inspection_park_frame?: InspectionFrame | null };
export type ColdTransferGeometry = {
  payload_component_id: string;
  pickup_mm: Vec3;
  storage_mm: Vec3;
  transfer_height_mm: number;
  checks: { passed: boolean }[];
  components: Component[];
};

const validPoint = (point: unknown): point is Vec3 => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite);
const copy = (point: Vec3): Vec3 => [...point];

/** Jaw positions are illustrative; the closed faces meet the plate envelope. */
export function coldJawOffsetsMm(gripper: Component, plateLength: number, openness: number): [number, number] {
  const left = gripper.geometry?.primitives.find((part) => part.id === 'gripper-jaw-left');
  const right = gripper.geometry?.primitives.find((part) => part.id === 'gripper-jaw-right');
  const opening = Math.max(0, Math.min(1, openness)) * 10;
  return [left ? -plateLength / 2 - (left.position[0] + left.size[0] / 2) - opening : -opening,
    right ? plateLength / 2 - (right.position[0] - right.size[0] / 2) + opening : opening];
}

/** Build a reversible, seekable conceptual sequence; it is not a control program. */
export function compileColdTransferMotion(project: Project, extension: ColdTransferGeometry | null | undefined, plan: MotionPlan): MotionPlan {
  const unavailable = (message: string): MotionPlan => ({ ...plan, status: 'unavailable', message, duration_s: 0, keyframes: [] });
  const inspectionPark = project.inspection_extension ? chooseInspectionPark(project) : null;
  if (project.inspection_extension && !inspectionPark) return unavailable('The inspection arm has no supported clear parking pose for this cold transfer. Revise or remove the inspection concept.');
  const sample = project.design.components.find((part) => part.id === extension?.payload_component_id);
  const plate = project.labware_plate;
  if (!extension || !sample || !plate || plate.target_component_id !== sample.id) return unavailable('Select a compatible 96-well plate and add the refrigerator transfer to preview it.');
  const compatibility = plate.compatibility;
  if (compatibility.blocking_issues.length || !['ready', 'needs_recipe'].includes(compatibility.status)) {
    return unavailable(compatibility.blocking_issues[0] ?? 'Resolve the plate compatibility issue before previewing the transfer.');
  }
  if (!extension.checks.length || extension.checks.some((check) => !check.passed)) return unavailable('Resolve the cold-transfer layout checks before previewing.');
  if (!validPoint(extension.pickup_mm) || !validPoint(extension.storage_mm) || !Number.isFinite(extension.transfer_height_mm) ||
      extension.pickup_mm.some((value, axis) => Math.abs(value - sample.position[axis]) > 0.01) ||
      Math.abs(extension.pickup_mm[2] - extension.storage_mm[2]) > 0.01 ||
      extension.transfer_height_mm <= Math.max(extension.pickup_mm[1], extension.storage_mm[1]) ||
      !sample.geometry?.primitives.some((primitive) => primitive.id === 'reference-plate-wells') ||
      !sample.geometry.primitives.some((primitive) => primitive.id === 'reference-plate-bottom')) return unavailable('The cold-transfer geometry does not match this plate and supported gantry.');
  const components = new Map(extension.components.map((part) => [part.id, part]));
  const shelf = components.get('cold-transfer-shelf'), gantry = components.get('cold-transfer-gantry');
  const cabinet = components.get('cold-transfer-fridge'), carriage = components.get('cold-transfer-carriage');
  const gripper = components.get('cold-transfer-gripper'), lid = components.get('cold-transfer-lid');
  const shaft = components.get('cold-transfer-shaft');
  const jubileeHead = project.design.components.find((part) => part.id === 'carriage');
  const plateParts = sample.geometry.primitives.filter((primitive) => primitive.id.startsWith('reference-plate-'));
  const bottom = Math.min(...plateParts.map((part) => part.position[1] - part.size[1] / 2));
  if (!shelf || !gantry || !cabinet || !carriage || !gripper || !lid || !shaft || !jubileeHead ||
      Math.abs(shelf.position[0] - extension.storage_mm[0]) > 0.01 || Math.abs(shelf.position[2] - extension.storage_mm[2]) > 0.01 ||
      Math.abs(shelf.position[1] + shelf.size[1] / 2 - (extension.storage_mm[1] + bottom)) > 0.01 ||
      plateParts.some((part) => part.size[0] > shelf.size[0] || part.size[2] > shelf.size[2]) ||
      [extension.pickup_mm[0], extension.storage_mm[0]].some((x) => x < gantry.position[0] - gantry.size[0] / 2 || x > gantry.position[0] + gantry.size[0] / 2) ||
      carriage.position[1] - carriage.size[1] / 2 <= gripper.position[1] ||
      Math.abs(gripper.position[1] - (extension.transfer_height_mm + 25)) > 0.01) return unavailable('The cabinet shelf or gantry cannot support this illustrative transfer. Rebuild older cold-transfer concepts.');
  const parkZ = extension.pickup_mm[2] < jubileeHead.position[2] ? 140 : -140;
  if (Math.abs(extension.pickup_mm[2] - (jubileeHead.position[2] + parkZ)) < sample.size[2] / 2 + jubileeHead.size[2] / 2 + 10) return unavailable('The Jubilee carriage cannot clear the plate pickup corridor.');
  const pickup = copy(extension.pickup_mm), storage = copy(extension.storage_mm);
  const highPickup: Vec3 = [pickup[0], extension.transfer_height_mm, pickup[2]];
  const highStorage: Vec3 = [storage[0], extension.transfer_height_mm, storage[2]];
  const frames: ColdTransferFrame[] = [];
  let park: [number, number] = [0, 0];
  let inspectionParkRatio = 0;
  const add = (time_s: number, position_mm: Vec3, payload_position_mm: Vec3, jaw_open: number, lid_open: number, stage: string, target: string) => {
    frames.push({ time_s, position_mm: copy(position_mm), payload_position_mm: copy(payload_position_mm), jaw_open, lid_open, jubilee_park_mm: [...park], inspection_park_ratio: inspectionParkRatio, stage, target, volume_ul: null, tip_attached: false });
  };
  add(0, highPickup, pickup, 1, 0, 'Ready', 'Plate on deck');
  park = [0, parkZ]; inspectionParkRatio = project.inspection_extension ? 1 : 0; add(1.5, highPickup, pickup, 1, 0, project.inspection_extension ? 'Park Jubilee and inspection' : 'Park Jubilee', 'Clear pickup corridor');
  add(2.5, highPickup, pickup, 1, 1, 'Open cabinet', 'Cold cabinet');
  add(4, pickup, pickup, 1, 1, 'Approach', 'Plate on deck');
  add(4.7, pickup, pickup, 0, 1, 'Grip', 'Plate on deck');
  add(6.2, highPickup, highPickup, 0, 1, 'Lift', 'Plate');
  add(8.2, highStorage, highStorage, 0, 1, 'Transfer', 'Cold cabinet');
  add(9.7, storage, storage, 0, 1, 'Place', 'Cabinet shelf');
  add(10.4, storage, storage, 1, 1, 'Release', 'Cabinet shelf');
  add(11.9, highStorage, storage, 1, 1, 'Withdraw', 'Cabinet shelf');
  add(13.9, highPickup, storage, 1, 1, 'Return', 'Home');
  add(14.9, highPickup, storage, 1, 0, 'Close cabinet', 'Cold cabinet');
  park = [0, 0]; inspectionParkRatio = 0; add(16.4, highPickup, storage, 1, 0, project.inspection_extension ? 'Restore Jubilee and inspection' : 'Restore Jubilee', 'Home');
  const referencePlate = compatibility.status === 'needs_recipe';
  return { ...plan, status: 'ready', scope: referencePlate ? 'illustrative' : plan.scope,
    message: referencePlate ? 'Preview the reference plate moving from the deck to the refrigerator shelf.' : 'Cold transfer · conceptual planned motion',
    duration_s: 16.4, keyframes: frames, inspection_park_frame: inspectionPark,
    limitations: ['Illustrative gantry and plate transfer; no robot control, collision or physical validation.', 'Cabinet shelf, gripper fit, mounting, cooling performance and sample stability remain unverified.'] } as ColdTransferPlan;
}

/** Interpolate all articulated properties together, including on seeking and reset. */
export function sampleColdTransfer(plan: MotionPlan, time: number): ColdTransferFrame | null {
  const frames = plan.keyframes as ColdTransferFrame[];
  if (!frames.length || frames.some((frame) => !validPoint(frame.payload_position_mm) || !Number.isFinite(frame.jaw_open) || !Number.isFinite(frame.lid_open) || !Number.isFinite(frame.inspection_park_ratio) || !Array.isArray(frame.jubilee_park_mm) || frame.jubilee_park_mm.length !== 2 || !frame.jubilee_park_mm.every(Number.isFinite))) return null;
  const t = Math.max(0, Math.min(plan.duration_s, Number.isFinite(time) ? time : 0));
  const index = frames.findIndex((frame) => frame.time_s > t);
  if (index < 0) return frames[frames.length - 1];
  if (index === 0) return frames[0];
  const a = frames[index - 1], b = frames[index];
  const raw = (t - a.time_s) / (b.time_s - a.time_s), u = raw * raw * (3 - 2 * raw);
  const lerp = (x: number, y: number) => x + (y - x) * u;
  const point = (x: Vec3, y: Vec3): Vec3 => [lerp(x[0], y[0]), lerp(x[1], y[1]), lerp(x[2], y[2])];
  return { ...b, time_s: t, position_mm: point(a.position_mm, b.position_mm), payload_position_mm: point(a.payload_position_mm, b.payload_position_mm), jaw_open: lerp(a.jaw_open, b.jaw_open), lid_open: lerp(a.lid_open, b.lid_open), jubilee_park_mm: [lerp(a.jubilee_park_mm[0], b.jubilee_park_mm[0]), lerp(a.jubilee_park_mm[1], b.jubilee_park_mm[1])], inspection_park_ratio: lerp(a.inspection_park_ratio, b.inspection_park_ratio) };
}
