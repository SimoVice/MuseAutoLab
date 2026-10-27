// Schematic operation timeline helpers for the dilution workstation preview.
// This module contains only illustrative geometry math. It does not model
// liquid handling, motion feasibility, collision clearance or hardware control.

export type Vec3 = [number, number, number];

export type OperationSpec = {
  playing: boolean;
  steps: { stock_volume_ul: number; diluent_volume_ul: number }[];
  onComplete: () => void;
  resetKey: number;
};

// Per-station segment durations in seconds. Kept short so the preview stays
// illustrative for a small number of direct-dilution targets.
export const TRAVEL_TIME = 0.55;
export const DIP_DOWN_TIME = 0.28;
export const DWELL_TIME = 0.18;
export const RETRACT_TIME = 0.28;

export type OperationKeyframe = {
  position: Vec3;
  time: number;
};

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function smooth(t: number): number {
  const clamped = Math.min(1, Math.max(0, t));
  return clamped * clamped * (3 - 2 * clamped);
}

export function sampleOperationKeyframes(keys: OperationKeyframe[], time: number): Vec3 {
  if (!keys.length) return [0, 0, 0];
  if (time <= keys[0].time) return [...keys[0].position] as Vec3;
  const last = keys[keys.length - 1];
  if (time >= last.time) return [...last.position] as Vec3;
  for (let i = 1; i < keys.length; i += 1) {
    const prev = keys[i - 1];
    const next = keys[i];
    if (time <= next.time) {
      const span = next.time - prev.time;
      const raw = span <= 0 ? 1 : (time - prev.time) / span;
      const eased = smooth(raw);
      return [
        lerp(prev.position[0], next.position[0], eased),
        lerp(prev.position[1], next.position[1], eased),
        lerp(prev.position[2], next.position[2], eased),
      ];
    }
  }
  return [...last.position] as Vec3;
}
