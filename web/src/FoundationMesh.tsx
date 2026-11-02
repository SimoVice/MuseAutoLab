import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useLoader, useThree, type ThreeEvent } from '@react-three/fiber';
import { DoubleSide, Mesh, MeshStandardMaterial, type Group } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { sampleMotionPlan } from './motionPlan';
import { deformJubileeBelts } from './beltDeformation';
import { sampleColdTransfer } from './coldTransferMotion';
import type { OperationSpec } from './operation';

/** Rigid renderer partitions of the pinned source. CAD exports use the original STEP. */
export default function FoundationMesh({ selected = false, onSelect, bedDropMm = 100, motion }: {
  selected?: boolean;
  onSelect?: (id: string) => void;
  bedDropMm?: number;
  motion?: OperationSpec;
}) {
  const invalidate = useThree((state) => state.invalidate);
  const [fixedGltf, crossbarGltf, carriageGltf, beltsGltf, bedGltf] = useLoader(GLTFLoader, [
    '/assets/jubilee-c877bd2-motion-fixed.glb',
    '/assets/jubilee-c877bd2-motion-crossbar.glb',
    '/assets/jubilee-c877bd2-motion-carriage.glb',
    '/assets/jubilee-c877bd2-motion-belts.glb',
    '/assets/jubilee-c877bd2-bed.glb',
  ]);
  const crossbar = useRef<Group>(null);
  const carriage = useRef<Group>(null);
  const belts = useRef<Group>(null);
  const bed = useRef<Group>(null);
  const material = useMemo(() => new MeshStandardMaterial({
    color: '#85989a', metalness: 0.65, roughness: 0.42, side: DoubleSide,
  }), []);
  const scenes = useMemo(() => [fixedGltf, crossbarGltf, carriageGltf, beltsGltf, bedGltf].map((gltf) => {
    const cloned = gltf.scene.clone(true);
    cloned.traverse((child) => {
      if (!(child instanceof Mesh)) return;
      child.geometry = child.geometry.clone();
      child.geometry.computeVertexNormals();
      child.material = material;
      child.castShadow = true;
      child.receiveShadow = true;
    });
    return cloned;
  }), [fixedGltf, crossbarGltf, carriageGltf, beltsGltf, bedGltf, material]);
  const beltGeometry = useMemo(() => {
    const meshes: Array<{ mesh: Mesh; original: Float32Array }> = [];
    scenes[3].traverse((child) => {
      if (child instanceof Mesh) {
        const attribute = child.geometry.getAttribute('position');
        meshes.push({ mesh: child, original: new Float32Array(attribute.array as ArrayLike<number>) });
      }
    });
    return meshes;
  }, [scenes]);
  useEffect(() => {
    material.emissive.set(selected ? '#0a6a71' : '#000000');
    material.emissiveIntensity = selected ? 0.17 : 0;
    invalidate();
  }, [material, selected, invalidate]);
  useEffect(() => () => {
    scenes.forEach((scene) => scene.traverse((child) => {
      if (child instanceof Mesh) child.geometry.dispose();
    }));
    material.dispose();
  }, [scenes, material]);
  const plan = motion?.timeline;
  const apply = () => {
    if (!crossbar.current || !carriage.current || !belts.current || !bed.current) return;
    let dx = 0, dz = 0, drop = bedDropMm;
    if (plan?.status === 'ready' && plan.mode === 'preparation' && plan.keyframes.length) {
      const home = plan.keyframes[0].position_mm;
      const frame = sampleMotionPlan(plan, motion?.timeRef?.current ?? motion?.time_s ?? 0);
      dx = frame.position_mm[0] - home[0];
      dz = frame.position_mm[2] - home[2];
      drop += frame.position_mm[1] - home[1];
    } else if (plan?.status === 'ready' && plan.mode === 'cold-transfer') {
      const frame = sampleColdTransfer(plan, motion?.timeRef?.current ?? motion?.time_s ?? 0);
      if (frame) [dx, dz] = frame.jubilee_park_mm;
    }
    // Source axes use the opposite Z convention to the application.
    crossbar.current.position.set(0, 0, -dz);
    carriage.current.position.set(dx, 0, -dz);
    // Deform the original straight runs between fixed frame turns and mobile turns.
    // This is a visual kinematic interpolation, not a belt physics simulation.
    beltGeometry.forEach(({ mesh, original }) => {
      const position = mesh.geometry.getAttribute('position');
      deformJubileeBelts(original, position.array as Float32Array, dx, -dz);
      position.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
      mesh.geometry.computeBoundingSphere();
    });
    bed.current.position.set(0, -drop, 0);
  };
  useEffect(() => { apply(); invalidate(); }, [plan, motion?.time_s, motion?.playing, bedDropMm, invalidate]);
  useFrame(() => { if (plan && motion?.playing) { apply(); invalidate(); } });
  if (!Number.isFinite(bedDropMm) || bedDropMm < 0 || bedDropMm > 150) {
    throw new Error('Invalid Jubilee bed position');
  }
  return (
    <group name="foundation-jubilee"
      position={[-274.855945675 / 100, -272.216535584 / 100, 425.743280356 / 100]}
      scale={[0.01, 0.01, -0.01]}
      onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect?.('foundation-jubilee'); }}>
      <primitive object={scenes[0]} />
      <group ref={crossbar}><primitive object={scenes[1]} /></group>
      <group ref={carriage}><primitive object={scenes[2]} /></group>
      <group ref={belts}><primitive object={scenes[3]} /></group>
      <group ref={bed} position={[0, -bedDropMm, 0]}><primitive object={scenes[4]} /></group>
    </group>
  );
}
