import { OrbitControls } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Component as ReactComponent, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode, RefObject } from 'react';
import { DoubleSide, PMREMGenerator, Spherical, Vector3 } from 'three';
import type { Group, Mesh, OrthographicCamera } from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { Component, InspectionExtension, LabwarePlate, LabwareRack, PhysicsFrame, PhysicsView, Project } from './types';
import GeometryPart from './GeometryPart';
import ColdTransferScene from './ColdTransferScene';
import { sampleColdTransfer } from './coldTransferMotion';
import type { ColdTransferPlan } from './coldTransferMotion';
import FoundationMesh from './FoundationMesh';
import './scene-controls.css';
import {
  DIP_DOWN_TIME,
  DWELL_TIME,
  RETRACT_TIME,
  TRAVEL_TIME,
  sampleOperationKeyframes,
} from './operation';
import type { OperationKeyframe, OperationSpec, Vec3 } from './operation';
import { availableTipSlots, sampleMotionPlan, SOURCE_TUBE_MOUTH_ABOVE_RACK_MM, SCHEMATIC_TIP_TOP_ABOVE_RACK_MM, VIRTUAL_TIP_LENGTH_MM } from './motionPlan';
import type { MotionFrame, MotionPlan } from './motionPlan';

const SCALE = 100;
const OPERATION_VISIT_ORDER = ['tip-rack', 'source-rack', 'sample-rack', 'tip-waste'] as const;
const BED_PART_IDS = new Set(['base', 'source-rack', 'sample-rack', 'tip-rack', 'tip-waste', 'controller']);
const WORKING_AREA_IDS = ['base', 'carriage', 'pipette', 'source-rack', 'sample-rack', 'tip-rack', 'tip-waste', 'controller'];

// A local studio environment supplies soft reflections without network assets.
function StudioEnvironment() {
  const { gl, scene, invalidate } = useThree();
  useEffect(() => {
    const generator = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const texture = generator.fromScene(room, 0.04);
    const previous = scene.environment;
    const previousIntensity = scene.environmentIntensity;
    scene.environment = texture.texture;
    scene.environmentIntensity = 0.45;
    invalidate();
    return () => {
      scene.environment = previous;
      scene.environmentIntensity = previousIntensity;
      texture.dispose();
      room.dispose();
      generator.dispose();
    };
  }, [gl, scene, invalidate]);
  return null;
}

class SceneBoundary extends ReactComponent<{ children: ReactNode; onError: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { this.props.onError(); }
  render() {
    if (this.state.failed) return <div className="scene-fallback">3D view unavailable. Use the component list below to inspect the design.</div>;
    return this.props.children;
  }
}

function FitCamera({ width, height, depth, enabled }: { width: number; height: number; depth: number; enabled: boolean }) {
  const camera = useThree((state) => state.camera) as import('three').OrthographicCamera;
  const size = useThree((state) => state.size);
  useEffect(() => {
    if (!enabled) return;
    const horizontalSpan = (width + depth * 0.58) / SCALE;
    const verticalSpan = (height + depth * 0.48) / SCALE;
    // Short embedded viewers need extra vertical margin for the oblique projection.
    const compactness = Math.min(1, Math.max(0, (460 - size.height) / 60));
    const verticalPadding = 1.05 + compactness * 0.23;
    camera.zoom = Math.min(size.width / (horizontalSpan * 1.1), size.height / (verticalSpan * verticalPadding));
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height, width, height, depth, enabled]);
  return null;
}

type CameraAction = 'left' | 'right' | 'up' | 'down' | 'in' | 'out';

function SceneTools({ captureRef, actionRef, sourceReady, sourceRequired }: {
  captureRef?: RefObject<(() => Promise<string>) | null>;
  actionRef: RefObject<((action: CameraAction) => void) | null>;
  sourceReady: RefObject<boolean>;
  sourceRequired: boolean;
}) {
  const { gl, scene, camera, invalidate } = useThree();
  const controls = useThree((state) => state.controls) as { target: Vector3; update: () => void } | null;
  useEffect(() => {
    if (!controls) return;
    actionRef.current = (action) => {
      if (action === 'in' || action === 'out') {
        const orthographic = camera as OrthographicCamera;
        orthographic.zoom = Math.max(15, Math.min(700, orthographic.zoom * (action === 'in' ? 1.2 : 1 / 1.2)));
        orthographic.updateProjectionMatrix();
      } else {
        const spherical = new Spherical().setFromVector3(camera.position.clone().sub(controls.target));
        if (action === 'left') spherical.theta -= Math.PI / 18;
        if (action === 'right') spherical.theta += Math.PI / 18;
        if (action === 'up') spherical.phi -= Math.PI / 18;
        if (action === 'down') spherical.phi += Math.PI / 18;
        spherical.phi = Math.max(0.08, Math.min(Math.PI / 2 - 0.04, spherical.phi));
        camera.position.copy(controls.target).add(new Vector3().setFromSpherical(spherical));
      }
      controls.update();
      invalidate();
    };
    return () => { actionRef.current = null; };
  }, [actionRef, camera, controls, invalidate]);
  useEffect(() => {
    if (!captureRef) return;
    captureRef.current = async () => {
      if (sourceRequired && !sourceReady.current) throw new Error('The source model is still loading.');
      if (gl.getContext().isContextLost()) throw new Error('The 3D view is unavailable.');
      // Render immediately before reading the buffer, without retaining it between frames.
      gl.render(scene, camera);
      const source = gl.domElement;
      if (!source.width || !source.height) throw new Error('The 3D view is not ready.');
      const scale = Math.min(1, 2048 / Math.max(source.width, source.height));
      const output = document.createElement('canvas');
      output.width = Math.max(1, Math.round(source.width * scale));
      output.height = Math.max(1, Math.round(source.height * scale));
      const context = output.getContext('2d');
      if (!context) throw new Error('The 3D view could not be captured.');
      context.drawImage(source, 0, 0, output.width, output.height);
      return output.toDataURL('image/png');
    };
    return () => { captureRef.current = null; };
  }, [captureRef, gl, scene, camera, sourceReady, sourceRequired]);
  return null;
}

function SourceState({ ready, onChange }: { ready: boolean; onChange: (ready: boolean) => void }) {
  useEffect(() => { onChange(ready); }, [ready, onChange]);
  return null;
}

// Labels use the same camera projection as the scene without nested React roots.
function PlateAxisLabel({ position, label }: { position: Vec3; label: string }) {
  const group = useRef<Group>(null);
  const { gl, camera, size, events, invalidate } = useThree();
  const point = useMemo(() => new Vector3(), []);
  const [element] = useState(() => {
    const span = document.createElement('span');
    span.className = 'microplate-axis-label';
    span.style.position = 'absolute';
    span.style.left = '0';
    span.style.top = '0';
    span.style.pointerEvents = 'none';
    span.style.zIndex = '100';
    return span;
  });
  useEffect(() => {
    element.textContent = label;
    const target = events.connected || gl.domElement.parentElement;
    target?.appendChild(element);
    invalidate();
    return () => { element.remove(); };
  }, [element, label, events.connected, gl, invalidate]);
  useFrame(() => {
    if (!group.current) return;
    group.current.getWorldPosition(point).project(camera);
    const x = (point.x + 1) * size.width / 2;
    const y = (1 - point.y) * size.height / 2;
    element.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
  });
  return <group ref={group} position={position} />;
}

type FocusRequest = { position: Vec3; size: Vec3; direction?: Vec3 };
type Isolation = FocusRequest & { id: string; ids: string[]; mode: 'part' | 'work' | 'arm' };

// Move only in response to an explicit inspection request; orbiting remains manual afterwards.
function FocusCamera({ request, focusKey }: { request: FocusRequest | null; focusKey?: string | null }) {
  const camera = useThree((state) => state.camera) as OrthographicCamera;
  const controls = useThree((state) => state.controls) as { target: Vector3; update: () => void; addEventListener: (type: 'start', callback: () => void) => void; removeEventListener: (type: 'start', callback: () => void) => void } | null;
  const viewport = useThree((state) => state.size);
  const invalidate = useThree((state) => state.invalidate);
  const transition = useRef<{ fromPosition: Vector3; toPosition: Vector3; fromTarget: Vector3; toTarget: Vector3; fromZoom: number; toZoom: number; elapsed: number } | null>(null);
  const previousFocusKey = useRef<string | null>(null);
  useEffect(() => {
    if (!request || !controls) {
      previousFocusKey.current = null;
      return;
    }
    const target = new Vector3(...request.position);
    const direction = focusKey && focusKey === previousFocusKey.current
      ? camera.position.clone().sub(controls.target).normalize()
      : new Vector3(...(request.direction ?? [0.45, 1, -1])).normalize();
    previousFocusKey.current = focusKey ?? null;
    const distance = Math.max(4, Math.max(...request.size) * 3);
    const [width, height, depth] = request.size;
    const horizontal = Math.max(0.15, width * 0.91 + depth * 0.41);
    const vertical = Math.max(0.15, width * 0.28 + height * 0.74 + depth * 0.61);
    const zoom = Math.min(700, Math.max(15, Math.min(viewport.width * 0.78 / horizontal, viewport.height * 0.72 / vertical)));
    const toPosition = target.clone().addScaledVector(direction, distance);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      transition.current = null;
      camera.position.copy(toPosition);
      controls.target.copy(target);
      camera.zoom = zoom;
      camera.updateProjectionMatrix();
      controls.update();
    } else {
      transition.current = { fromPosition: camera.position.clone(), toPosition, fromTarget: controls.target.clone(), toTarget: target, fromZoom: camera.zoom, toZoom: zoom, elapsed: 0 };
    }
    invalidate();
    return () => { transition.current = null; };
  }, [request, focusKey, camera, controls, invalidate, viewport.width, viewport.height]);
  useEffect(() => {
    if (!controls) return;
    const cancel = () => { transition.current = null; };
    controls.addEventListener('start', cancel);
    return () => controls.removeEventListener('start', cancel);
  }, [controls]);
  useFrame((_, delta) => {
    const motion = transition.current;
    if (!motion || !controls) return;
    motion.elapsed = Math.min(0.42, motion.elapsed + Math.min(delta, 0.05));
    const progress = motion.elapsed / 0.42;
    const eased = 1 - Math.pow(1 - progress, 3);
    camera.position.lerpVectors(motion.fromPosition, motion.toPosition, eased);
    controls.target.lerpVectors(motion.fromTarget, motion.toTarget, eased);
    camera.zoom = motion.fromZoom + (motion.toZoom - motion.fromZoom) * eased;
    camera.updateProjectionMatrix();
    controls.update();
    if (progress < 1) invalidate();
    else transition.current = null;
  });
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

// Positions in the shared timeline describe the virtual tip endpoint in project mm.
// The adapter follows the planned pose; the pinned source uses separate rigid preview groups.
function TimelineHead({ carriage, pipette, frame, plan, timeRef, time, playing, bedMotion, center, selectedId, onSelect, visibleIds }: {
  carriage: Component;
  pipette: Component;
  frame: MotionFrame;
  plan: MotionPlan;
  timeRef?: { current: number };
  time: number;
  playing: boolean;
  bedMotion: boolean;
  center: Vec3;
  selectedId: string | null;
  onSelect: (id: string) => void;
  visibleIds: string[] | null;
}) {
  const group = useRef<Group>(null);
  const tip = useRef<Mesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const tipHeight = VIRTUAL_TIP_LENGTH_MM / SCALE;
  const pipetteOffset: Vec3 = [
    (pipette.position[0] - carriage.position[0]) / SCALE,
    (pipette.position[1] - carriage.position[1]) / SCALE,
    (pipette.position[2] - carriage.position[2]) / SCALE,
  ];
  const position: Vec3 = [
    (frame.position_mm[0] - center[0]) / SCALE - pipetteOffset[0],
    ((bedMotion ? plan.keyframes[0].position_mm[1] : frame.position_mm[1]) - center[1]) / SCALE + pipette.size[1] / SCALE / 2 + tipHeight - pipetteOffset[1],
    (frame.position_mm[2] - center[2]) / SCALE - pipetteOffset[2],
  ];
  // The controls own time. Fiber reads it without a React render for every frame.
  const applyFrame = (next: MotionFrame) => {
    group.current?.position.set(
      (next.position_mm[0] - center[0]) / SCALE - pipetteOffset[0],
      ((bedMotion ? plan.keyframes[0].position_mm[1] : next.position_mm[1]) - center[1]) / SCALE + pipette.size[1] / SCALE / 2 + tipHeight - pipetteOffset[1],
      (next.position_mm[2] - center[2]) / SCALE - pipetteOffset[2],
    );
    if (tip.current) tip.current.visible = next.tip_attached;
  };
  useEffect(() => {
    applyFrame(sampleMotionPlan(plan, timeRef?.current ?? time));
    invalidate();
  }, [plan, timeRef, time, playing, center[0], center[1], center[2], invalidate]);
  useFrame(() => {
    if (!playing) return;
    applyFrame(sampleMotionPlan(plan, timeRef?.current ?? time));
    invalidate();
  });
  const showCarriage = !visibleIds || visibleIds.includes(carriage.id);
  const showPipette = !visibleIds || visibleIds.includes(pipette.id);
  return <group ref={group} position={position} name="operating-tool-preview">
    {showCarriage && <GeometryPart part={carriage} position={[0, 0, 0]} selected={selectedId === carriage.id} onSelect={onSelect} />}
    {showPipette && <GeometryPart part={pipette} position={pipetteOffset} selected={selectedId === pipette.id} onSelect={onSelect} />}
    {showPipette && <mesh ref={tip} visible={frame.tip_attached} name="operating-tip-preview"
      position={[pipetteOffset[0], pipetteOffset[1] - pipette.size[1] / SCALE / 2 - tipHeight / 2, pipetteOffset[2]]}
      onClick={(event) => { event.stopPropagation(); onSelect(pipette.id); }}>
      <cylinderGeometry args={[0.035, 0.012, tipHeight, 16]} />
      <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
    </mesh>}
  </group>;
}

function ColdParkedHead({ carriage, pipette, plan, operation, center, selectedId, onSelect, visibleIds }: {
  carriage: Component; pipette: Component; plan: MotionPlan; operation: OperationSpec; center: Vec3;
  selectedId: string | null; onSelect: (id: string) => void; visibleIds: string[] | null;
}) {
  const group = useRef<Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const apply = () => {
    const park = sampleColdTransfer(plan, operation.timeRef?.current ?? operation.time_s ?? 0)?.jubilee_park_mm ?? [0, 0];
    group.current?.position.set((carriage.position[0] + park[0] - center[0]) / SCALE,
      (carriage.position[1] - center[1]) / SCALE, (carriage.position[2] + park[1] - center[2]) / SCALE);
  };
  useEffect(() => { apply(); invalidate(); }, [plan, operation.time_s, operation.playing, center, invalidate]);
  useFrame(() => { if (operation.playing) { apply(); invalidate(); } });
  const pipetteOffset: Vec3 = [(pipette.position[0] - carriage.position[0]) / SCALE,
    (pipette.position[1] - carriage.position[1]) / SCALE, (pipette.position[2] - carriage.position[2]) / SCALE];
  return <group ref={group} name="cold-parked-jubilee-head">
    {(!visibleIds || visibleIds.includes(carriage.id)) && <GeometryPart part={carriage} position={[0, 0, 0]} selected={selectedId === carriage.id} onSelect={onSelect} />}
    {(!visibleIds || visibleIds.includes(pipette.id)) && <GeometryPart part={pipette} position={pipetteOffset} selected={selectedId === pipette.id} onSelect={onSelect} />}
  </group>;
}

// All accepted deck-mounted components share the source bed's vertical pose.
function BedContents({ operation, enabled, children }: { operation?: OperationSpec; enabled: boolean; children: ReactNode }) {
  const group = useRef<Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const plan = enabled ? operation?.timeline : undefined;
  const apply = () => {
    if (!group.current) return;
    if (!plan || plan.status !== 'ready' || plan.mode !== 'preparation' || !plan.keyframes.length) {
      group.current.position.y = 0;
      return;
    }
    const frame = sampleMotionPlan(plan, operation?.timeRef?.current ?? operation?.time_s ?? 0);
    group.current.position.y = -(frame.position_mm[1] - plan.keyframes[0].position_mm[1]) / SCALE;
  };
  useEffect(() => { apply(); invalidate(); }, [plan, operation?.time_s, operation?.playing, invalidate]);
  useFrame(() => { if (plan && operation?.playing) { apply(); invalidate(); } });
  return <group ref={group} name="operating-bed-contents">{children}</group>;
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

// The inspection pose sequence describes rigid links and joints. Keep the
// original shapes mounted and apply interpolated transforms using the shared clock.
function SmoothInspection({ extension, center, selectedId, onSelect, visibleIds, playback, time, coldClock }: {
  extension: InspectionExtension;
  center: Vec3;
  selectedId: string | null;
  onSelect: (id: string) => void;
  visibleIds: string[] | null;
  playback: { timeRef: { current: number }; playing: boolean };
  time: number;
  coldClock?: { plan: MotionPlan; operation: OperationSpec };
}) {
  const groups = useRef(new Map<string, Group>());
  const invalidate = useThree((state) => state.invalidate);
  const baseline = extension.pose_frames[0]?.components ?? extension.components;
  const apply = () => {
    const coldTime = coldClock && sampleColdTransfer(coldClock.plan, coldClock.operation.timeRef?.current ?? coldClock.operation.time_s ?? 0)?.inspection_park_ratio;
    for (const part of sampleInspection(extension, coldTime ?? (playback.playing ? playback.timeRef.current : time))) {
      const group = groups.current.get(part.id);
      if (!group) continue;
      group.position.set((part.position[0] - center[0]) / SCALE, (part.position[1] - center[1]) / SCALE, (part.position[2] - center[2]) / SCALE);
      if (part.id === 'inspection-upper-link' || part.id === 'inspection-forearm') {
        const reference = baseline.find((item) => item.id === part.id);
        const angle = part.geometry?.primitives[0]?.rotation_y_deg ?? 0;
        const original = reference?.geometry?.primitives[0]?.rotation_y_deg ?? 0;
        group.rotation.y = (angle - original) * Math.PI / 180;
      }
    }
  };
  useEffect(() => { apply(); invalidate(); }, [extension, playback.timeRef, playback.playing, time, coldClock?.operation.time_s, coldClock?.operation.playing, visibleIds, center[0], center[1], center[2], invalidate]);
  useFrame(() => { if (coldClock?.operation.playing || (!coldClock && playback.playing)) { apply(); invalidate(); } });
  return <group name="inspection-motion-preview">{baseline.filter((part) => !visibleIds || visibleIds.includes(part.id)).map((part) =>
    <group key={part.id} ref={(group) => { if (group) groups.current.set(part.id, group); else groups.current.delete(part.id); }}
      position={[(part.position[0] - center[0]) / SCALE, (part.position[1] - center[1]) / SCALE, (part.position[2] - center[2]) / SCALE]}>
      <GeometryPart part={part} position={[0, 0, 0]} selected={part.id === selectedId} onSelect={onSelect} />
    </group>)}</group>;
}

function ColdInspection({ extension, parkFrame, operation, plan, initialTime, center, selectedId, onSelect, visibleIds }: {
  extension: InspectionExtension; parkFrame: NonNullable<ColdTransferPlan['inspection_park_frame']>;
  operation: OperationSpec; plan: MotionPlan; initialTime: number; center: Vec3;
  selectedId: string | null; onSelect: (id: string) => void; visibleIds: string[] | null;
}) {
  const [derived] = useState<InspectionExtension>(() => ({ ...extension, pose_frames: [
    { ...extension.pose_frames[0], time_s: 0, components: sampleInspection(extension, initialTime) },
    { ...parkFrame, time_s: 1 },
  ] }));
  const [playback] = useState(() => ({ timeRef: { current: 0 }, playing: false }));
  return <SmoothInspection extension={derived} center={center} selectedId={selectedId} onSelect={onSelect} visibleIds={visibleIds}
    playback={playback} time={0} coldClock={{ plan, operation }} />;
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

function RackDetails({ components, center, stepCount, selectedId, onSelect, labwareRack, labwarePlate, showPlateLabels, showOpenTubes, hidePlateDetails }: {
  components: Component[];
  center: [number, number, number];
  stepCount: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  labwareRack?: LabwareRack | null;
  labwarePlate?: LabwarePlate | null;
  showPlateLabels?: boolean;
  hidePlateDetails?: boolean;
  showOpenTubes?: boolean;
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
    const top = rack.geometry?.primitives.find((part) => part.holes?.length);
    return (
      <group key={prefix}>
        {Array.from({ length: safeCount }, (_, index) => {
          const hole = top?.holes?.[index];
          const x = hole ? rackCenterX + (top!.position[0] + hole.x_mm) / SCALE : rackCenterX + (index - (safeCount - 1) / 2) * spacing;
          const z = hole ? rackCenterZ + (top!.position[2] + hole.z_mm) / SCALE : rackCenterZ;
          return (
            <mesh key={`${prefix}-${index}`} position={[x, rackTopY + SOURCE_TUBE_MOUTH_ABOVE_RACK_MM / SCALE - height / 2, z]} {...events(rack.id)}>
              <cylinderGeometry args={[radius, radius, height, 16, 1, true]} />
              <meshStandardMaterial color={color} metalness={0.05} roughness={0.45}
                emissive={selectedId === rack.id || hoveredId === rack.id ? '#0a6a71' : '#000000'} emissiveIntensity={selectedId === rack.id ? 0.2 : 0.09} />
            </mesh>
          );
        })}
      </group>
    );
  };

  const sampleTubeCount = Math.max(1, Math.min(6, stepCount));
  const customSampleTubes = () => {
    const rack = details.sampleRack;
    if (!rack || !labwareRack) return null;
    const plate = labwareRack.geometry.primitives.find((primitive) => primitive.id === 'perforated-top');
    if (!plate?.holes) return null;
    const occupied = plate.holes.slice(0, Math.max(0, Math.min(stepCount, labwareRack.spec.count)));
    const topY = (rack.position[1] + rack.size[1] / 2 - center[1]) / SCALE;
    const height = labwareRack.spec.below_rim_height_mm / SCALE;
    const bodyRadius = labwareRack.spec.body_diameter_max_mm / SCALE / 2;
    const capRadius = labwareRack.spec.cap_diameter_max_mm / SCALE / 2;
    return <group>{occupied.map((hole, index) => {
      const x = (rack.position[0] + plate.position[0] + hole.x_mm - center[0]) / SCALE;
      const z = (rack.position[2] + plate.position[2] + hole.z_mm - center[2]) / SCALE;
      return <group key={`custom-tube-${index}`}>
        <mesh name={`sample-tube-envelope-${index}`} position={[x, topY - height / 2, z]} {...events(rack.id)}>
          <cylinderGeometry args={[bodyRadius, bodyRadius, height, 20, 1, Boolean(showOpenTubes)]} />
          <meshStandardMaterial color="#3a8a92" transparent opacity={0.6} roughness={0.5} />
        </mesh>
        <mesh name={showOpenTubes ? `sample-open-rim-envelope-${index}` : `sample-closed-cap-envelope-${index}`} position={[x, topY + 0.006, z]} rotation={[-Math.PI / 2, 0, 0]} {...events(rack.id)}>
          <ringGeometry args={[Math.max(0, capRadius - 0.003), capRadius, 28]} />
          <meshStandardMaterial color="#2a737b" side={DoubleSide} transparent opacity={0.8} />
        </mesh>
      </group>;
    })}</group>;
  };
  const microplateWells = () => {
    const part = details.sampleRack;
    if (!part || !labwarePlate) return null;
    const occupied = new Set(labwarePlate.compatibility.occupied_wells);
    const wells = labwarePlate.derived.wells;
    const origin = part.position.map((value, axis) => (value - center[axis]) / SCALE);
    const a1 = wells.find((well) => well.label === 'A1');
    return <group>{wells.filter((well) => occupied.has(well.label)).map((well) => <mesh key={well.label}
      name={`occupied-well-${well.label}`} position={[origin[0] + well.app_x_mm / SCALE, origin[1] + (well.app_y_mm - 0.5) / SCALE, origin[2] + well.app_z_mm / SCALE]}
      rotation={[-Math.PI / 2, 0, 0]} {...events(part.id)}>
      <circleGeometry args={[well.diameter_mm / SCALE * 0.42, 24]} />
      <meshStandardMaterial color="#087d7d" side={DoubleSide} transparent opacity={0.75} />
    </mesh>)}
    {showPlateLabels && a1 && <>
      {Array.from({ length: 12 }, (_, column) => wells.find((well) => well.label === `A${column + 1}`)).map((well) => well && <PlateAxisLabel key={`column-${well.label}`} position={[origin[0] + well.app_x_mm / SCALE, origin[1] + (well.app_y_mm + 0.6) / SCALE, origin[2] + (well.app_z_mm + 7) / SCALE]} label={well.label.slice(1)} />)}
      {'ABCDEFGH'.split('').map((row) => wells.find((well) => well.label === `${row}1`)).map((well) => well && <PlateAxisLabel key={`row-${well.label}`} position={[origin[0] + (well.app_x_mm - 7) / SCALE, origin[1] + (well.app_y_mm + 0.6) / SCALE, origin[2] + well.app_z_mm / SCALE]} label={well.label[0]} />)}
      <mesh name="a1-orientation-marker" position={[origin[0] + a1.app_x_mm / SCALE, origin[1] + (a1.app_y_mm + 0.1) / SCALE, origin[2] + a1.app_z_mm / SCALE]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[a1.diameter_mm / SCALE * 0.55, a1.diameter_mm / SCALE * 0.65, 28]} />
        <meshStandardMaterial color="#b16b20" side={DoubleSide} />
      </mesh>
    </>}
    </group>;
  };

  return (
    <group>
      {tubeRow(details.sourceRack, 2, 0.06, 0.22, '#2f6f77', 'source-tube')}
      {labwarePlate ? !hidePlateDetails && microplateWells() : labwareRack ? customSampleTubes() : tubeRow(details.sampleRack, sampleTubeCount, 0.06, 0.22, '#3a8a92', 'sample-tube')}

    </group>
  );
}

// A released tip descends into the waste envelope; time is derived from playback.
function DiscardedTip({ waste, center, operation, active }: { waste?: Component; center: Vec3; operation?: OperationSpec; active: boolean }) {
  const mesh = useRef<Mesh>(null);
  const invalidate = useThree((state) => state.invalidate);
  const plan = active ? operation?.timeline : undefined;
  const apply = () => {
    if (!mesh.current || !waste) return;
    const time = operation?.timeRef?.current ?? operation?.time_s ?? 0;
    const discarded = plan?.keyframes.filter((frame) => frame.stage === 'Discard tip' && frame.time_s <= time).at(-1);
    mesh.current.visible = Boolean(discarded);
    if (discarded) {
      const fall = Math.min(1, Math.max(0, (time - discarded.time_s) / 0.35));
      mesh.current.position.set((waste.position[0] - center[0]) / SCALE,
        (waste.position[1] + waste.size[1] / 2 + 5 + VIRTUAL_TIP_LENGTH_MM / 2 - fall * 25 - center[1]) / SCALE,
        (waste.position[2] - center[2]) / SCALE);
    }
  };
  useEffect(() => { apply(); invalidate(); }, [plan, operation?.time_s, operation?.playing, waste, invalidate]);
  useFrame(() => { if (plan && operation?.playing) { apply(); invalidate(); } });
  if (!waste || !plan) return null;
  return <mesh ref={mesh} visible={false} name="discarded-tip-preview">
    <cylinderGeometry args={[0.035, 0.012, VIRTUAL_TIP_LENGTH_MM / SCALE, 16]} />
    <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
  </mesh>;
}

// The same tip envelopes and hole order are used by the motion compiler.
function TipInventory({ rack, center, operation, active, onSelect }: {
  rack?: Component; center: Vec3; operation?: OperationSpec; active: boolean; onSelect: (id: string) => void;
}) {
  const group = useRef<Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const top = rack?.geometry?.primitives.find((primitive) => primitive.holes?.length);
  const holes = top?.holes ?? [];
  const plan = active ? operation?.timeline : undefined;
  const apply = () => {
    if (!group.current) return;
    const available = plan ? availableTipSlots(plan, operation?.timeRef?.current ?? operation?.time_s ?? 0, holes.length) : holes.map(() => true);
    group.current.children.forEach((child, index) => { child.visible = available[index]; });
  };
  useEffect(() => { apply(); invalidate(); }, [plan, operation?.time_s, operation?.playing, holes.length, invalidate]);
  useFrame(() => { if (plan && operation?.playing) { apply(); invalidate(); } });
  if (!rack || !top) return null;
  const topY = rack.position[1] + rack.size[1] / 2 + SCHEMATIC_TIP_TOP_ABOVE_RACK_MM;
  return <group ref={group} name="tip-inventory">{holes.map((hole, index) => <mesh key={index}
    name={`rack-tip-${index}`} position={[(rack.position[0] + top.position[0] + hole.x_mm - center[0]) / SCALE,
      (topY - VIRTUAL_TIP_LENGTH_MM / 2 - center[1]) / SCALE,
      (rack.position[2] + top.position[2] + hole.z_mm - center[2]) / SCALE]}
    onClick={(event) => { event.stopPropagation(); onSelect(rack.id); }}>
    <cylinderGeometry args={[0.035, 0.012, VIRTUAL_TIP_LENGTH_MM / SCALE, 16]} />
    <meshStandardMaterial color="#f7fbfb" metalness={0.05} roughness={0.4} />
  </mesh>)}</group>;
}

export default function Scene({ project, selectedId, onSelect, operation, physics, inspectionTime = 0, inspectionPlayback, captureRef, coldTransferFocusKey = 0 }: {
  project: Project;
  selectedId: string | null;
  onSelect: (id: string) => void;
  operation?: OperationSpec;
  physics?: PhysicsView | null;
  inspectionTime?: number;
  inspectionPlayback?: { timeRef: { current: number }; playing: boolean };
  captureRef?: RefObject<(() => Promise<string>) | null>;
  coldTransferFocusKey?: number;
}) {
  const { components: designComponents, footprint } = project.design;
  const sourceReady = useRef(false);
  const [sourceLoading, setSourceLoading] = useState(Boolean(project.design.foundation));
  const actionRef = useRef<((action: CameraAction) => void) | null>(null);
  const updateSourceReady = useMemo(() => (ready: boolean) => {
    sourceReady.current = ready;
    setSourceLoading(!ready);
  }, []);
  const extension = project.inspection_extension;
  const cold = project.cold_transfer_extension;
  const physicsActive = Boolean(physics && physics.result.project_id === project.id && physics.result.revision === project.revision && physics.result.frames.length > 0 && designComponents.some((part) => part.id === 'carriage') && designComponents.some((part) => part.id === 'pipette'));
  const coldSample = designComponents.find((part) => part.id === cold?.payload_component_id);
  const coldTimeline = operation?.timeline;
  const inspectionPark = (coldTimeline as ColdTransferPlan | undefined)?.inspection_park_frame;
  const showColdHardware = Boolean(!physicsActive && cold && coldSample && project.labware_plate &&
    ['cold-transfer-lid', 'cold-transfer-carriage', 'cold-transfer-gripper', 'cold-transfer-shaft'].every((id) => cold.components.some((part) => part.id === id)));
  const showCold = Boolean(showColdHardware && cold && coldSample && project.labware_plate && coldTimeline &&
    coldTimeline.status === 'ready' && coldTimeline.mode === 'cold-transfer' &&
    coldTimeline.project_id === project.id && coldTimeline.revision === project.revision &&
    (!extension || Boolean(inspectionPark)) &&
    sampleColdTransfer(coldTimeline, operation?.time_s ?? 0));
  const coldIds = useMemo(() => new Set(cold?.component_ids ?? []), [cold]);
  const components = useMemo(() => {
    if (!extension) return designComponents;
    const displayed = sampleInspection(extension, physicsActive ? 0 : inspectionTime);
    const replacements = new Map(displayed.map((part) => [part.id, part]));
    const existing = new Set(designComponents.map((part) => part.id));
    return [...designComponents.map((part) => replacements.get(part.id) ?? part), ...displayed.filter((part) => !existing.has(part.id))];
  }, [designComponents, extension, inspectionTime, physicsActive]);
  const smoothInspection = Boolean(extension && inspectionPlayback && !physicsActive);
  const [viewKey, setViewKey] = useState(0);
  const [isolation, setIsolation] = useState<Isolation | null>(null);
  const [coldFocus, setColdFocus] = useState<FocusRequest | null>(null);
  const isolatedRevision = useRef(`${project.id}:${project.revision}`);
  const layoutKey = JSON.stringify(project.engineering_design?.proposal ?? null);
  const isolationContext = useRef({ projectId: project.id, layoutKey });
  useEffect(() => {
    const revision = `${project.id}:${project.revision}`;
    const retainSampleFocus = isolation?.mode === 'part' && isolation.id === 'sample-rack'
      && selectedId === 'sample-rack' && Boolean(project.labware_plate || project.labware_rack)
      && isolationContext.current.projectId === project.id && isolationContext.current.layoutKey === layoutKey;
    const retainTipFocus = isolation?.mode === 'part' && isolation.id === 'tip-rack'
      && selectedId === 'tip-rack' && Boolean(project.tip_rack)
      && isolationContext.current.projectId === project.id && isolationContext.current.layoutKey === layoutKey;
    if (isolation && (isolation.id !== selectedId || (isolatedRevision.current !== revision && !retainSampleFocus && !retainTipFocus))) {
      setIsolation(null);
      setViewKey((value) => value + 1);
    }
    isolatedRevision.current = revision;
    isolationContext.current = { projectId: project.id, layoutKey };
  }, [isolation, selectedId, project.id, project.revision, project.labware_plate, project.labware_rack, project.tip_rack, layoutKey]);
  const bounds = useMemo(() => {
    if (!components.length) return { center: [0, 0, 0] as [number, number, number], height: 0 };
    const min = [0, 1, 2].map((axis) => Math.min(...components.map((part) => part.position[axis] - part.size[axis] / 2), extension?.bounds.min_mm[axis] ?? Infinity));
    const max = [0, 1, 2].map((axis) => Math.max(...components.map((part) => part.position[axis] + part.size[axis] / 2), extension?.bounds.max_mm[axis] ?? -Infinity));
    // Include the complete lid swing, even when playback is paused or sought.
    const lid = cold?.components.find((part) => part.id === 'cold-transfer-lid');
    if (lid && cold && Number.isFinite(cold.lid_open_angle_deg)) {
      const hingeZ = lid.position[2] + lid.size[2] / 2;
      for (let i = 0; i <= 48; i += 1) {
        const angle = cold.lid_open_angle_deg * Math.PI / 180 * i / 48;
        for (const y of [-lid.size[1] / 2, lid.size[1] / 2]) for (const z of [-lid.size[2], 0]) {
          const movedY = lid.position[1] + y * Math.cos(angle) - z * Math.sin(angle);
          const movedZ = hingeZ + y * Math.sin(angle) + z * Math.cos(angle);
          min[1] = Math.min(min[1], movedY); max[1] = Math.max(max[1], movedY);
          min[2] = Math.min(min[2], movedZ); max[2] = Math.max(max[2], movedZ);
        }
      }
    }
    return { center: [(min[0] + max[0]) / 2, min[1], (min[2] + max[2]) / 2] as [number, number, number], width: max[0] - min[0], height: max[1] - min[1], depth: max[2] - min[2] };
  }, [designComponents, extension, cold]);
  const target: [number, number, number] = [0, bounds.height / SCALE / 2, 0];

  const lastColdFocusKey = useRef(0);
  useEffect(() => {
    if (lastColdFocusKey.current === coldTransferFocusKey) return;
    if (!cold || !showColdHardware) return;
    const fridge = cold.components.find((part) => part.id === 'cold-transfer-fridge');
    if (!fridge) return;
    lastColdFocusKey.current = coldTransferFocusKey;
    const points = [fridge.position, cold.pickup_mm];
    const minX = Math.min(...points.map((point) => point[0])) - fridge.size[0] / 2;
    const maxX = Math.max(...points.map((point) => point[0])) + fridge.size[0] / 2;
    const top = Math.max(cold.transfer_height_mm, fridge.position[1] + fridge.size[1] / 2) + 100;
    const bottom = Math.max(0, Math.min(cold.pickup_mm[1], fridge.position[1]) - 60);
    setIsolation(null);
    setColdFocus({ position: [((minX + maxX) / 2 - bounds.center[0]) / SCALE, ((top + bottom) / 2 - bounds.center[1]) / SCALE, (fridge.position[2] - bounds.center[2]) / SCALE],
      size: [(maxX - minX) / SCALE, (top - bottom) / SCALE, Math.max(fridge.size[2], 300) / SCALE], direction: [0.45, 1, -1.5] });
  }, [coldTransferFocusKey, cold, showColdHardware, bounds.center]);

  const byId = useMemo(() => new Map(components.map((part) => [part.id, part])), [components]);
  const isolated = useMemo(() => {
    if (!isolation || isolation.id !== selectedId) return null;
    const parts = components.filter((part) => isolation.ids.includes(part.id));
    if (!parts.length) return null;
    // Keep the full travel in view when an isolated cold-transfer part moves.
    if (isolation.ids.some((id) => (showCold && id === coldSample?.id) || (showColdHardware && coldIds.has(id)))) {
      return { ...isolation, position: [0, bounds.height / SCALE / 2, 0] as Vec3,
        size: [(bounds.width ?? 0) / SCALE, bounds.height / SCALE, (bounds.depth ?? 0) / SCALE] as Vec3 };
    }
    const min = [0, 1, 2].map((axis) => Math.min(...parts.map((part) => part.position[axis] - part.size[axis] / 2)));
    const max = [0, 1, 2].map((axis) => Math.max(...parts.map((part) => part.position[axis] + part.size[axis] / 2)));
    return { ...isolation, position: min.map((value, axis) => ((value + max[axis]) / 2 - bounds.center[axis]) / SCALE) as Vec3,
      size: min.map((value, axis) => (max[axis] - value) / SCALE) as Vec3 };
  }, [isolation, selectedId, components, bounds, showCold, showColdHardware, coldSample, coldIds]);
  const selectedPart = selectedId ? byId.get(selectedId) : undefined;
  const canInspectWork = Boolean(project.design.foundation && selectedId && WORKING_AREA_IDS.includes(selectedId));
  const canInspectArm = Boolean(selectedId && extension?.component_ids.includes(selectedId));
  const inspectSelection = (mode: Isolation['mode']) => {
    if (!selectedPart) return;
    setColdFocus(null);
    const ids = mode === 'work' ? WORKING_AREA_IDS : mode === 'arm' ? extension?.component_ids ?? [] : [selectedPart.id];
    const parts = components.filter((part) => ids.includes(part.id));
    if (!parts.length) return;
    const min = [0, 1, 2].map((axis) => Math.min(...parts.map((part) => part.position[axis] - part.size[axis] / 2)));
    const max = [0, 1, 2].map((axis) => Math.max(...parts.map((part) => part.position[axis] + part.size[axis] / 2)));
    setIsolation({
      id: selectedPart.id,
      ids,
      mode,
      position: min.map((value, axis) => ((value + max[axis]) / 2 - bounds.center[axis]) / SCALE) as Vec3,
      size: min.map((value, axis) => (max[axis] - value) / SCALE) as Vec3,
    });
  };
  const resetView = () => {
    setIsolation(null);
    setColdFocus(null);
    setViewKey((value) => value + 1);
  };
  const carriagePart = byId.get('carriage');
  const pipettePart = byId.get('pipette');
  const physicsFrame = useMemo(
    () => (physicsActive && physics ? samplePhysicsFrames(physics.result.frames, physics.time_s) : null),
    [physicsActive, physics],
  );
  const timelineFrame = useMemo(() => {
    const timeline = operation?.timeline;
    if (!timeline || timeline.status !== 'ready' || timeline.mode !== 'preparation' ||
        timeline.project_id !== project.id || timeline.revision !== project.revision || !timeline.keyframes.length) return null;
    return sampleMotionPlan(timeline, operation.time_s ?? 0);
  }, [operation?.timeline, operation?.time_s, project.id, project.revision]);
  const showTimeline = Boolean(!physicsActive && timelineFrame && carriagePart && pipettePart);
  const showAnimation = Boolean(!operation?.timeline && !project.labware_rack && !project.labware_plate && !physicsActive && operation && carriagePart && pipettePart);

  const normalizedStepCount = useMemo(() => {
    if (!operation) return 0;
    return operation.steps.length;
  }, [operation]);

  const animationLayout = useMemo(() => {
    if (project.labware_rack || project.labware_plate || !carriagePart || !pipettePart) return null;
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
  }, [project.labware_rack, project.labware_plate, byId, bounds.center, carriagePart, pipettePart, normalizedStepCount, operation?.steps]);

  const staticParts = useMemo(() => {
    if (!showAnimation && !showTimeline && !showCold && !physicsActive) return components;
    return components.filter((part) => part.id !== 'carriage' && part.id !== 'pipette');
  }, [components, showAnimation, showTimeline, showCold, physicsActive]);
  const bedPartForDisplay = (part: Component): Component => {
    if (!showCold || part.id !== coldSample?.id || !part.geometry) return part;
    return { ...part, geometry: { ...part.geometry, primitives: part.geometry.primitives.filter((primitive) => !primitive.id.startsWith('reference-plate-')) } };
  };

  return (
    <>
    <SceneBoundary key={viewKey} onError={() => { sourceReady.current = false; setSourceLoading(false); }}>
      <Canvas
        orthographic
        camera={{ position: project.design.foundation ? [4, 9, -16.4] : [10, 9, 12], zoom: 65, near: 0.01, far: 100 }}
        dpr={[1, 1.5]}
        shadows="percentage"
        frameloop="demand"
        aria-label={physicsActive ? 'MuJoCo state replay in the interactive workstation view.' : 'Interactive schematic 3D workstation model. Drag to rotate and scroll to zoom.'}
      >
        <color attach="background" args={['#edf2ef']} />
        <StudioEnvironment />
        <ambientLight intensity={0.32} />
        <directionalLight position={[7, 12, -8]} intensity={1.65} castShadow shadow-mapSize={[2048, 2048]}
          shadow-bias={-0.00015} shadow-normalBias={0.003} shadow-radius={2}
          shadow-camera-left={-10} shadow-camera-right={10} shadow-camera-top={10} shadow-camera-bottom={-10} />
        <directionalLight position={[-8, 6, -3]} intensity={0.38} color="#e2f1ee" />
        <directionalLight position={[1, 8, 10]} intensity={0.6} color="#fff7e9" />
        <FitCamera enabled={!isolated && !coldFocus} width={Math.max(footprint.width_mm, bounds.width ?? 0)} height={Math.max(footprint.height_mm, bounds.height)} depth={Math.max(footprint.depth_mm, bounds.depth ?? 0)} />
        <FocusCamera request={coldFocus ?? (isolated?.mode === 'arm' ? isolation : isolated)} focusKey={isolated?.mode === 'part' && isolated.id === 'tip-rack' ? `${project.id}:tip-rack` : null} />
        <group>
          {(isolated && !showTimeline && !showCold ? components : staticParts).filter((part) => part.kind !== 'upstream-cad' && !BED_PART_IDS.has(part.id) && (!showColdHardware || !coldIds.has(part.id)) && (!(smoothInspection || showCold) || !extension?.component_ids.includes(part.id)) && (!isolated || isolated.ids.includes(part.id))).map((part) => <GeometryPart key={part.id} part={part}
            position={[(part.position[0] - bounds.center[0]) / SCALE, (part.position[1] - bounds.center[1]) / SCALE, (part.position[2] - bounds.center[2]) / SCALE]}
            selected={part.id === selectedId} onSelect={onSelect} />)}
        </group>
        {!showCold && smoothInspection && extension && inspectionPlayback && <SmoothInspection extension={extension} center={bounds.center}
          selectedId={selectedId} onSelect={onSelect} visibleIds={isolated?.ids ?? null} playback={inspectionPlayback} time={inspectionTime} />}
        {showCold && extension && inspectionPark && operation && coldTimeline && <ColdInspection extension={extension} parkFrame={inspectionPark}
          operation={operation} plan={coldTimeline} initialTime={inspectionPlayback?.timeRef.current ?? inspectionTime} center={bounds.center}
          selectedId={selectedId} onSelect={onSelect} visibleIds={isolated?.ids ?? null} />}
        {project.design.foundation && <Suspense fallback={<SourceState ready={false} onChange={updateSourceReady} />}>
          <SourceState ready onChange={updateSourceReady} />
          <group visible={!isolated || isolated.ids.includes('foundation-jubilee')} position={[-bounds.center[0] / SCALE, -bounds.center[1] / SCALE, -bounds.center[2] / SCALE]}>
            <FoundationMesh bedDropMm={project.design.foundation.bed_drop_mm}
              motion={showTimeline || showCold ? operation : undefined}
              selected={selectedId === 'foundation-jubilee'} onSelect={onSelect} />
          </group>
        </Suspense>}
        <BedContents enabled={Boolean(project.design.foundation && showTimeline)} operation={operation}>
          {(isolated && !showTimeline && !showCold ? components : staticParts).filter((part) => BED_PART_IDS.has(part.id) && (!isolated || isolated.ids.includes(part.id))).map((part) => <GeometryPart key={part.id} part={bedPartForDisplay(part)}
            position={[(part.position[0] - bounds.center[0]) / SCALE, (part.position[1] - bounds.center[1]) / SCALE, (part.position[2] - bounds.center[2]) / SCALE]}
            selected={part.id === selectedId} onSelect={onSelect} />)}
          <RackDetails components={isolated ? components.filter((part) => isolated.ids.includes(part.id)) : components} center={bounds.center} stepCount={operation ? normalizedStepCount : project.plan?.steps.length ?? 0} selectedId={selectedId} onSelect={onSelect} labwareRack={project.labware_rack} labwarePlate={project.labware_plate} showPlateLabels={isolated?.mode === 'part' && selectedId === project.labware_plate?.target_component_id} showOpenTubes={showTimeline} hidePlateDetails={showCold} />
          {(!isolated || isolated.ids.includes('tip-waste')) && <DiscardedTip waste={byId.get('tip-waste')} center={bounds.center} operation={operation} active={showTimeline} />}
          {(!isolated || isolated.ids.includes('tip-rack')) && <TipInventory rack={byId.get('tip-rack')} center={bounds.center} operation={operation} active={showTimeline} onSelect={onSelect} />}
        </BedContents>
        {showColdHardware && cold && coldSample && project.labware_plate && <ColdTransferScene extension={cold} sample={coldSample} plate={project.labware_plate}
          center={bounds.center} operation={showCold ? operation : undefined} selectedId={selectedId} onSelect={onSelect} visibleIds={isolated?.ids ?? null} renderPayload={showCold} />}
        {showCold && coldTimeline && operation && carriagePart && pipettePart && <ColdParkedHead carriage={carriagePart} pipette={pipettePart}
          plan={coldTimeline} operation={operation} center={bounds.center} selectedId={selectedId} onSelect={onSelect} visibleIds={isolated?.ids ?? null} />}
        {!isolated && physicsActive && physics && physics.result.obstacles.map((obstacle) => (
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
        {!isolated && physicsActive && carriagePart && pipettePart && physicsFrame && (
          <PhysicalHead carriage={carriagePart} pipette={pipettePart} frame={physicsFrame} center={bounds.center} selectedId={selectedId} onSelect={onSelect} />
        )}
        {showTimeline && carriagePart && pipettePart && timelineFrame && <TimelineHead
          carriage={carriagePart} pipette={pipettePart} frame={timelineFrame} center={bounds.center}
          plan={operation!.timeline!} timeRef={operation!.timeRef} time={operation!.time_s ?? 0} playing={operation!.playing} bedMotion={Boolean(project.design.foundation)}
          visibleIds={isolated?.ids ?? null} selectedId={selectedId} onSelect={onSelect} />}
        {showAnimation && carriagePart && pipettePart && animationLayout && operation ? (
          <group visible={!isolated}>
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
          </group>
        ) : null}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, isolated ? isolated.position[1] - isolated.size[1] / 2 - 0.008 : -0.008, 0]} receiveShadow>
          <planeGeometry args={[200, 200]} />
          <meshStandardMaterial color="#e7eeea" roughness={1} />
        </mesh>
        <OrbitControls makeDefault target={target} minZoom={15} maxZoom={700} minPolarAngle={0.08} maxPolarAngle={Math.PI / 2 - 0.04} enablePan={false} />
        <SceneTools captureRef={captureRef} actionRef={actionRef} sourceReady={sourceReady} sourceRequired={Boolean(project.design.foundation)} />
      </Canvas>
    </SceneBoundary>
    {project.design.foundation && sourceLoading && <div className="scene-loading" role="status">Loading source model…</div>}
    {project.labware_rack && (!isolated || isolated.ids.includes(project.labware_rack.target_component_id)) && <div className="scene-rack-occupancy">{Math.min(normalizedStepCount, project.labware_rack.spec.count)} / {project.labware_rack.spec.count} positions occupied · tube envelopes</div>}
    {project.labware_plate && (!isolated || isolated.ids.includes(project.labware_plate.target_component_id)) && <div className="scene-rack-occupancy">{project.labware_plate.compatibility.occupied_wells.length} / {project.labware_plate.derived.well_count} wells occupied · A1 marked in amber</div>}
    <div className="scene-controls" role="group" aria-label="3D view controls">
      <span>View</span>
      {([['left', 'Rotate left', '←'], ['right', 'Rotate right', '→'], ['up', 'Rotate up', '↑'], ['down', 'Rotate down', '↓'], ['in', 'Zoom in', '+'], ['out', 'Zoom out', '−']] as const).map(([action, label, symbol]) =>
        <button key={action} type="button" aria-label={label} title={label} onClick={() => actionRef.current?.(action)}>{symbol}</button>)}
    </div>
    {selectedPart && <select className="scene-reset" style={{ right: 125, width: 155, maxWidth: 'calc(100% - 145px)' }}
      aria-label="Inspect component view" value={isolated?.mode ?? ''}
      onChange={(event) => { if (event.target.value) inspectSelection(event.target.value as Isolation['mode']); }}>
      <option value="" disabled>Inspect view…</option>
      <option value="part">Selected part only</option>
      {canInspectWork && <option value="work">Working area only</option>}
      {canInspectArm && <option value="arm">Arm + camera only</option>}
    </select>}
    <button className="scene-reset" type="button" onClick={resetView}>{isolated ? 'Show full model' : 'Reset view'}</button>
    </>
  );
}
