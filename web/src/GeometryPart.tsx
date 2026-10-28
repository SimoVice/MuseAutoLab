import { useEffect, useMemo, useState } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import { BoxGeometry, CylinderGeometry, ExtrudeGeometry, LatheGeometry, Path, Shape, Vector2 } from 'three';
import type { BufferGeometry } from 'three';
import type { Component, GeometryPrimitive } from './types';

const SCALE = 100;
type Vec3 = [number, number, number];

// Appearance roles are illustrative and do not specify construction materials.
const finishes: Record<string, { color: string; metalness: number; roughness: number; opacity?: number }> = {
  deck: { color: '#d2dcda', metalness: 0.45, roughness: 0.48 },
  frame: { color: '#aebfc2', metalness: 0.7, roughness: 0.34 },
  rail: { color: '#8b9fa4', metalness: 0.78, roughness: 0.3 },
  structure: { color: '#9caeb1', metalness: 0.6, roughness: 0.4 },
  motor: { color: '#344b55', metalness: 0.5, roughness: 0.42 },
  holder: { color: '#446471', metalness: 0.5, roughness: 0.4 },
  pipette: { color: '#e6efec', metalness: 0.18, roughness: 0.4 },
  rack: { color: '#76a7a4', metalness: 0.16, roughness: 0.5 },
  'rack-top': { color: '#d7e8e4', metalness: 0.18, roughness: 0.45 },
  waste: { color: '#c9d9d7', metalness: 0.16, roughness: 0.55 },
  controller: { color: '#49656f', metalness: 0.35, roughness: 0.45 },
  panel: { color: '#263f48', metalness: 0.25, roughness: 0.42 },
  vent: { color: '#536e73', metalness: 0.3, roughness: 0.55 },
  cooling: { color: '#e0e9e8', metalness: 0.2, roughness: 0.5 },
  insert: { color: '#91c4c8', metalness: 0.55, roughness: 0.35 },
  lid: { color: '#c5e7e8', metalness: 0.1, roughness: 0.25, opacity: 0.48 },
};

function validPrimitive(p: GeometryPrimitive): boolean {
  if (!p || typeof p.id !== 'string' || typeof p.appearance !== 'string' ||
      !Array.isArray(p.position) || p.position.length !== 3 || !p.position.every(Number.isFinite) ||
      !Array.isArray(p.size) || p.size.length !== 3 || !p.size.every((n) => Number.isFinite(n) && n > 0) ||
      !['box', 'cylinder', 'frustum', 'tube', 'plate'].includes(p.kind) ||
      (p.axis !== undefined && !['x', 'y', 'z'].includes(p.axis))) return false;
  const axis = p.axis ?? 'y';
  const perpendicular = axis === 'x' ? [p.size[1], p.size[2]] : axis === 'z' ? [p.size[0], p.size[1]] : [p.size[0], p.size[2]];
  if (['cylinder', 'frustum', 'tube'].includes(p.kind) && Math.abs(perpendicular[0] - perpendicular[1]) > 0.001) return false;
  const radius = perpendicular[0] / 2;
  if (p.kind === 'frustum' && (![p.radius_top_mm, p.radius_bottom_mm].every((n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= radius) || Math.max(p.radius_top_mm!, p.radius_bottom_mm!) <= 0)) return false;
  if (p.kind === 'tube' && !(typeof p.inner_radius_mm === 'number' && p.inner_radius_mm > 0 && p.inner_radius_mm < radius)) return false;
  if (p.kind === 'plate' && p.holes && (!Array.isArray(p.holes) || !p.holes.every((hole) =>
    Number.isFinite(hole.x_mm) && Number.isFinite(hole.z_mm) && Number.isFinite(hole.radius_mm) && hole.radius_mm > 0 &&
    Math.abs(hole.x_mm) + hole.radius_mm < p.size[0] / 2 && Math.abs(hole.z_mm) + hole.radius_mm < p.size[2] / 2))) return false;
  return true;
}

function makeGeometry(p: GeometryPrimitive): BufferGeometry {
  const [x, y, z] = p.size.map((n) => n / SCALE) as Vec3;
  if (p.kind === 'box') return new BoxGeometry(x, y, z);
  if (p.kind === 'plate') {
    // Shape lies in X/-Z; extrusion is centred and then rotated into the XZ plane.
    const shape = new Shape();
    shape.moveTo(-x / 2, -z / 2);
    shape.lineTo(x / 2, -z / 2);
    shape.lineTo(x / 2, z / 2);
    shape.lineTo(-x / 2, z / 2);
    shape.closePath();
    for (const hole of p.holes ?? []) {
      const path = new Path();
      path.absarc(hole.x_mm / SCALE, -hole.z_mm / SCALE, hole.radius_mm / SCALE, 0, Math.PI * 2, true);
      shape.holes.push(path);
    }
    const geometry = new ExtrudeGeometry(shape, { depth: y, bevelEnabled: false, curveSegments: 24 });
    geometry.translate(0, 0, -y / 2);
    geometry.rotateX(-Math.PI / 2);
    return geometry;
  }
  const axis = p.axis ?? 'y';
  const height = axis === 'x' ? x : axis === 'z' ? z : y;
  const radius = (axis === 'x' ? y : x) / 2;
  let geometry: BufferGeometry;
  if (p.kind === 'tube') {
    const inner = p.inner_radius_mm! / SCALE;
    geometry = new LatheGeometry([
      new Vector2(inner, -height / 2), new Vector2(radius, -height / 2),
      new Vector2(radius, height / 2), new Vector2(inner, height / 2),
      new Vector2(inner, -height / 2),
    ], 32);
  } else {
    const top = p.kind === 'frustum' ? p.radius_top_mm! / SCALE : radius;
    const bottom = p.kind === 'frustum' ? p.radius_bottom_mm! / SCALE : radius;
    geometry = new CylinderGeometry(top, bottom, height, 32);
  }
  if (axis === 'x') geometry.rotateZ(-Math.PI / 2);
  if (axis === 'z') geometry.rotateX(Math.PI / 2);
  return geometry;
}

function PrimitiveMesh({ primitive, selected, hovered }: { primitive: GeometryPrimitive; selected: boolean; hovered: boolean }) {
  const geometry = useMemo(() => makeGeometry(primitive), [primitive]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const finish = finishes[primitive.appearance] ?? { color: '#a8bfc0', metalness: 0.2, roughness: 0.5 };
  return (
    <mesh position={primitive.position.map((n) => n / SCALE) as Vec3} castShadow receiveShadow>
      <primitive object={geometry} attach="geometry" />
      <meshStandardMaterial color={finish.color} metalness={finish.metalness} roughness={finish.roughness}
        transparent={finish.opacity !== undefined} opacity={finish.opacity ?? 1} depthWrite={finish.opacity === undefined}
        emissive={selected || hovered ? '#0a6a71' : '#000000'} emissiveIntensity={selected ? 0.2 : hovered ? 0.09 : 0} />
    </mesh>
  );
}

export default function GeometryPart({ part, position, selected, onSelect }: {
  part: Component; position: Vec3; selected: boolean; onSelect: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  const primitives = part.geometry?.schema_version === '1' && Array.isArray(part.geometry.primitives) &&
    part.geometry.primitives.length > 0 && part.geometry.primitives.every(validPrimitive)
    ? part.geometry.primitives : null;
  const invalidGeometry = part.geometry !== undefined && !primitives;
  useEffect(() => {
    if (invalidGeometry) console.warn(`Invalid shared geometry for component ${part.id}; showing its declared envelope only.`);
  }, [invalidGeometry, part.id]);
  // Saved designs predating the shared geometry are represented only by their declared envelopes.
  const envelope: GeometryPrimitive = {
    id: `${part.id}-envelope`, kind: part.kind === 'pipette' ? 'cylinder' : 'box',
    position: [0, 0, 0], size: part.size, appearance: part.kind,
  };
  return (
    <group name={part.id} position={position}
      onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(part.id); }}
      onPointerOver={(event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}>
      {invalidGeometry ? (
        <mesh>
          <boxGeometry args={part.size.map((n) => n / SCALE) as Vec3} />
          <meshStandardMaterial color="#c2763f" wireframe />
        </mesh>
      ) : (primitives ?? [envelope]).map((primitive) => <PrimitiveMesh key={primitive.id} primitive={primitive} selected={selected} hovered={hovered} />)}
    </group>
  );
}
