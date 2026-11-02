import { useEffect, useRef, useState } from 'react';
import { OrthographicCamera } from 'three';
import { Canvas, useThree } from '@react-three/fiber';
import { Bounds, OrbitControls, useBounds } from '@react-three/drei';
import type { BenchStation, BenchStationModule, ProcurementReport, ProcurementResponse, Project } from './types';
import CostSummary from './CostSummary';
import './bench-station.css';

const colors = { frame: '#c6d2d1', surface: '#eff4f2', dark: '#263d42', accent: '#277b78', metal: '#aebec0' };

function Box({ size, position, color = colors.surface, metalness = 0.2 }: { size: [number, number, number]; position: [number, number, number]; color?: string; metalness?: number }) {
  return <mesh position={position} castShadow receiveShadow><boxGeometry args={size} /><meshStandardMaterial color={color} metalness={metalness} roughness={0.32} /></mesh>;
}

function Cylinder({ radius, height, position, rotation = [0, 0, 0], color = colors.metal }: { radius: number; height: number; position: [number, number, number]; rotation?: [number, number, number]; color?: string }) {
  return <mesh position={position} rotation={rotation} castShadow><cylinderGeometry args={[radius, radius, height, 32]} /><meshStandardMaterial color={color} metalness={0.65} roughness={0.28} /></mesh>;
}

// Every visual fits inside the module's supplied envelope. These are original schematic forms.
function StationModule({ module, scale }: { module: BenchStationModule; scale: number }) {
  const [w, h, d] = module.size_mm.map((n) => n * scale) as [number, number, number];
  const pos = module.position_mm.map((n) => n * scale) as [number, number, number];
  const unit = Math.min(w, h, d);
  return <group position={pos}>
    {module.id === 'weigh' && <>
      <Box size={[w, h * .48, d]} position={[0, -h * .26, 0]} color="#dbe5e4" />
      <Box size={[w * .38, h * .12, d * .025]} position={[0, -h * .23, d * .506]} color={colors.dark} />
      <Box size={[w * .18, h * .035, d * .027]} position={[-w * .05, -h * .23, d * .522]} color="#6dc2b4" />
      <Cylinder radius={Math.min(w, d) * .32} height={h * .055} position={[0, h * .025, 0]} />
      <Cylinder radius={Math.min(w, d) * .27} height={h * .035} position={[0, h * .07, 0]} color="#e7eeee" />
    </>}
    {module.id === 'print_label' && <>
      <Box size={[w, h * .82, d]} position={[0, -h * .09, 0]} color="#dbe5e4" />
      <Box size={[w * .77, h * .08, d * .04]} position={[0, -h * .15, d * .51]} color={colors.dark} />
      <Box size={[w * .57, h * .22, d * .045]} position={[0, -h * .30, d * .525]} color="#fffefa" />
      <Cylinder radius={Math.min(w, h) * .23} height={d * .22} rotation={[Math.PI / 2, 0, 0]} position={[0, h * .16, d * .40]} color="#f8faf7" />
      <Cylinder radius={Math.min(w, h) * .065} height={d * .23} rotation={[Math.PI / 2, 0, 0]} position={[0, h * .16, d * .4]} color={colors.dark} />
    </>}
    {module.id === 'read_barcode' && <>
      <Box size={[w * .72, h * .12, d * .9]} position={[0, -h * .44, 0]} color={colors.dark} />
      <Box size={[w * .13, h * .62, d * .16]} position={[0, -h * .09, -d * .12]} color={colors.metal} metalness={.7} />
      <Box size={[w * .72, h * .30, d * .40]} position={[0, h * .25, 0]} color={colors.dark} />
      <Box size={[w * .52, h * .11, d * .025]} position={[0, h * .22, d * .212]} color="#72bbb4" />
    </>}
    {module.id === 'inspect' && <>
      <Box size={[w, h * .10, d]} position={[0, -h * .45, 0]} color={colors.dark} />
      <Box size={[w * .12, h * .76, d * .12]} position={[-w * .36, -.02 * h, -d * .32]} color={colors.metal} metalness={.7} />
      <Box size={[w * .64, h * .09, d * .12]} position={[-w * .10, h * .35, -d * .32]} color={colors.metal} metalness={.7} />
      <Box size={[w * .34, h * .22, d * .30]} position={[w * .13, h * .24, -d * .25]} color={colors.dark} />
      <Cylinder radius={unit * .12} height={h * .08} position={[w * .13, h * .09, -d * .25]} color="#90b5b1" />
    </>}
  </group>;
}

function FitOnResize({ turn }: { turn: number }) {
  const bounds = useBounds();
  const size = useThree((state) => state.size);
  useEffect(() => { bounds.refresh().clip().fit(); }, [bounds, size.width, size.height, turn]);
  return null;
}

function KeyboardZoom({ zoom }: { zoom: number }) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  const previous = useRef(zoom);
  useEffect(() => {
    const delta = zoom - previous.current;
    previous.current = zoom;
    if (delta && camera instanceof OrthographicCamera) {
      camera.zoom = Math.max(25, Math.min(1200, camera.zoom * Math.pow(1.2, delta)));
      camera.updateProjectionMatrix();
      invalidate();
    }
  }, [zoom, camera, invalidate]);
  return null;
}

function StationScene({ station, turn, zoom }: { station: BenchStation; turn: number; zoom: number }) {
  const scale = 1 / Math.max(...station.footprint_mm, 1);
  const [width, depth] = station.footprint_mm.map((n) => n * scale);
  const height = Math.max(...station.modules.map((module) => module.position_mm[1] + module.size_mm[1] / 2), 0) * scale;
  return <Canvas aria-label="Interactive modular bench station schematic" orthographic frameloop="demand" camera={{ position: [2.3, 2.1, 3], zoom: 200, near: .001, far: 100 }}>
    <color attach="background" args={['#edf3f1']} />
    <ambientLight intensity={1.5} />
    <directionalLight position={[2, 4, 3]} intensity={2.6} />
    <directionalLight position={[-3, 2, -2]} intensity={1.1} />
    <Bounds fit clip observe margin={1.1} maxDuration={0}>
      <group rotation={[0, turn * Math.PI / 4, 0]}>
        <group position={[-width / 2, -height / 2, -depth / 2]}>
        <Box size={[width, .025, depth]} position={[width / 2, -.015, depth / 2]} color={colors.frame} metalness={.55} />
        <Box size={[width * .98, .008, depth * .98]} position={[width / 2, .002, depth / 2]} color="#f6f9f7" />
        {station.modules.map((module) => module.functional_surface_mm && <Box key={`surface-${module.id}`} size={[module.functional_surface_mm[2] * scale, .004, module.functional_surface_mm[3] * scale]} position={[(module.functional_surface_mm[0] + module.functional_surface_mm[2] / 2) * scale, .009, (module.functional_surface_mm[1] + module.functional_surface_mm[3] / 2) * scale]} color="#e1eeea" />)}
        {station.modules.map((module) => <StationModule key={module.id} module={module} scale={scale} />)}
        </group>
      </group>
      <FitOnResize turn={turn} />
    </Bounds>
    <KeyboardZoom zoom={zoom} />
    <OrbitControls makeDefault enablePan={false} minZoom={25} maxZoom={1200} maxPolarAngle={Math.PI / 2 - .03} />
  </Canvas>;
}

function supplierPrice(part: BenchStation['parts'][number], report: ProcurementReport | null) {
  const id = `bench-${part.operation}-${part.source_url ? 'equipment' : 'supplies'}`;
  const row = report?.rows.find((item) => item.group_id === id);
  if (row?.status === 'priced' && row.freshness === 'fresh' && row.line_total != null)
    return `Verified supplier · $${row.line_total.toFixed(2)} USD`;
  if (row?.status === 'quote_needed' || (part.source_url && part.operation !== 'inspect'))
    return 'US supplier quote needed';
  return 'Supplier price unavailable';
}

export default function BenchStationPanel({ station, project, projectId, revision }: { station: BenchStation; project: Project; projectId: string; revision: number }) {
  const [turn, setTurn] = useState(0);
  const [zoom, setZoom] = useState(0);
  const [viewKey, setViewKey] = useState(0);
  const [report, setReport] = useState<ProcurementReport | null>(null);
  const [pricesReady, setPricesReady] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [priceIssue, setPriceIssue] = useState<string | null>(null);
  const [priceEpoch, setPriceEpoch] = useState(0);
  const base = `/api/projects/${encodeURIComponent(projectId)}`;
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${base}/procurement?revision=${revision}`, { signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error('Saved prices are unavailable.'); return response.json() as Promise<ProcurementResponse>; })
      .then((data) => { if (!controller.signal.aborted && data.state === 'current' && data.report?.project_id === projectId && data.report.project_revision === revision) setReport(data.report); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setPriceIssue(error instanceof Error ? error.message : 'Saved prices are unavailable.'); })
      .finally(() => { if (!controller.signal.aborted) setPricesReady(true); });
    return () => controller.abort();
  }, [base, projectId, revision]);
  async function refreshPrices() {
    setRefreshing(true); setPriceIssue(null);
    try {
      const response = await fetch(`${base}/procurement/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_revision: revision }) });
      if (!response.ok) throw new Error('Supplier prices could not be refreshed.');
      const data: ProcurementResponse = await response.json();
      if (data.state !== 'current' || data.report?.project_id !== projectId || data.report.project_revision !== revision) throw new Error('The price report does not match this revision.');
      setReport(data.report);
    } catch (error) { setPriceIssue(error instanceof Error ? error.message : 'Supplier prices could not be refreshed.'); }
    finally { setRefreshing(false); }
  }
  useEffect(() => {
    if (!report) return;
    const delay = Date.parse(report.expires_at) - Date.now();
    if (!Number.isFinite(delay) || delay <= 0) return;
    const timer = window.setTimeout(() => setPriceEpoch((value) => value + 1), Math.min(delay + 20, 2147483647));
    return () => window.clearTimeout(timer);
  }, [report, priceEpoch]);
  const liveReport = report?.project_id === projectId && report.project_revision === revision && Date.parse(report.expires_at) > Date.now() ? report : null;
  const exportBase = `/api/projects/${encodeURIComponent(projectId)}/bench-station`;
  return <section className="bench-station" aria-label="Modular bench station">
    <div className="bench-station-heading"><div><h2>Modular bench station</h2><p>Concept layout · revision {revision}</p></div><span>Schematic</span></div>
    <div className="bench-station-view">
      <StationScene key={viewKey} station={station} turn={turn} zoom={zoom} />
      <div className="bench-station-controls" aria-label="Schematic view controls">
        <button type="button" onClick={() => setTurn((v) => v - 1)} aria-label="Rotate station left">↶</button>
        <button type="button" onClick={() => setTurn((v) => v + 1)} aria-label="Rotate station right">↷</button>
        <button type="button" onClick={() => setZoom((v) => v + 1)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => setZoom((v) => v - 1)} aria-label="Zoom out">−</button>
        <button type="button" onClick={() => { setTurn(0); setZoom(0); setViewKey((value) => value + 1); }}>Reset view</button>
      </div>
      <span className="bench-station-hint">Drag to rotate · Scroll to zoom</span>
    </div>
    <div className="bench-station-meta"><span>Proposed footprint</span><strong>{station.footprint_mm[0]} × {station.footprint_mm[1]} mm</strong></div>
    {pricesReady && <CostSummary project={project} report={liveReport} />}
    <p className="bench-station-disclaimer">Original schematic, not manufacturer CAD. Shaded areas reserve access around each module. Positions and envelopes are conceptual; fit, safety and performance require verification.</p>
    <div className="bench-station-body">
      <div><h3>Work through the station</h3><p>Follow the sequence and complete each human handoff before moving to the next operation.</p><ol>{station.steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol></div>
      <div><h3>Modules and sourcing references</h3><p>References help identify equipment; they are not quotes or verified compatibility. US prices, when available, are shown in USD.</p><button className="bench-station-refresh" type="button" disabled={refreshing || !pricesReady} onClick={() => void refreshPrices()}>{refreshing ? 'Checking supplier catalogs…' : 'Refresh US prices'}</button>{priceIssue && <p role="status">{priceIssue}</p>}<ul className="bench-station-parts">{station.modules.map((module, index) => {
        const parts = station.parts.filter((item) => item.operation === module.id);
        return <li key={module.id}><span className="bench-station-number">{index + 1}</span><div><strong>{module.label}</strong><p>{module.role} {module.guidance}</p><ul className="bench-station-references">{parts.map((part, partIndex) => <li key={partIndex}><span>{part.label}</span>{part.source_url && part.source_title && <a href={part.source_url} target="_blank" rel="noopener noreferrer">{part.source_title}</a>}<span className="bench-station-price">{supplierPrice(part, liveReport)}</span></li>)}</ul></div></li>;
      })}</ul></div>
    </div>
    <div className="bench-station-limits"><h3>Constraints and checks</h3><ul>{station.limitations.map((limit, index) => <li key={`${index}-${limit}`}>{limit}</li>)}</ul></div>
    <p className="bench-station-disclaimer">Download the plan and runner together. Run <code>python run.py --plan plan.json --output record.json</code> to record operator checkpoints. Add <code>--dry-run</code> to preview the sequence. {station.modules.some((module) => module.id === 'print_label') && <>Add <code>--label-output label.html</code> during an assisted run to prepare a printable text label. </>}The operator handles the instruments.</p>
    <div className="bench-station-downloads"><a href={`${exportBase}/layout.svg?revision=${revision}`} download>Download layout (SVG)</a><a href={`${exportBase}/plan.json?revision=${revision}`} download>Download plan (JSON)</a><a href={`${exportBase}/run.py?revision=${revision}`} download>Download assisted runner (Python)</a></div>
  </section>;
}
