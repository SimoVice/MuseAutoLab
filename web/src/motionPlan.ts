import type { Component, Project } from './types';
import type { Vec3 } from './operation';
import { compileColdTransferMotion } from './coldTransferMotion.ts';
// Shared illustrative envelopes used by both planning and the viewer.
export const VIRTUAL_TIP_LENGTH_MM = 22;
export const SOURCE_TUBE_MOUTH_ABOVE_RACK_MM = 20;
export const SCHEMATIC_TIP_TOP_ABOVE_RACK_MM = 14;
export const PREVIEW_APPROACH_CLEARANCE_MM = 3;

export type MotionMode = 'preparation' | 'inspection' | 'cold-transfer';
export type MotionFrame = { time_s: number; position_mm: Vec3; stage: string; target: string; volume_ul: number | null; tip_attached: boolean; station_id?: string | null; destination_id?: string | null; tip_slot?: number | null };
export type MotionPlan = { schema_version: 1; project_id: string; revision: number; mode: MotionMode; scope: 'illustrative' | 'recipe'; illustrative_recipe?: { stock: string; target: string; final_volume_ul: number; stock_volume_ul: number; diluent_volume_ul: number }; binding: { adapter_version: string; platform_id: string; foundation_id: string | null; foundation_source_sha256: string | null; plate_profile_id: string | null; tip_profile_id: string | null; rack_spec: Record<string, unknown> | null; component_ids: string[] }; status: 'ready' | 'unavailable'; message: string; duration_s: number; keyframes: MotionFrame[]; limitations: string[] };
const LIMITS = ['Transfer amounts are totals; pipette capacity and repeated aspiration strokes are not modeled.', 'Planned kinematics only; no collision, fluid, calibration or physical validation.', 'Approach heights and timings are illustrative, not robot commands. Source containers and tubes must be open; caps are not operated.', 'Tips are illustrative envelopes; pipette fit is not validated. A labelled manual refill is required when a schematic rack is exhausted.'];
const finite = (point: number[]) => point.length === 3 && point.every(Number.isFinite);
function holes(part: Component): Vec3[] {
  const top = part.geometry?.primitives.find((primitive) => primitive.holes?.length);
  return top?.holes?.map((hole) => [part.position[0] + top.position[0] + hole.x_mm, part.position[1] + top.position[1] + top.size[1] / 2, part.position[2] + top.position[2] + hole.z_mm]) ?? [];
}
export function compileMotionPlan(project: Project, mode: MotionMode = 'preparation'): MotionPlan {
  const plan: MotionPlan = { schema_version: 1, project_id: project.id, revision: project.revision, mode, scope: 'recipe', binding: { adapter_version: 'illustrative-motion-1', platform_id: project.design.platform?.id ?? (project.design.foundation ? 'jubilee' : 'legacy-schematic'), foundation_id: project.design.foundation?.id ?? null, foundation_source_sha256: project.design.foundation?.source_sha256 ?? null, plate_profile_id: project.labware_plate?.profile_id ?? null, tip_profile_id: project.tip_rack?.profile_id ?? null, rack_spec: project.labware_rack?.spec ? { ...project.labware_rack.spec } : null, component_ids: project.design.components.map((part) => part.id) }, status: 'unavailable', message: '', duration_s: 0, keyframes: [], limitations: [...LIMITS] };
  const unavailable = (message: string) => ({ ...plan, message });
  if (!project.engineering_design) return unavailable('Accept a supported design before preparing an operating preview.');
  if (mode === 'cold-transfer') return compileColdTransferMotion(project, project.cold_transfer_extension, plan);
  if (mode === 'inspection') {
    const extension = project.inspection_extension;
    if (!extension || extension.pose_frames.length < 2 || extension.checks.some((check) => !check.passed)) return unavailable('A checked inspection concept with reachable poses is required.');
    if (extension.pose_frames.some((frame, i, frames) => !finite(frame.camera_mm) || !Number.isFinite(frame.time_s) || frame.time_s < 0 || (i > 0 && frame.time_s <= frames[i - 1].time_s))) return unavailable('Inspection poses are incomplete.');
    plan.keyframes = extension.pose_frames.map((frame) => ({ time_s: frame.time_s, position_mm: [...frame.camera_mm], stage: 'Inspect', target: 'Camera sweep', volume_ul: null, tip_attached: false }));
    return { ...plan, status: 'ready', message: 'Inspection concept · canonical pose sequence', duration_s: plan.keyframes.at(-1)!.time_s, limitations: [...extension.limitations, LIMITS[1]] };
  }
  if (project.workflow.kind !== 'liquid_preparation') return unavailable('This workflow has no operating motion adapter. Continue developing the process in chat.');
  const recipeStarted = [project.summary.stock_concentration, project.summary.target_concentrations, project.summary.final_volume].some((value) => Boolean(value?.trim()));
  const illustrative = !recipeStarted && project.plan?.status === 'incomplete';
  if (project.plan?.status !== 'ready' && !illustrative) return unavailable('Complete or correct the preparation quantities to enable this preview.');
  if (illustrative) {
    plan.scope = 'illustrative';
    plan.illustrative_recipe = { stock: '1 mg/mL', target: '0.5 mg/mL', final_volume_ul: 100, stock_volume_ul: 50, diluent_volume_ul: 50 };
  }
  if (project.design.platform?.id && !project.design.foundation) return unavailable('This platform has no operating motion adapter. Its logical recipe remains available under Software & protocols.');
  const parts = new Map(project.design.components.map((part) => [part.id, part]));
  const sample = parts.get('sample-rack'), source = parts.get('source-rack'), tips = parts.get('tip-rack'), waste = parts.get('tip-waste'), pipette = parts.get('pipette'), base = parts.get('base');
  if (!sample || !source || !tips || !waste || !pipette || !base) return unavailable('This design lacks a supported tool or station binding.');
  let targets: Vec3[] = holes(sample);
  let labels = targets.map((_, i) => `Tube ${i + 1}`);
  if (project.labware_plate) {
    const plate = project.labware_plate;
    if (!illustrative && plate.compatibility.status !== 'ready') return unavailable('Resolve plate volume and recipe compatibility before previewing.');
    const wells = new Map(plate.derived.wells.map((well) => [well.label, well]));
    labels = illustrative ? plate.derived.wells.slice(0, 1).map((well) => well.label) : plate.compatibility.occupied_wells;
    targets = labels.map((label) => { const well = wells.get(label); return well ? [sample.position[0] + well.app_x_mm, sample.position[1] + well.app_y_mm, sample.position[2] + well.app_z_mm] : [NaN, NaN, NaN]; });
  }
  const sources = holes(source).map((point) => [point[0], source.position[1] + source.size[1] / 2 + SOURCE_TUBE_MOUTH_ABOVE_RACK_MM + PREVIEW_APPROACH_CLEARANCE_MM, point[2]] as Vec3);
  const tipPositions = holes(tips).map((point) => [point[0], tips.position[1] + tips.size[1] / 2 + SCHEMATIC_TIP_TOP_ABOVE_RACK_MM - VIRTUAL_TIP_LENGTH_MM, point[2]] as Vec3), steps = illustrative ? [] : project.plan!.steps;
  const destinationCount = illustrative ? 1 : steps.length;
  if (!project.labware_plate) targets = targets.map((point) => [point[0], sample.position[1] + sample.size[1] / 2 + (project.labware_rack ? PREVIEW_APPROACH_CLEARANCE_MM : SOURCE_TUBE_MOUTH_ABOVE_RACK_MM + PREVIEW_APPROACH_CLEARANCE_MM), point[2]]);
  if (!destinationCount || destinationCount > 96 || targets.length < destinationCount || sources.length < 2 || !tipPositions.length) return unavailable('The preparation exceeds the current station bindings.');
  if (steps.some((step) => ![step.stock_volume_ul, step.diluent_volume_ul, step.total_volume_ul].every((value) => Number.isFinite(value) && value >= 0) || step.total_volume_ul <= 0 || Math.abs(step.stock_volume_ul + step.diluent_volume_ul - step.total_volume_ul) > 1e-6)) return unavailable('Preparation quantities are incomplete or inconsistent.');
  const points = [...targets.slice(0, destinationCount), ...sources, ...tipPositions];
  if (points.some((point) => !finite(point) || Math.abs(point[0] - base.position[0]) > base.size[0] / 2 || Math.abs(point[2] - base.position[2]) > base.size[2] / 2)) return unavailable('A bound station is outside the supported deck envelope. Revise the layout.');
  const home: Vec3 = [pipette.position[0], pipette.position[1] - pipette.size[1] / 2 - VIRTUAL_TIP_LENGTH_MM, pipette.position[2]];
  const cruise = Math.max(home[1], ...points.map((point) => point[1] + 8), ...[source, sample, tips, waste].map((part) => part.position[1] + part.size[1] / 2 + 10));
  let time = 0, tip = false, tipIndex = 0;
  let stationId: string | null = null, destinationId: string | null = null, tipSlot: number | null = null;
  const add = (position_mm: Vec3, stage: string, target: string, volume_ul: number | null, seconds: number) => { time = Math.round((time + seconds) * 1000) / 1000; plan.keyframes.push({ time_s: time, position_mm: [...position_mm], stage, target, volume_ul, tip_attached: tip, station_id: stationId, destination_id: destinationId, tip_slot: tipSlot }); };
  add(home, 'Ready', 'Home', null, 0);
  add([home[0], cruise, home[2]], 'Lift', 'Home', null, 0.45);
  const visit = (point: Vec3, stage: string, target: string, volume: number | null, tipAfter: boolean, station: string) => {
    stationId = station;
    add([point[0], cruise, point[2]], 'Travel', target, volume, 0.65);
    add(point, 'Approach', target, volume, 0.35);
    tip = tipAfter; add(point, stage, target, volume, 0.35);
    add([point[0], cruise, point[2]], 'Retract', target, volume, 0.35);
  };
  for (let i = 0; i < destinationCount; i += 1) {
    destinationId = project.labware_plate ? labels[i] : `tube-${i + 1}`;
    const volumes = illustrative ? [plan.illustrative_recipe!.stock_volume_ul, plan.illustrative_recipe!.diluent_volume_ul] : [steps[i].stock_volume_ul, steps[i].diluent_volume_ul];
    for (const [sourceIndex, volume] of volumes.entries()) {
      if (volume === 0) continue;
      if (tipIndex > 0 && tipIndex % tipPositions.length === 0) {
        stationId = 'tip-rack'; tipSlot = null;
        add([tips.position[0], cruise, tips.position[2]], 'Manual refill', 'Refill tip rack before continuing', null, 1.5);
      }
      tipSlot = tipIndex++ % tipPositions.length;
      visit(tipPositions[tipSlot], 'Pick up tip', 'Tip rack · illustrative pickup', null, true, 'tip-rack');
      tipSlot = null;
      visit(sources[sourceIndex], 'Aspirate', sourceIndex === 0 ? 'Stock' : 'Diluent', volume, true, 'source-rack');
      visit(targets[i], 'Dispense', illustrative ? `${labels[i]} · example ${plan.illustrative_recipe!.target}` : `${labels[i]} · ${steps[i].target}`, volume, true, 'sample-rack');
      visit([waste.position[0], waste.position[1] + waste.size[1] / 2 + 5, waste.position[2]], 'Discard tip', 'Tip waste', null, false, 'tip-waste');
    }
  }
  stationId = null; destinationId = null;
  add([home[0], cruise, home[2]], 'Return home', 'Home', null, 0.65);
  add(home, 'Complete', 'Home', null, 0.45);
  if (project.design.foundation) {
    const drop = project.design.foundation.bed_drop_mm;
    if (!Number.isFinite(drop) || plan.keyframes.some((frame) => {
      const proposedDrop = drop + frame.position_mm[1] - home[1];
      return proposedDrop < 0 || proposedDrop > 150;
    })) return unavailable('The approach exceeds the illustrative Jubilee bed-pose envelope (0-150 mm). Revise the bed pose or station heights.');
  }
  return { ...plan, status: 'ready', message: illustrative ? 'Illustrative example only · planned kinematics with example quantities. These values are not saved.' : 'Preparation · planned kinematics', duration_s: time };
}
export function sampleMotionPlan(plan: MotionPlan, time: number): MotionFrame {
  const frames = plan.keyframes;
  if (!frames.length) return { time_s: 0, position_mm: [0, 0, 0], stage: 'Unavailable', target: '', volume_ul: null, tip_attached: false };
  const t = Number.isFinite(time) ? Math.max(0, Math.min(plan.duration_s, time)) : 0;
  if (t <= frames[0].time_s) return { ...frames[0], position_mm: [...frames[0].position_mm] };
  if (t >= frames[frames.length - 1].time_s) return { ...frames[frames.length - 1], position_mm: [...frames[frames.length - 1].position_mm] };
  const nextIndex = frames.findIndex((frame) => frame.time_s > t);
  const a = frames[Math.max(0, nextIndex - 1)], b = frames[nextIndex];
  const ratio = Math.max(0, Math.min(1, (t - a.time_s) / (b.time_s - a.time_s)));
  const blend = ratio * ratio * (3 - 2 * ratio);
  return { ...b, tip_attached: a.tip_attached, time_s: t, position_mm: a.position_mm.map((value, axis) => value + (b.position_mm[axis] - value) * blend) as Vec3 };
}

/** Rack state is derived from the timeline, so reset and seeking are deterministic. */
export function availableTipSlots(plan: MotionPlan, time: number, count: number): boolean[] {
  const available = Array.from({ length: count }, () => true);
  const t = Number.isFinite(time) ? time : 0;
  for (const frame of plan.keyframes) {
    if (frame.time_s > t) break;
    if (frame.stage === 'Manual refill') available.fill(true);
    if (frame.stage === 'Pick up tip' && frame.tip_slot != null && frame.tip_slot >= 0 && frame.tip_slot < count) available[frame.tip_slot] = false;
  }
  return available;
}
