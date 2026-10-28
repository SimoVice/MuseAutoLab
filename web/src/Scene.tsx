import { OrbitControls } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Component as ReactComponent, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import type { Group } from 'three';
import type { Component, InspectionExtension, PhysicsFrame, PhysicsView, Project } from './types';
import GeometryPart from './GeometryPart';
import FoundationMesh from './FoundationMesh';
import {
  DIP_DOWN_TIME,
  DWELL_TIME,
  RETRACT_TIME,
  TRAVEL_TIME,
  sampleOperationKeyframes,
} from './operation';
import type { OperationKeyframe, OperationSpec, Vec3 } from './operation';

const SCALE = 100;
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
    camera.zoom = Math.min(size.width / (horizontalSpan * 1.1), size.height / (verticalSpan * 1.05));
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height, width, height, depth]);
  return null;
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

  const pipetteHeight = pipette.size[1] / SCALE;
  const pipetteOffset: Vec3 = [
    (pipette.position[0] - carriage.position[0]) / SCALE,
    (pipette.position[1] - carriage.position[1]) / SCALE,
    (pipette.position[2] - carriage.position[2]) / SCALE,
  ];
  const tipHeight = 0.22;

  return (
    <group ref={groupRef} position={home}>
      <GeometryPart part={carriage} position={[0, 0, 0]} selected={selectedId === carriage.id} onSelect={onSelect} />
      <GeometryPart part={pipette} position={pipetteOffset} selected={selectedId === pipette.id} onSelect={onSelect} />
      {/* Restrained schematic disposable tip; illustrative only, not a physical model. */}
      <mesh position={[pipetteOffset[0], pipetteOffset[1] - pipetteHeight / 2 - tipHeight / 2 + 0.03, pipetteOffset[2]]}
        onClick={(event) => { event.stopPropagation(); onSelect(pipette.id); }}>
        <cylinderGeometry args={[0.035, 0.012, tipHeight, 16]} />
        <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
      </mesh>
    </group>
  );
}

function lerp3(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function sampleInspection(extension: InspectionExtension, time: number): Component[] {
  const frames = extension.pose_frames;
  if (!frames.length) return extension.components;
  const bounded = Math.max(frames[0].time_s, Math.min(frames[frames.length - 1].time_s, Number.isFinite(time) ? time : 0));
  const next = frames.findIndex((frame) => frame.time_s >= bounded);
  if (next <= 0) return frames[0].components;
  const a = frames[next - 1];
  const b = frames[next];
  const t = b.time_s > a.time_s ? (bounded - a.time_s) / (b.time_s - a.time_s) : 0;
  const prior = new Map(a.components.map((part) => [part.id, part]));
  const interpolated = b.components.map((part) => {
    const before = prior.get(part.id);
    if (!before) return part;
    const oldPrimitives = new Map(before.geometry?.primitives.map((p) => [p.id, p]) ?? []);
    return {
      ...part,
      position: lerp3(before.position, part.position, t),
      size: lerp3(before.size, part.size, t),
      geometry: part.geometry && {
        ...part.geometry,
        primitives: part.geometry.primitives.map((primitive) => {
          const old = oldPrimitives.get(primitive.id);
          if (!old) return primitive;
          const start = old.rotation_y_deg ?? 0;
          const end = primitive.rotation_y_deg ?? 0;
          const delta = ((end - start + 540) % 360) - 180;
          return { ...primitive, position: lerp3(old.position, primitive.position, t), rotation_y_deg: start + delta * t };
        }),
      },
    };
  });
  // Interpolate link yaw on the shortest arc, then reconstruct the joints from
  // the fixed link lengths. Independent midpoint interpolation would visibly
  // disconnect the rigid links between keyframes.
  const parts = new Map(interpolated.map((part) => [part.id, part]));
  const shoulder = parts.get('inspection-shoulder');
  const upper = parts.get('inspection-upper-link');
  const elbow = parts.get('inspection-elbow');
  const forearm = parts.get('inspection-forearm');
  const wrist = parts.get('inspection-wrist');
  const camera = parts.get('inspection-camera');
  const cameraMount = parts.get('inspection-camera-mount');
  if (shoulder && upper && elbow && forearm && wrist && camera) {
    const upperAngle = (upper.geometry?.primitives[0]?.rotation_y_deg ?? 0) * Math.PI / 180;
    const lowerAngle = (forearm.geometry?.primitives[0]?.rotation_y_deg ?? 0) * Math.PI / 180;
    const [first, second] = extension.proposal.link_lengths_mm;
    const ex = shoulder.position[0] + first * Math.cos(upperAngle);
    const ez = shoulder.position[2] - first * Math.sin(upperAngle);
    const wx = ex + second * Math.cos(lowerAngle);
    const wz = ez - second * Math.sin(lowerAngle);
    elbow.position = [ex, elbow.position[1], ez];
    wrist.position = [wx, wrist.position[1], wz];
    camera.position = [wx, camera.position[1], wz];
    if (cameraMount) cameraMount.position = [wx, cameraMount.position[1], wz];
    upper.position = [(shoulder.position[0] + ex) / 2, upper.position[1], (shoulder.position[2] + ez) / 2];
    forearm.position = [(ex + wx) / 2, forearm.position[1], (ez + wz) / 2];
  }
  return interpolated;
}

function samplePhysicsFrames(frames: PhysicsFrame[], time: number): PhysicsFrame | null {
  if (!frames.length) return null;
  if (time <= frames[0].time_s) return frames[0];
  const last = frames[frames.length - 1];
  if (time >= last.time_s) return last;
  // Linear scan is fine for <=6500 frames; binary search keeps it lightweight.
  let lo = 0;
  let hi = frames.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].time_s <= time) lo = mid;
    else hi = mid;
  }
  const a = frames[lo];
  const b = frames[hi];
  const span = b.time_s - a.time_s;
  const t = span <= 0 ? 0 : (time - a.time_s) / span;
  return {
    ...b,
    carriage_mm: lerp3(a.carriage_mm, b.carriage_mm, t),
    pipette_mm: lerp3(a.pipette_mm, b.pipette_mm, t),
    tip_mm: lerp3(a.tip_mm, b.tip_mm, t),
    target_mm: lerp3(a.target_mm, b.target_mm, t),
    time_s: time,
  };
}

function PhysicalHead({ carriage, pipette, frame, center, selectedId, onSelect }: {
  carriage: Component;
  pipette: Component;
  frame: PhysicsFrame;
  center: [number, number, number];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const toCentered = (mm: [number, number, number]): Vec3 => [
    (mm[0] - center[0]) / SCALE,
    (mm[1] - center[1]) / SCALE,
    (mm[2] - center[2]) / SCALE,
  ];
  const carriagePos = toCentered(frame.carriage_mm);
  const pipettePos = toCentered(frame.pipette_mm);
  const tipPos = toCentered(frame.tip_mm);
  // tip_mm is the lowest point reported by the engine, not the mesh centre.
  const tipHeight = 0.19;
  const tipOffset: Vec3 = [tipPos[0] - carriagePos[0], tipPos[1] + tipHeight / 2 - carriagePos[1], tipPos[2] - carriagePos[2]];
  const pipetteOffset: Vec3 = [pipettePos[0] - carriagePos[0], pipettePos[1] - carriagePos[1], pipettePos[2] - carriagePos[2]];
  return (
    <group position={carriagePos}>
      <GeometryPart part={carriage} position={[0, 0, 0]} selected={selectedId === carriage.id} onSelect={onSelect} />
      <GeometryPart part={pipette} position={pipetteOffset} selected={selectedId === pipette.id} onSelect={onSelect} />
      <mesh position={tipOffset} onClick={(event) => { event.stopPropagation(); onSelect(pipette.id); }}>
        <cylinderGeometry args={[0.035, 0.035, tipHeight, 16]} />
        <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
      </mesh>
    </group>
  );
}

function RackDetails({ components, center, stepCount, selectedId, onSelect }: {
  components: Component[];
  center: [number, number, number];
  stepCount: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const events = (id: string) => ({
    onClick: (event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(id); },
    onPointerOver: (event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); setHoveredId(id); },
    onPointerOut: () => setHoveredId(null),
  });
  const details = useMemo(() => {
    const byId = new Map(components.map((part) => [part.id, part]));
    const sourceRack = byId.get('source-rack');
    const sampleRack = byId.get('sample-rack');
    const tipRack = byId.get('tip-rack');
    return { sourceRack, sampleRack, tipRack };
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
            <mesh key={`${prefix}-${index}`} position={[x, rackTopY + height / 2 - 0.02, rackCenterZ]} {...events(rack.id)}>
              <cylinderGeometry args={[radius, radius, height, 16]} />
              <meshStandardMaterial color={color} metalness={0.05} roughness={0.45}
                emissive={selectedId === rack.id || hoveredId === rack.id ? '#0a6a71' : '#000000'} emissiveIntensity={selectedId === rack.id ? 0.2 : 0.09} />
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
            <mesh key={`tip-${index}`} position={[x, rackTopY + 0.06, rackCenterZ]} {...events(rack.id)}>
              <cylinderGeometry args={[0.045, 0.016, 0.16, 12]} />
              <meshStandardMaterial color="#ffffff" metalness={0.02} roughness={0.35}
                emissive={selectedId === rack.id || hoveredId === rack.id ? '#0a6a71' : '#000000'} emissiveIntensity={selectedId === rack.id ? 0.2 : 0.09} />
            </mesh>
          );
        })}
      </group>
    );
  };

  const sampleTubeCount = Math.max(1, Math.min(6, stepCount));

  return (
    <group>
      {tubeRow(details.sourceRack, 2, 0.06, 0.22, '#2f6f77', 'source-tube')}
      {tubeRow(details.sampleRack, sampleTubeCount, 0.06, 0.22, '#3a8a92', 'sample-tube')}
      {tipRow(details.tipRack)}
    </group>
  );
}

export default function Scene({ project, selectedId, onSelect, operation, physics, inspectionTime = 0 }: {
  project: Project;
  selectedId: string | null;
  onSelect: (id: string) => void;
  operation?: OperationSpec;
  physics?: PhysicsView | null;
  inspectionTime?: number;
}) {
  const { components: designComponents, footprint } = project.design;
  const extension = project.inspection_extension;
  const physicsActive = Boolean(physics && physics.result.project_id === project.id && physics.result.revision === project.revision && physics.result.frames.length > 0 && designComponents.some((part) => part.id === 'carriage') && designComponents.some((part) => part.id === 'pipette'));
  const components = useMemo(() => {
    if (!extension) return designComponents;
    const displayed = sampleInspection(extension, physicsActive ? 0 : inspectionTime);
    const replacements = new Map(displayed.map((part) => [part.id, part]));
    const existing = new Set(designComponents.map((part) => part.id));
    return [...designComponents.map((part) => replacements.get(part.id) ?? part), ...displayed.filter((part) => !existing.has(part.id))];
  }, [designComponents, extension, inspectionTime, physicsActive]);
  const [viewKey, setViewKey] = useState(0);
  const bounds = useMemo(() => {
    if (!components.length) return { center: [0, 0, 0] as [number, number, number], height: 0 };
    const min = [0, 1, 2].map((axis) => Math.min(...components.map((part) => part.position[axis] - part.size[axis] / 2), extension?.bounds.min_mm[axis] ?? Infinity));
    const max = [0, 1, 2].map((axis) => Math.max(...components.map((part) => part.position[axis] + part.size[axis] / 2), extension?.bounds.max_mm[axis] ?? -Infinity));
    return { center: [(min[0] + max[0]) / 2, min[1], (min[2] + max[2]) / 2] as [number, number, number], width: max[0] - min[0], height: max[1] - min[1], depth: max[2] - min[2] };
  }, [designComponents, extension]);
  const target: [number, number, number] = [0, bounds.height / SCALE / 2, 0];

  const byId = useMemo(() => new Map(components.map((part) => [part.id, part])), [components]);
  const carriagePart = byId.get('carriage');
  const pipettePart = byId.get('pipette');
  const physicsFrame = useMemo(
    () => (physicsActive && physics ? samplePhysicsFrames(physics.result.frames, physics.time_s) : null),
    [physicsActive, physics],
  );
  const showAnimation = Boolean(!physicsActive && operation && carriagePart && pipettePart);

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
    if (!showAnimation && !physicsActive) return components;
    return components.filter((part) => part.id !== 'carriage' && part.id !== 'pipette');
  }, [components, showAnimation, physicsActive]);

  return (
    <>
    <SceneBoundary key={viewKey}>
      <Canvas
        orthographic
        camera={{ position: project.design.foundation ? [5, 10, -15] : [10, 9, 12], zoom: 65, near: 0.01, far: 100 }}
        dpr={[1, 1.5]}
        shadows="percentage"
        frameloop="demand"
        aria-label={physicsActive ? 'MuJoCo state replay in the interactive workstation view.' : 'Interactive schematic 3D workstation model. Drag to rotate and scroll to zoom.'}
      >
        <color attach="background" args={['#eef4f4']} />
        <ambientLight intensity={1.2} />
        <directionalLight position={[8, 12, 7]} intensity={2.1} castShadow shadow-mapSize={[1024, 1024]}
          shadow-camera-left={-10} shadow-camera-right={10} shadow-camera-top={10} shadow-camera-bottom={-10} />
        <directionalLight position={[-6, 5, -5]} intensity={0.7} />
        <FitCamera width={Math.max(footprint.width_mm, bounds.width ?? 0)} height={Math.max(footprint.height_mm, bounds.height)} depth={Math.max(footprint.depth_mm, bounds.depth ?? 0)} />
        <group>
          {staticParts.filter((part) => part.kind !== 'upstream-cad').map((part) => <GeometryPart key={part.id} part={part}
            position={[(part.position[0] - bounds.center[0]) / SCALE, (part.position[1] - bounds.center[1]) / SCALE, (part.position[2] - bounds.center[2]) / SCALE]}
            selected={part.id === selectedId} onSelect={onSelect} />)}
        </group>
        {project.design.foundation && <Suspense fallback={null}>
          <group position={[-bounds.center[0] / SCALE, -bounds.center[1] / SCALE, -bounds.center[2] / SCALE]}>
            <FoundationMesh bedDropMm={project.design.foundation.bed_drop_mm}
              selected={selectedId === 'foundation-jubilee'} onSelect={onSelect} />
          </group>
        </Suspense>}
        <RackDetails components={components} center={bounds.center} stepCount={operation ? normalizedStepCount : project.plan?.steps.length ?? 0} selectedId={selectedId} onSelect={onSelect} />
        {physicsActive && physics && physics.result.obstacles.map((obstacle) => (
          <mesh
            key={obstacle.id}
            position={[
              (obstacle.position_mm[0] - bounds.center[0]) / SCALE,
              (obstacle.position_mm[1] - bounds.center[1]) / SCALE,
              (obstacle.position_mm[2] - bounds.center[2]) / SCALE,
            ]}
          >
            <boxGeometry args={[obstacle.size_mm[0] / SCALE, obstacle.size_mm[1] / SCALE, obstacle.size_mm[2] / SCALE]} />
            <meshStandardMaterial color="#e08a2e" transparent opacity={0.75} roughness={0.5} metalness={0.05} />
          </mesh>
        ))}
        {physicsActive && carriagePart && pipettePart && physicsFrame && (
          <PhysicalHead carriage={carriagePart} pipette={pipettePart} frame={physicsFrame} center={bounds.center} selectedId={selectedId} onSelect={onSelect} />
        )}
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
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.04, 0]} receiveShadow>
          <planeGeometry args={[18, 18]} />
          <meshStandardMaterial color="#eef4f4" roughness={1} />
        </mesh>
        <gridHelper args={[18, 36, '#cfdddd', '#dbe7e7']} position={[0, -0.025, 0]} />
        <OrbitControls makeDefault target={target} minZoom={15} maxZoom={200} minPolarAngle={0.08} maxPolarAngle={Math.PI / 2 - 0.04} enablePan={false} />
      </Canvas>
    </SceneBoundary>
    <button className="scene-reset" type="button" onClick={() => setViewKey((value) => value + 1)}>Reset view</button>
    </>
  );
}
