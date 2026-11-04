import type { Component, Project } from './types';

/** Use the same assembly as the visible 3D scene. */
export function modelComponents(project: Project): Pick<Component, 'id' | 'label' | 'size'>[] {
  if (project.concept_design) {
    return project.concept_design.components.map(part => ({ id: part.key, label: part.name, size: part.size_mm }));
  }
  if (project.bench_station) {
    return project.bench_station.modules.map(part => ({ id: part.id, label: part.label, size: part.size_mm }));
  }
  return project.design.components;
}
