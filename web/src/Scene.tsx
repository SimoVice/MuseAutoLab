import { OrbitControls } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Component as ReactComponent, useEffect, useMemo, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import type { Group } from 'three';
import type { Component, Project } from './types';
import {
  DIP_DOWN_TIME,
  DWELL_TIME,
  RETRACT_TIME,
  TRAVEL_TIME,
  sampleOperationKeyframes,
} from './operation';
import type { OperationKeyframe, OperationSpec, Vec3 } from './operation';

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

const OPERATION_VISIT_ORDER = ['tip-rack', 'source-rack', 'sample-rack', 'tip-waste'] as const;

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
  const camera = useThree((state) => state.camera) as import('three').OrthographicCamera;
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

function ColdStorageBay({ part, center, selected, onSelect }: {
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
  const w = part.size[0] / SCALE;
  const h = part.size[1] / SCALE;
  const d = part.size[2] / SCALE;
  const highlight = selected || hovered;
  const onClick = (event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(part.id); };
  const onOver = (event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); setHovered(true); };
  const onOut = () => setHovered(false);

  // Split the declared envelope so every detail stays inside it:
  // insulated shell below, sample inset + framed translucent lid in the top zone.
  const lidZone = Math.min(0.06, Math.max(0.04, h * 0.08));
  const shellH = Math.max(0.1, h - lidZone);
  const shellCenterY = -h / 2 + shellH / 2;
  const shellTopY = -h / 2 + shellH;
  const insetH = Math.min(0.03, Math.max(0.015, lidZone * 0.45));
  const insetW = w * 0.55;
  const insetD = d * 0.48;
  const insetCenterY = shellTopY + 0.005 + insetH / 2;
  const insetTopY = insetCenterY + insetH / 2;
  const lidThickness = 0.015;
  const lidY = h / 2 - lidThickness / 2 - 0.001;
  const lidW = w * 0.82;
  const lidD = d * 0.76;
  const frameH = 0.03;
  const frameY = h / 2 - frameH / 2 - 0.001;
  const frameBar = 0.04;
  const ventCount = 3;
  const ventW = w * 0.5;
  const ventBaseY = -h / 2 + Math.min(0.18, h * 0.22);
  const wellCount = 3;
  const wellSpacing = Math.min(0.2, insetW / (wellCount + 1));

  return (
    <group name={part.id} position={position}>
      {/* Insulated light shell: fills the declared footprint, shortened for the lid zone. */}
      <mesh position={[0, shellCenterY, 0]} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
        <boxGeometry args={[w, shellH, d]} />
        <meshStandardMaterial
          color={selected ? '#167d84' : '#e6eef0'}
          metalness={0.08}
          roughness={0.6}
          emissive={highlight ? '#0a5f67' : '#000000'}
          emissiveIntensity={selected ? 0.14 : hovered ? 0.06 : 0}
        />
      </mesh>
      {/* Cyan/aluminum sample inset resting on the shell, below the lid. */}
      <mesh position={[0, insetCenterY, 0]} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
        <boxGeometry args={[insetW, insetH, insetD]} />
        <meshStandardMaterial
          color={selected ? '#7fc4cb' : '#a9d6db'}
          metalness={0.55}
          roughness={0.35}
          emissive={highlight ? '#0a5f67' : '#000000'}
          emissiveIntensity={selected ? 0.12 : hovered ? 0.05 : 0}
        />
      </mesh>
      {/* Schematic sample wells; positions only, no liquid or temperature implication. */}
      {Array.from({ length: wellCount }, (_, index) => {
        const x = (index - (wellCount - 1) / 2) * wellSpacing;
        return (
          <mesh key={`cold-well-${index}`} position={[x, insetTopY + 0.001, 0]} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
            <cylinderGeometry args={[0.05, 0.05, 0.008, 16]} />
            <meshStandardMaterial
              color="#2f6f77"
              metalness={0.1}
              roughness={0.5}
              emissive={highlight ? '#0a5f67' : '#000000'}
              emissiveIntensity={selected ? 0.12 : hovered ? 0.05 : 0}
            />
          </mesh>
        );
      })}
      {/* Framed translucent lid: transparent panel plus four frame bars, all flush inside the envelope. */}
      <mesh position={[0, lidY, 0]} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
        <boxGeometry args={[lidW, lidThickness, lidD]} />
        <meshStandardMaterial
          color="#cfeef2"
          metalness={0.05}
          roughness={0.25}
          transparent
          opacity={0.45}
          depthWrite={false}
          emissive={highlight ? '#0a5f67' : '#000000'}
          emissiveIntensity={selected ? 0.1 : hovered ? 0.04 : 0}
        />
      </mesh>
      {[
        { key: 'front', args: [lidW, frameH, frameBar] as [number, number, number], pos: [0, frameY, lidD / 2 - frameBar / 2] as Vec3 },
        { key: 'back', args: [lidW, frameH, frameBar] as [number, number, number], pos: [0, frameY, -lidD / 2 + frameBar / 2] as Vec3 },
        { key: 'left', args: [frameBar, frameH, lidD] as [number, number, number], pos: [-lidW / 2 + frameBar / 2, frameY, 0] as Vec3 },
        { key: 'right', args: [frameBar, frameH, lidD] as [number, number, number], pos: [lidW / 2 - frameBar / 2, frameY, 0] as Vec3 },
      ].map((bar) => (
        <mesh key={`cold-lid-${bar.key}`} position={bar.pos} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
          <boxGeometry args={bar.args} />
          <meshStandardMaterial
            color={selected ? '#167d84' : '#3d545b'}
            metalness={0.2}
            roughness={0.5}
            emissive={highlight ? '#0a5f67' : '#000000'}
            emissiveIntensity={selected ? 0.14 : hovered ? 0.06 : 0}
          />
        </mesh>
      ))}
      {/* Vent details on the front face, recessed inside the declared depth. */}
      {Array.from({ length: ventCount }, (_, index) => {
        const y = ventBaseY + index * 0.08;
        return (
          <mesh key={`cold-vent-${index}`} position={[0, y, d / 2 - 0.011]} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut}>
            <boxGeometry args={[ventW, 0.035, 0.02]} />
            <meshStandardMaterial
              color={selected ? '#1a7f87' : '#5b7379'}
              metalness={0.25}
              roughness={0.6}
              emissive={highlight ? '#0a5f67' : '#000000'}
              emissiveIntensity={selected ? 0.12 : hovered ? 0.05 : 0}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function AnimatedSelectableMesh({ id, kind, selected, onSelect, geometry, offset }: {
  id: string;
  kind: string;
  selected: boolean;
  onSelect: (meshId: string) => void;
  geometry: ReactNode;
  offset: Vec3;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <mesh
      name={id}
      position={offset}
      onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(id); }}
      onPointerOver={(event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {geometry}
      <meshStandardMaterial
        color={selected ? '#167d84' : colors[kind] ?? '#a8bfc0'}
        metalness={['rail', 'column', 'carriage'].includes(kind) ? 0.5 : 0.12}
        roughness={0.5}
        emissive={selected || hovered ? '#0a5f67' : '#000000'}
        emissiveIntensity={selected ? 0.14 : hovered ? 0.06 : 0}
      />
    </mesh>
  );
}

function AnimatedPipetteCarriage({ carriage, pipette, home, keyframes, duration, playing, resetKey, revision, stepCount, onComplete, selectedId, onSelect }: {
  carriage: Component;
  pipette: Component;
  home: Vec3;
  keyframes: OperationKeyframe[];
  duration: number;
  playing: boolean;
  resetKey: number;
  revision: number;
  stepCount: number;
  onComplete: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const groupRef = useRef<Group | null>(null);
  const progressRef = useRef(0);
  const completedRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  const invalidate = useThree((state) => state.invalidate);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  // Reset the schematic progress when the operation is reset or the project revision changes.
  useEffect(() => {
    progressRef.current = 0;
    completedRef.current = false;
    if (groupRef.current) {
      groupRef.current.position.set(home[0], home[1], home[2]);
    }
    invalidate();
    // Cleanup resets the completion guard so a remount never fires a stale callback.
    return () => {
      completedRef.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, revision, stepCount, duration]);

  // Wake the demand render loop only while playing.
  useEffect(() => {
    if (playing && !completedRef.current) {
      invalidate();
    }
    return () => {
      // No leaked loops: animation is driven solely by useFrame.
    };
  }, [playing, invalidate, resetKey, revision]);

  // Zero-step operations complete without motion; assume no liquid animation or physical execution.
  useEffect(() => {
    if (playing && duration <= 0 && !completedRef.current) {
      completedRef.current = true;
      invalidate();
      onCompleteRef.current();
    }
  }, [playing, duration, invalidate, resetKey, revision, stepCount]);

  useFrame((_, delta) => {
    if (!playing) return;
    if (completedRef.current) return;
    if (duration <= 0) return;
    // Cap the frame delta so tab refocus or slow frames cannot jump the schematic.
    const cappedDelta = Math.min(delta, 0.05);
    progressRef.current += cappedDelta;
    const sampled = sampleOperationKeyframes(keyframes, progressRef.current);
    if (groupRef.current) {
      groupRef.current.position.set(sampled[0], sampled[1], sampled[2]);
    }
    // Keep the demand loop alive only while the schematic is playing.
    invalidate();
    if (progressRef.current >= duration) {
      completedRef.current = true;
      onCompleteRef.current();
    }
  });

  const carriageSize: Vec3 = [carriage.size[0] / SCALE, carriage.size[1] / SCALE, carriage.size[2] / SCALE];
  const pipetteDiameter = pipette.size[0] / SCALE;
  const pipetteHeight = pipette.size[1] / SCALE;
  const pipetteOffsetY = (pipette.position[1] - carriage.position[1]) / SCALE;
  const tipHeight = 0.22;

  return (
    <group ref={groupRef} position={home}>
      <AnimatedSelectableMesh
        id={carriage.id}
        kind={carriage.kind}
        selected={selectedId === carriage.id}
        onSelect={onSelect}
        offset={[0, 0, 0]}
        geometry={<boxGeometry args={carriageSize} />}
      />
      <AnimatedSelectableMesh
        id={pipette.id}
        kind={pipette.kind}
        selected={selectedId === pipette.id}
        onSelect={onSelect}
        offset={[0, pipetteOffsetY, 0]}
        geometry={<cylinderGeometry args={[pipetteDiameter / 2, pipetteDiameter / 2, pipetteHeight, 32]} />}
      />
      {/* Restrained schematic disposable tip; illustrative only, not a physical model. */}
      <mesh position={[0, pipetteOffsetY - pipetteHeight / 2 - tipHeight / 2 + 0.03, 0]}>
        <cylinderGeometry args={[0.035, 0.012, tipHeight, 16]} />
        <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
      </mesh>
    </group>
  );
}

function RackDetails({ components, center, stepCount }: {
  components: Component[];
  center: [number, number, number];
  stepCount: number;
}) {
  const details = useMemo(() => {
    const byId = new Map(components.map((part) => [part.id, part]));
    const sourceRack = byId.get('source-rack');
    const sampleRack = byId.get('sample-rack');
    const tipRack = byId.get('tip-rack');
    const tipWaste = byId.get('tip-waste');
    return { sourceRack, sampleRack, tipRack, tipWaste };
  }, [components]);

  const tubeRow = (rack: Component | undefined, count: number, radius: number, height: number, color: string, prefix: string) => {
    if (!rack) return null;
    const safeCount = Math.max(1, Math.min(6, Math.floor(count)));
    const rackCenterX = (rack.position[0] - center[0]) / SCALE;
    const rackCenterZ = (rack.position[2] - center[2]) / SCALE;
    const rackTopY = (rack.position[1] - center[1]) / SCALE + rack.size[1] / SCALE / 2;
    const spacing = Math.min(0.2, (rack.size[0] / SCALE) / (safeCount + 1));
    return (
      <group key={prefix}>
        {Array.from({ length: safeCount }, (_, index) => {
          const x = rackCenterX + (index - (safeCount - 1) / 2) * spacing;
          return (
            <mesh key={`${prefix}-${index}`} position={[x, rackTopY + height / 2 - 0.02, rackCenterZ]}>
              <cylinderGeometry args={[radius, radius, height, 16]} />
              <meshStandardMaterial color={color} metalness={0.05} roughness={0.45} />
            </mesh>
          );
        })}
      </group>
    );
  };

  const tipRow = (rack: Component | undefined) => {
    if (!rack) return null;
    const count = 4;
    const rackCenterX = (rack.position[0] - center[0]) / SCALE;
    const rackCenterZ = (rack.position[2] - center[2]) / SCALE;
    const rackTopY = (rack.position[1] - center[1]) / SCALE + rack.size[1] / SCALE / 2;
    const spacing = Math.min(0.2, (rack.size[0] / SCALE) / (count + 1));
    return (
      <group key="tips">
        {Array.from({ length: count }, (_, index) => {
          const x = rackCenterX + (index - (count - 1) / 2) * spacing;
          return (
            <mesh key={`tip-${index}`} position={[x, rackTopY + 0.06, rackCenterZ]}>
              <cylinderGeometry args={[0.045, 0.016, 0.16, 12]} />
              <meshStandardMaterial color="#ffffff" metalness={0.02} roughness={0.35} />
            </mesh>
          );
        })}
      </group>
    );
  };

  const wasteOpening = details.tipWaste ? (() => {
    const rack = details.tipWaste;
    const x = (rack.position[0] - center[0]) / SCALE;
    const topY = (rack.position[1] - center[1]) / SCALE + rack.size[1] / SCALE / 2;
    const z = (rack.position[2] - center[2]) / SCALE;
    return (
      <mesh key="waste-opening" position={[x, topY + 0.005, z]}>
        <boxGeometry args={[rack.size[0] / SCALE * 0.7, 0.02, rack.size[2] / SCALE * 0.7]} />
        <meshStandardMaterial color="#3d545b" metalness={0.1} roughness={0.7} />
      </mesh>
    );
  })() : null;

  const sampleTubeCount = stepCount > 0 ? Math.min(6, stepCount) : 3;

  return (
    <group>
      {tubeRow(details.sourceRack, 2, 0.06, 0.22, '#2f6f77', 'source-tube')}
      {tubeRow(details.sampleRack, sampleTubeCount, 0.06, 0.22, '#3a8a92', 'sample-tube')}
      {tipRow(details.tipRack)}
      {wasteOpening}
    </group>
  );
}

export default function Scene({ project, selectedId, onSelect, operation }: {
  project: Project;
  selectedId: string | null;
  onSelect: (id: string) => void;
  operation?: OperationSpec;
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

  const byId = useMemo(() => new Map(components.map((part) => [part.id, part])), [components]);
  const carriagePart = byId.get('carriage');
  const pipettePart = byId.get('pipette');
  const showAnimation = Boolean(operation && carriagePart && pipettePart);

  const normalizedStepCount = useMemo(() => {
    if (!operation) return 0;
    return operation.steps.length;
  }, [operation]);

  const animationLayout = useMemo(() => {
    if (!carriagePart || !pipettePart) return null;
    const toCentered = (position: [number, number, number]): Vec3 => [
      (position[0] - bounds.center[0]) / SCALE,
      (position[1] - bounds.center[1]) / SCALE,
      (position[2] - bounds.center[2]) / SCALE,
    ];
    const carriageCentered = toCentered(carriagePart.position as [number, number, number]);
    const home: Vec3 = [carriageCentered[0], carriageCentered[1], carriageCentered[2]];
    const cruiseY = carriageCentered[1] + 0.5;
    // Illustrative approach only: the travel mechanism and clearance are not modeled.
    const dipY = cruiseY - 0.4;

    const stationBaseXZ: Record<string, { x: number; z: number }> = {};
    for (const stationId of OPERATION_VISIT_ORDER) {
      const station = byId.get(stationId);
      if (station) {
        stationBaseXZ[stationId] = {
          x: (station.position[0] - bounds.center[0]) / SCALE,
          z: (station.position[2] - bounds.center[2]) / SCALE,
        };
      } else {
        stationBaseXZ[stationId] = { x: home[0], z: home[2] };
      }
    }

    const sampleRack = byId.get('sample-rack');
    const sampleSpacing = sampleRack ? Math.min(0.2, sampleRack.size[0] / SCALE / (normalizedStepCount + 1)) : 0;

    // Two source positions represent stock and diluent. Each non-zero transfer
    // uses a fresh tip and visits the corresponding destination tube. This is
    // a visual sequence only, not a validated motion or laboratory protocol.
    const keyframes: OperationKeyframe[] = [{ position: [...home] as Vec3, time: 0 }];
    let time = 0;
    for (let targetIndex = 0; targetIndex < normalizedStepCount; targetIndex += 1) {
      const step = operation!.steps[targetIndex];
      const transfers = [step.stock_volume_ul > 0 ? -0.1 : null, step.diluent_volume_ul > 0 ? 0.1 : null];
      for (const sourceOffset of transfers) {
        if (sourceOffset === null) continue;
        for (const stationId of OPERATION_VISIT_ORDER) {
        const base = stationBaseXZ[stationId];
        let x = base.x;
        const z = base.z;
        if (stationId === 'source-rack') x += sourceOffset;
        if (stationId === 'sample-rack') x += (targetIndex - (normalizedStepCount - 1) / 2) * sampleSpacing;
        if (stationId === 'tip-rack') x += ((targetIndex * 2 + (sourceOffset > 0 ? 1 : 0)) % 4 - 1.5) * 0.19;
        time += TRAVEL_TIME;
        keyframes.push({ position: [x, cruiseY, z], time });
        time += DIP_DOWN_TIME;
        keyframes.push({ position: [x, dipY, z], time });
        time += DWELL_TIME;
        keyframes.push({ position: [x, dipY, z], time });
        time += RETRACT_TIME;
        keyframes.push({ position: [x, cruiseY, z], time });
        }
      }
    }
    time += TRAVEL_TIME;
    keyframes.push({ position: [...home] as Vec3, time });
    const duration = keyframes.length > 1 ? keyframes[keyframes.length - 1].time : 0;
    return { home, cruiseY, dipY, keyframes, duration };
  }, [byId, bounds.center, carriagePart, pipettePart, normalizedStepCount, operation?.steps]);

  const staticParts = useMemo(() => {
    if (!showAnimation) return components;
    return components.filter((part) => part.id !== 'carriage' && part.id !== 'pipette');
  }, [components, showAnimation]);

  const coldStoragePart = useMemo(() => staticParts.find((part) => part.id === 'cold-storage'), [staticParts]);
  const genericStaticParts = useMemo(() => staticParts.filter((part) => part.id !== 'cold-storage'), [staticParts]);

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
          {genericStaticParts.map((part) => <MachinePart key={part.id} part={part} center={bounds.center} selected={part.id === selectedId} onSelect={onSelect} />)}
        </group>
        {coldStoragePart ? (
          <ColdStorageBay part={coldStoragePart} center={bounds.center} selected={coldStoragePart.id === selectedId} onSelect={onSelect} />
        ) : null}
        <RackDetails components={components} center={bounds.center} stepCount={normalizedStepCount} />
        {showAnimation && carriagePart && pipettePart && animationLayout && operation ? (
          <AnimatedPipetteCarriage
            carriage={carriagePart}
            pipette={pipettePart}
            home={animationLayout.home}
            keyframes={animationLayout.keyframes}
            duration={animationLayout.duration}
            playing={operation.playing}
            resetKey={operation.resetKey}
            revision={project.revision}
            stepCount={normalizedStepCount}
            onComplete={operation.onComplete}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ) : null}
        <gridHelper args={[18, 36, '#cfdddd', '#dbe7e7']} position={[0, -0.025, 0]} />
        <OrbitControls makeDefault target={target} minZoom={15} maxZoom={200} minPolarAngle={0.08} maxPolarAngle={Math.PI / 2 - 0.04} enablePan={false} />
      </Canvas>
    </SceneBoundary>
    <button className="scene-reset" type="button" onClick={() => setViewKey((value) => value + 1)}>Reset view</button>
    </>
  );
}
