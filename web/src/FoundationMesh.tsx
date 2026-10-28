import { useEffect, useMemo } from 'react';
import { useLoader, type ThreeEvent } from '@react-three/fiber';
import { DoubleSide, Mesh, MeshStandardMaterial } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

/** Render the reviewed, fixed Jubilee source; never load a user-provided URL. */
export default function FoundationMesh({ selected = false, onSelect, bedDropMm = 100 }: {
  selected?: boolean;
  onSelect?: (id: string) => void;
  bedDropMm?: number;
}) {
  const [fixedGltf, bedGltf] = useLoader(GLTFLoader, [
    '/assets/jubilee-c877bd2-static.glb', '/assets/jubilee-c877bd2-bed.glb',
  ]);
  const scenes = useMemo(() => [fixedGltf, bedGltf].map((gltf) => {
    const cloned = gltf.scene.clone(true);
    cloned.traverse((child) => {
      if (!(child instanceof Mesh)) return;
      child.geometry = child.geometry.clone();
      child.geometry.computeVertexNormals();
      child.material = new MeshStandardMaterial({
        color: '#9aadb2', metalness: 0.55, roughness: 0.42,
        emissive: selected ? '#0a6a71' : '#000000',
        emissiveIntensity: selected ? 0.17 : 0,
        side: DoubleSide,
      });
      child.castShadow = true;
      child.receiveShadow = true;
    });
    return cloned;
  }), [fixedGltf, bedGltf, selected]);
  useEffect(() => () => {
    scenes.forEach((scene) => scene.traverse((child) => {
      if (child instanceof Mesh) {
        child.geometry.dispose();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach((material) => material.dispose());
      }
    }));
  }, [scenes]);
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
