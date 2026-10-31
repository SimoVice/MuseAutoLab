import { useEffect, useMemo } from 'react';
import { useLoader, useThree, type ThreeEvent } from '@react-three/fiber';
import { DoubleSide, Mesh, MeshStandardMaterial } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

/** Render the reviewed, fixed Jubilee source; never load a user-provided URL. */
export default function FoundationMesh({ selected = false, onSelect, bedDropMm = 100 }: {
  selected?: boolean;
  onSelect?: (id: string) => void;
  bedDropMm?: number;
}) {
  const invalidate = useThree((state) => state.invalidate);
  const [fixedGltf, bedGltf] = useLoader(GLTFLoader, [
    '/assets/jubilee-c877bd2-static.glb', '/assets/jubilee-c877bd2-bed.glb',
  ]);
  const material = useMemo(() => new MeshStandardMaterial({
    color: '#85989a', metalness: 0.65, roughness: 0.42, side: DoubleSide,
  }), []);
  const scenes = useMemo(() => [fixedGltf, bedGltf].map((gltf) => {
    const cloned = gltf.scene.clone(true);
    cloned.traverse((child) => {
      if (!(child instanceof Mesh)) return;
      // The source has no normals. Derive them once on an owned copy without changing its vertices.
      child.geometry = child.geometry.clone();
      child.geometry.computeVertexNormals();
      child.material = material;
      child.castShadow = true;
      child.receiveShadow = true;
    });
    return cloned;
  }), [fixedGltf, bedGltf, material]);
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
  if (!Number.isFinite(bedDropMm) || bedDropMm < 0 || bedDropMm > 150) {
    throw new Error('Invalid Jubilee bed position');
  }
  return (
    <group name="foundation-jubilee"
      position={[-274.855945675 / 100, -272.216535584 / 100, 425.743280356 / 100]}
      scale={[0.01, 0.01, -0.01]}
      onClick={(event: ThreeEvent<MouseEvent>) => {
        event.stopPropagation();
        onSelect?.('foundation-jubilee');
      }}>
      <primitive object={scenes[0]} />
      <group position={[0, -bedDropMm, 0]}><primitive object={scenes[1]} /></group>
    </group>
  );
}
