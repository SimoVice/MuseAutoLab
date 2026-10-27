import { OrbitControls } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Component as ReactComponent, useEffect, useMemo, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import type { OrthographicCamera } from 'three';
import type { Component, Project } from './types';

const SCALE = 100;
const colors: Record<string, string> = {
  base: '#b6c5c7',
  rail: '#6c848b',
  column: '#869ca0',
  carriage: '#294b59',
  pipette: '#d7e6e2',
  rack: '#73aaa7',
  tiprack: '#edf5f3',
  waste: '#d7e5e4',
  controller: '#456772',
};

class SceneBoundary extends ReactComponent<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* The accessible component list remains available. */ }
  render() {
    if (this.state.failed) return <div className="scene-fallback">3D view unavailable. Use the component list below to inspect the design.</div>;
    return this.props.children;
  }
}

function FitCamera({ width, height, depth }: { width: number; height: number; depth: number }) {
  const camera = useThree((state) => state.camera) as OrthographicCamera;
  const size = useThree((state) => state.size);
  useEffect(() => {
    const horizontalSpan = (width + depth * 0.58) / SCALE;
    const verticalSpan = (height + depth * 0.48) / SCALE;
    camera.zoom = Math.min(size.width / (horizontalSpan * 1.25), size.height / (verticalSpan * 1.3));
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height, width, height, depth]);
  return null;
}

function MachinePart({ part, center, selected, onSelect }: {
  part: Component;
  center: [number, number, number];
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  const position: [number, number, number] = [
    (part.position[0] - center[0]) / SCALE,
    (part.position[1] - center[1]) / SCALE,
    (part.position[2] - center[2]) / SCALE,
  ];
  const dimensions: [number, number, number] = [part.size[0] / SCALE, part.size[1] / SCALE, part.size[2] / SCALE];
  const onClick = (event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(part.id); };
  return (
    <mesh
      name={part.id}
      position={position}
      onClick={onClick}
      onPointerOver={(event) => { event.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {part.kind === 'pipette' ? (
        <cylinderGeometry args={[dimensions[0] / 2, dimensions[0] / 2, dimensions[1], 32]} />
      ) : <boxGeometry args={dimensions} />}
      <meshStandardMaterial
        color={selected ? '#167d84' : colors[part.kind] ?? '#a8bfc0'}
        metalness={['rail', 'column', 'carriage'].includes(part.kind) ? 0.5 : 0.12}
        roughness={0.5}
        emissive={selected || hovered ? '#0a5f67' : '#000000'}
        emissiveIntensity={selected ? 0.14 : hovered ? 0.06 : 0}
      />
    </mesh>
  );
}

export default function Scene({ project, selectedId, onSelect }: {
  project: Project;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { components, footprint } = project.design;
  const [viewKey, setViewKey] = useState(0);
  const bounds = useMemo(() => {
    if (!components.length) return { center: [0, 0, 0] as [number, number, number], height: 0 };
    const min = [0, 1, 2].map((axis) => Math.min(...components.map((part) => part.position[axis] - part.size[axis] / 2)));
    const max = [0, 1, 2].map((axis) => Math.max(...components.map((part) => part.position[axis] + part.size[axis] / 2)));
    return { center: [(min[0] + max[0]) / 2, min[1], (min[2] + max[2]) / 2] as [number, number, number], height: max[1] - min[1] };
  }, [components]);
  const target: [number, number, number] = [0, bounds.height / SCALE / 2, 0];
  return (
    <>
    <SceneBoundary key={viewKey}>
      <Canvas
        orthographic
        camera={{ position: [10, 9, 12], zoom: 65, near: 0.01, far: 100 }}
        dpr={[1, 1.5]}
        frameloop="demand"
        aria-label="Interactive schematic 3D workstation model. Drag to rotate and scroll to zoom."
      >
        <color attach="background" args={['#eef4f4']} />
        <ambientLight intensity={1.2} />
        <directionalLight position={[8, 12, 7]} intensity={2.1} />
        <directionalLight position={[-6, 5, -5]} intensity={0.7} />
        <FitCamera width={footprint.width_mm} height={footprint.height_mm} depth={footprint.depth_mm} />
        <group>
          {components.map((part) => <MachinePart key={part.id} part={part} center={bounds.center} selected={part.id === selectedId} onSelect={onSelect} />)}
        </group>
        <gridHelper args={[18, 36, '#cfdddd', '#dbe7e7']} position={[0, -0.025, 0]} />
        <OrbitControls makeDefault target={target} minZoom={15} maxZoom={200} minPolarAngle={0.08} maxPolarAngle={Math.PI / 2 - 0.04} enablePan={false} />
      </Canvas>
    </SceneBoundary>
    <button className="scene-reset" type="button" onClick={() => setViewKey((value) => value + 1)}>Reset view</button>
    </>
  );
}
