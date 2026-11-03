/** Illustrative travel from rest, with optional planned outward pauses. */
export const CONCEPT_MOVE_SECONDS = 4;
export const CONCEPT_STOP_SECONDS = .6;

export function conceptDuration(stops: number[]) {
  return CONCEPT_MOVE_SECONDS + stops.length * CONCEPT_STOP_SECONDS;
}

export function conceptIndexDuration(stops: number[]) {
  return CONCEPT_MOVE_SECONDS / 2 + stops.length * CONCEPT_STOP_SECONDS;
}

function outwardAt(elapsed: number, stops: number[]) {
  let time = elapsed;
  let previous = 0;
  for (let index = 0; index <= stops.length; index++) {
    const stop = index < stops.length ? stops[index] : 1;
    const duration = (stop - previous) * CONCEPT_MOVE_SECONDS / 2;
    if (duration > 0 && time < duration) {
      const t = time / duration;
      return { distance: previous + (stop - previous) * t * t * (3 - 2 * t), remaining: 0 };
    }
    time -= duration;
    if (index < stops.length) {
      if (time < CONCEPT_STOP_SECONDS) return { distance: stop, remaining: 0 };
      time -= CONCEPT_STOP_SECONDS;
    }
    previous = stop;
  }
  return { distance: 1, remaining: time };
}

export function conceptIndexTravelAt(progress: number, stops: number[]) {
  return outwardAt(progress * conceptIndexDuration(stops), stops).distance;
}

export function conceptIndexAngle(start: number, delta: number, progress: number, stops: number[]) {
  return start + delta * conceptIndexTravelAt(progress, stops);
}

export function conceptTravelAt(progress: number, stops: number[]) {
  if (!stops.length) return Math.sin(Math.PI * progress) ** 2;
  const result = outwardAt(progress * conceptDuration(stops), stops);
  if (result.remaining <= 0) return result.distance;
  return (1 + Math.cos(Math.PI * Math.min(result.remaining / (CONCEPT_MOVE_SECONDS / 2), 1))) / 2;
}
