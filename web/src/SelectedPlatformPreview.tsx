import { Suspense, useCallback, useEffect, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Bounds, OrbitControls, useBounds } from '@react-three/drei';
import FoundationMesh from './FoundationMesh';

function ReadyFoundation({ onReady }: { onReady: () => void }) {
  const bounds = useBounds();
  const size = useThree((state) => state.size);
  useEffect(onReady, [onReady]);
  useEffect(() => { bounds.refresh().clip().fit(); }, [bounds, size.width, size.height]);
  return <FoundationMesh />;
}

/** The explicitly selected source foundation, before a custom layout is accepted. */
export default function SelectedPlatformPreview() {
  const [ready, setReady] = useState(false);
  const onReady = useCallback(() => setReady(true), []);
  return <section className="selected-platform-preview" aria-label="Selected Jubilee platform preview">
    <div className="planning-heading"><div><h2>Jubilee foundation</h2>
      <p>Selected platform · custom layout pending</p></div></div>
    <div className="viewer-canvas" style={{ height: 'clamp(300px, 44vh, 480px)' }}>
      <Canvas aria-label="Interactive pinned Jubilee foundation. Drag to rotate and scroll to zoom." orthographic frameloop="demand" camera={{ position: [8, 7, -12], zoom: 60, near: 0.01, far: 100 }}>
        <color attach="background" args={['#eef1ef']} />
        <ambientLight intensity={1.4} />
        <directionalLight position={[6, 10, -8]} intensity={2.4} />
        <directionalLight position={[-7, 4, 6]} intensity={1.2} />
        <Suspense fallback={null}><Bounds fit clip observe margin={1.15} maxDuration={0}><ReadyFoundation onReady={onReady} /></Bounds></Suspense>
        <OrbitControls makeDefault minZoom={15} maxZoom={700} maxPolarAngle={Math.PI / 2 - 0.04} />
      </Canvas>
      {!ready && <div className="scene-loading" role="status">Loading selected source model…</div>}
      <div className="scene-hint">Drag to rotate · Scroll to zoom</div>
    </div>
    <p className="planning-note">Pinned Jubilee source CAD preview. The custom layout will appear after a design is accepted. Optional arms and cold storage are added only when requested.</p>
  </section>;
}
