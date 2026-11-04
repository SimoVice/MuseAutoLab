import StepIllustration from './StepIllustration';
import type { ImageCapability } from './ModelSelector';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Vector3 as ThreeVector3, type Group } from 'three';
import { Bounds, OrbitControls } from '@react-three/drei';
import { conceptDuration, conceptIndexAngle, conceptIndexDuration, conceptTravelAt } from './conceptMotion';
import './concept-workspace.css';

type Vector3 = [number, number, number];
type Finish = 'frame' | 'steel' | 'polymer' | 'clear' | 'accent' | 'dark';
type ConceptPrimitive = { shape: 'box' | 'cylinder' | 'sphere'; center_mm: Vector3; size_mm: Vector3; finish: Finish; color?: string | null };
type ConceptComponent = { key: string; name: string; role: string; primitives: ConceptPrimitive[]; source: { title: string; url: string } | null; assembly: string; check: string; position_mm: Vector3; size_mm: Vector3 };
type ConceptSupply = { key: string; name: string; role: string; quantity: number; unit: string; source: { title: string; url: string } | null; catalog_search_url?: string | null; component_names?: string[] };
type ConceptStep = { name: string; instruction: string; component_keys: string[]; moving_key: string | null; moving_component_keys?: string[]; translation_mm: Vector3; rotation_deg?: number; rotation_axis?: 'x' | 'y' | 'z' | null; pivot_mm?: Vector3 | null; stops?: number[]; rotation_reference?: 'from_rest' | 'previous_index'; index_chain?: boolean; start_rotation_deg?: number; rotation_delta_deg?: number };
type WorkInterface = { key: string; label: string; tool_key: string; target_key: string; step_name: string | null; phase: number };
export type ConceptDesign = { title: string; overview: string; footprint_mm: [number, number]; bounds_mm?: { min: Vector3; max: Vector3 }; components: ConceptComponent[]; supplies?: ConceptSupply[]; work_interfaces?: WorkInterface[]; steps: ConceptStep[]; software: { controller: string; interfaces: string[]; setup: string[]; checks: string[] }; open_questions: string[] };

const finishes: Record<Finish, { color: string; metalness: number; roughness: number; opacity?: number }> = {
  frame: { color: '#9aaeb0', metalness: .64, roughness: .34 },
  steel: { color: '#c7d3d1', metalness: .78, roughness: .24 },
  polymer: { color: '#e8eeeb', metalness: .08, roughness: .52 },
  clear: { color: '#b9deda', metalness: .05, roughness: .18, opacity: .47 },
  accent: { color: '#3e8e85', metalness: .26, roughness: .32 },
  dark: { color: '#314c51', metalness: .28, roughness: .38 },
};

function Primitive({ primitive, scale }: { primitive: ConceptPrimitive; scale: number }) {
  const material = finishes[primitive.finish] || finishes.polymer;
  const position = primitive.center_mm.map((n) => n * scale) as Vector3;
  const size = primitive.size_mm.map((n) => Math.max(n * scale, .0001)) as Vector3;
  return <mesh position={position} castShadow receiveShadow>
    {primitive.shape === 'box' ? <boxGeometry args={size} /> : primitive.shape === 'cylinder' ? <cylinderGeometry args={[.5, .5, 1, 32]} /> : <sphereGeometry args={[.5, 24, 16]} />}
    <meshStandardMaterial color={primitive.color ?? material.color} metalness={material.metalness} roughness={material.roughness} transparent={material.opacity != null} opacity={material.opacity ?? 1} depthWrite={material.opacity == null} />
  </mesh>;
}

// A cylinder or sphere is built at unit size so its three supplied dimensions remain independent.
function ShapedPrimitive({ primitive, scale }: { primitive: ConceptPrimitive; scale: number }) {
  if (primitive.shape === 'box') return <Primitive primitive={primitive} scale={scale} />;
  const material = finishes[primitive.finish] || finishes.polymer;
  const position = primitive.center_mm.map((n) => n * scale) as Vector3;
  const size = primitive.size_mm.map((n) => Math.max(n * scale, .0001)) as Vector3;
  return <mesh position={position} scale={size} castShadow receiveShadow>
    {primitive.shape === 'cylinder' ? <cylinderGeometry args={[.5, .5, 1, 32]} /> : <sphereGeometry args={[.5, 24, 16]} />}
    <meshStandardMaterial color={primitive.color ?? material.color} metalness={material.metalness} roughness={material.roughness} transparent={material.opacity != null} opacity={material.opacity ?? 1} depthWrite={material.opacity == null} />
  </mesh>;
}

function AnimationClock({ playing, progress, onComplete, motionVersion, step, stepIndex }: { playing: boolean; progress: RefObject<number>; onComplete: () => void; motionVersion: number; step: ConceptStep | undefined; stepIndex: number }) {
  const invalidate = useThree((state) => state.invalidate);
  const completed = useRef(false);
  useLayoutEffect(() => { progress.current = 0; completed.current = false; invalidate(); }, [stepIndex, progress, invalidate]);
  useEffect(() => { if (playing) completed.current = false; invalidate(); }, [playing, motionVersion, invalidate]);
  useFrame((_, delta) => {
    if (!playing || completed.current) return;
    const duration = step?.index_chain ? conceptIndexDuration(step.stops ?? []) : conceptDuration(step?.stops ?? []);
    progress.current += Math.min(delta, .1) / duration;
    if (progress.current >= 1) { completed.current = true; progress.current = step?.index_chain ? 1 : 0; onComplete(); }
    else invalidate();
  }, -1);
  return null;
}

function ComponentGroup({ component, step, progress, scale, footprint, pivot, selected }: { selected: boolean; component: ConceptComponent; step: ConceptStep | undefined; progress: RefObject<number>; scale: number; footprint: [number, number]; pivot: Vector3 }) {
  const group = useRef<Group>(null);
  const scratch = useRef(new ThreeVector3());
  const axis = useRef(new ThreeVector3());
  const rest: Vector3 = [(component.position_mm[0] - footprint[0] / 2) * scale, component.position_mm[1] * scale, (component.position_mm[2] - footprint[1] / 2) * scale];
  useFrame(() => {
    if (!group.current) return;
    const moving = step && (step.moving_component_keys?.includes(component.key) ?? component.key === step.moving_key);
    const travel = moving && !step.index_chain ? conceptTravelAt(progress.current, step.stops ?? []) : 0;
    const offset = moving ? step.translation_mm : [0, 0, 0];
    axis.current.set(step?.rotation_axis === 'x' ? 1 : 0, step?.rotation_axis === 'y' ? 1 : 0, step?.rotation_axis === 'z' ? 1 : 0);
    const angle = moving && step.index_chain ? conceptIndexAngle(step.start_rotation_deg ?? 0, step.rotation_delta_deg ?? 0, progress.current, step.stops ?? []) : moving ? (step.rotation_deg ?? 0) * travel : 0;
    if (moving && step.rotation_axis && angle) group.current.quaternion.setFromAxisAngle(axis.current, angle * Math.PI / 180);
    else group.current.quaternion.identity();
    scratch.current.set(rest[0] - pivot[0], rest[1] - pivot[1], rest[2] - pivot[2]).applyQuaternion(group.current.quaternion);
    group.current.position.set(pivot[0] + scratch.current.x + offset[0] * travel * scale, pivot[1] + scratch.current.y + offset[1] * travel * scale, pivot[2] + scratch.current.z + offset[2] * travel * scale);
  });
  return <group ref={group} position={rest}>{selected && <mesh><boxGeometry args={component.size_mm.map(value => value * scale * 1.04) as Vector3} /><meshBasicMaterial color="#db7418" wireframe depthTest={false} /></mesh>}{component.primitives.map((primitive, index) => <ShapedPrimitive key={index} primitive={primitive} scale={scale} />)}</group>;
}

function ConceptScene({ design, step, progress, turn, playing, onComplete, motionVersion, stepIndex, hiddenKeys, selectedId }: { selectedId?: string | null; design: ConceptDesign; step: ConceptStep | undefined; progress: RefObject<number>; turn: number; playing: boolean; onComplete: () => void; motionVersion: number; stepIndex: number; hiddenKeys: Set<string> }) {
  const scale = 1 / Math.max(...design.footprint_mm, ...design.components.flatMap((c) => [c.size_mm[1]]), 1);
  const movingOrigin = design.components.find((component) => component.key === step?.moving_key)?.position_mm ?? [0, 0, 0];
  const localPivot = step?.pivot_mm ?? [0, 0, 0];
  const pivot: Vector3 = [(movingOrigin[0] + localPivot[0] - design.footprint_mm[0] / 2) * scale, (movingOrigin[1] + localPivot[1]) * scale, (movingOrigin[2] + localPivot[2] - design.footprint_mm[1] / 2) * scale];
  const floor = Math.min(0, ...design.components.flatMap((c) => c.primitives.map((p) => c.position_mm[1] + p.center_mm[1] - p.size_mm[1] / 2))) * scale;
  return <Canvas aria-label="Interactive concept model" orthographic shadows="percentage" frameloop="demand" camera={{ position: [2.4, 2, 3], zoom: 250, near: .001, far: 100 }} dpr={[1, 1.5]}>
    <color attach="background" args={['#e8f0ee']} />
    <ambientLight intensity={1.35} />
    <directionalLight position={[3, 5, 4]} intensity={2.4} castShadow shadow-mapSize={[1024, 1024]} shadow-camera-left={-3} shadow-camera-right={3} shadow-camera-top={3} shadow-camera-bottom={-3} />
    <directionalLight position={[-3, 2, -2]} intensity={1.1} />
    <Bounds fit clip observe margin={1.15} maxDuration={0}>
      <group rotation={[0, turn * Math.PI / 4, 0]}>
        {design.bounds_mm && <mesh visible={false} position={[(design.bounds_mm.min[0] + design.bounds_mm.max[0] - design.footprint_mm[0]) * scale / 2, (design.bounds_mm.min[1] + design.bounds_mm.max[1]) * scale / 2, (design.bounds_mm.min[2] + design.bounds_mm.max[2] - design.footprint_mm[1]) * scale / 2]}><boxGeometry args={design.bounds_mm.max.map((value, i) => Math.max((value - design.bounds_mm!.min[i]) * scale, .001)) as Vector3} /><meshBasicMaterial /></mesh>}
        {design.components.map((component) => <group key={component.key} visible={!hiddenKeys.has(component.key)}><ComponentGroup selected={component.key === selectedId} component={component} step={step} progress={progress} scale={scale} footprint={design.footprint_mm} pivot={pivot} /></group>)}
      </group>
    </Bounds>
    <AnimationClock playing={playing} progress={progress} onComplete={onComplete} motionVersion={motionVersion} step={step} stepIndex={stepIndex} />
    <mesh receiveShadow rotation={[-Math.PI / 2, 0, 0]} position={[0, floor - .002, 0]}><planeGeometry args={[4, 4]} /><shadowMaterial opacity={.18} /></mesh>
    <OrbitControls makeDefault enablePan={false} minZoom={20} maxZoom={1600} />
  </Canvas>;
}

const dimension = (value: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value);
function useReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

function StepDownload({ url, filename, label, card = false }: { url: string; filename: string; label: string; card?: boolean }) {
  const [working, setWorking] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  async function download() {
    setWorking(true); setIssue(null);
    try {
      const response = await fetch(url);
      if (!response.ok) {
        const data = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(typeof data?.detail === 'string' ? data.detail : 'The STEP file is unavailable.');
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = objectUrl; link.download = filename; link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) { setIssue(error instanceof Error ? error.message : 'The STEP file is unavailable.'); }
    finally { setWorking(false); }
  }
  return <span className={card ? 'concept-step-download concept-step-card' : 'concept-step-download'}><button type="button" aria-label={label} disabled={working} onClick={() => void download()}>{working ? 'Preparing STEP…' : card ? <>Editable model <span>STEP</span></> : 'Editable model (STEP)'}</button>{issue && <small role="status">{issue}</small>}</span>;
}

export default function ConceptWorkspace({ projectId, revision, design, panel, selectedId = null, onHideSelected, imageCapability = null }: { projectId: string; revision: number; design: ConceptDesign; panel: 'design' | 'parts' | 'instructions' | 'software'; selectedId?: string | null; onHideSelected?: () => void; imageCapability?: ImageCapability | null }) {
  const [stepIndex, setStepIndex] = useState(0);
  const progress = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [viewKey, setViewKey] = useState(0);
  const [turn, setTurn] = useState(0);
  const [motionVersion, setMotionVersion] = useState(0);
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(() => new Set());
  const reducedMotion = useReducedMotion();
  const base = `/api/projects/${encodeURIComponent(projectId)}/concept`;
  const query = `?revision=${encodeURIComponent(revision)}`;
  const step = design.steps[stepIndex];
  const firstMotion = design.steps.findIndex((item) => item.moving_key != null);
  const hasIndexedPoses = design.steps.some((item) => item.rotation_reference === 'previous_index');
  const componentNames = useMemo(() => new Map(design.components.map((c) => [c.key, c.name])), [design.components]);
  useEffect(() => { setStepIndex(0); progress.current = 0; setPlaying(false); setHiddenKeys(new Set()); }, [projectId, revision]);
  useEffect(() => { if (reducedMotion) { setPlaying(false); progress.current = 0; setMotionVersion((value) => value + 1); } }, [reducedMotion]);
  useEffect(() => { if (panel !== 'design' && panel !== 'software') setPlaying(false); }, [panel]);
  useEffect(() => { if (selectedId) setHiddenKeys(current => { if (!current.has(selectedId)) return current; const next = new Set(current); next.delete(selectedId); return next; }); }, [selectedId]);
  const selectStep = (index: number) => { setPlaying(false); progress.current = 0; setStepIndex(index); setMotionVersion((value) => value + 1); };
  const onComplete = () => {
    if (stepIndex < design.steps.length - 1) setStepIndex((index) => index + 1);
    else setPlaying(false);
  };
  const next = () => selectStep(Math.min(stepIndex + 1, design.steps.length - 1));
  return <section className={`concept-workspace concept-panel-${panel}`} aria-label="Concept workspace" data-testid="concept-workspace">
    <div className="concept-design-stage" hidden={panel !== 'design' && panel !== 'software'}>
    <header className="concept-heading"><div><p className="concept-kicker">Your proposed setup <span>Revision {revision}</span></p><h2>{design.title}</h2><p>{design.overview}</p></div><span className="concept-status">Concept design</span></header>
    <div className="concept-view">
      <ConceptScene key={viewKey} design={design} step={step} progress={progress} turn={turn} playing={playing} onComplete={onComplete} motionVersion={motionVersion} stepIndex={stepIndex} hiddenKeys={hiddenKeys} selectedId={selectedId} />
      <div className="concept-view-label"><strong>{design.components.find(component => component.key === selectedId && !hiddenKeys.has(component.key))?.name ?? 'Explore the setup'}</strong><span>Drag to rotate · scroll to zoom</span></div>

      <div className="concept-view-controls"><button type="button" aria-label="Rotate model left" onClick={() => setTurn((value) => value - 1)}>↶</button><button type="button" aria-label="Rotate model right" onClick={() => setTurn((value) => value + 1)}>↷</button><button type="button" onClick={() => { setTurn(0); setViewKey((value) => value + 1); }}>Reset view</button></div>
    </div>
    <div className="concept-facts"><div><span>Proposed footprint</span><strong>{dimension(design.footprint_mm[0])} × {dimension(design.footprint_mm[1])} mm</strong></div><div><span>Components</span><strong>{design.components.length}</strong></div><p>Illustrative geometry and motion. Fit, safety and performance require physical verification.</p></div>
    {design.components.some((component) => component.primitives.some((primitive) => primitive.color)) && <p className="concept-color-note">Colors are illustrative. Use component names and positions to identify parts.</p>}
    {step && <details className="concept-playback" aria-label="Operating preview" open={panel === 'software' ? true : undefined}><summary>Motion preview</summary>
      <div className="concept-playback-intro"><div><h3>Operating preview</h3><p>Follow the proposed sequence. This preview does not control hardware.</p></div><span>Step {stepIndex + 1} of {design.steps.length}</span></div>
      <div className="concept-current"><div><strong>{step.name}</strong><p>{step.instruction}</p><small>{step.moving_key ? `Illustrative ${step.index_chain ? 'index movement' : 'out-and-back motion'}: ${componentNames.get(step.moving_key) || 'selected component'}. ${step.stops?.length ? 'Includes planned pauses; sensor readings and process outcomes are not simulated.' : 'Pauses and process outcomes are not modeled.'}` : 'Operator prompt · no hardware motion'}</small></div>
      <div className="concept-buttons">{!reducedMotion && <button type="button" onClick={() => { if (!playing && progress.current >= 1) { progress.current = 0; setMotionVersion((value) => value + 1); } setPlaying(!playing); }}>{playing ? 'Pause' : 'Play'}</button>}{!step.moving_key && firstMotion >= 0 && <button type="button" onClick={() => { progress.current = 0; setStepIndex(firstMotion); setMotionVersion((value) => value + 1); setPlaying(!reducedMotion); }}>{reducedMotion ? 'Go to motion step' : 'Preview movement'}</button>}<button type="button" onClick={next} disabled={stepIndex >= design.steps.length - 1}>Next step</button><button type="button" onClick={() => selectStep(0)}>Reset</button></div></div>
      {hasIndexedPoses && <p className="concept-reduced">Linked index movements continue from the previous position. Independent steps start at the home pose.</p>}
      {reducedMotion && <p className="concept-reduced">Motion is reduced in your device settings. Use Next step to review the sequence.</p>}
      {Boolean(design.work_interfaces?.length) && <details className="concept-positions"><summary>Working positions ({design.work_interfaces?.length})</summary><p>Only the listed working axes were checked against the specified target geometry; other positions were not checked. Optics, calibration and operation remain unverified.</p><ul>{design.work_interfaces?.map((position) => <li key={position.key}><strong>Proposed: {position.label}</strong><span>{componentNames.get(position.tool_key) ?? 'Selected tool'} → {componentNames.get(position.target_key) ?? 'Selected target'}</span><small>{position.step_name ? `${dimension(position.phase * 100)}% of travel during ${position.step_name}` : 'At the starting position'}</small></li>)}</ul></details>}
    </details>}
    </div>
    {panel === 'parts' && <details className="concept-visibility"><summary>Show or hide parts</summary><div><p>View only; the design and downloads stay unchanged.</p>{design.components.map((component) => <label key={component.key}><input type="checkbox" checked={!hiddenKeys.has(component.key)} onChange={(event) => { const visible = event.target.checked; if (!visible && component.key === selectedId) onHideSelected?.(); setHiddenKeys((current) => { const next = new Set(current); if (visible) next.delete(component.key); else next.add(component.key); return next; }); }} />{component.name}</label>)}<button type="button" disabled={!hiddenKeys.size} onClick={() => setHiddenKeys(new Set())}>Show all parts</button></div></details>}
    {panel !== 'design' && <div className="concept-details">
      {(panel === 'instructions' || panel === 'software') && <section><div className="concept-section-heading"><h3>Assembly and operation</h3><span>{design.steps.length} {design.steps.length === 1 ? 'step' : 'steps'}</span></div><ol className="concept-steps">{design.steps.map((item, index) => <li key={`${index}-${item.name}`}><button type="button" aria-current={index === stepIndex ? 'step' : undefined} onClick={() => selectStep(index)}><span>{index + 1}</span><div><strong>{item.name}</strong><p>{item.instruction}</p>{item.component_keys.length > 0 && <small>{item.component_keys.map((key) => componentNames.get(key)).filter(Boolean).join(', ')}</small>}</div></button><StepIllustration key={`${projectId}:${revision}:concept-step-${index + 1}`} projectId={projectId} revision={revision} stepId={`concept-step-${index + 1}`} title={item.name} capability={imageCapability} /></li>)}</ol></section>}
      {panel === 'parts' && <section><div className="concept-section-heading"><h3>Components</h3><span>{design.components.length} items</span></div><p className="concept-intro">Each entry represents one proposed component. References are candidates; confirm compatibility before building.</p><ul className="concept-parts">{design.components.map((component) => <li key={component.key}><strong>{component.name}</strong><p>{component.role}</p><p className="concept-part-kind">Quantity: 1 · {component.source ? 'Sourcing reference' : 'Custom concept'}</p><dl><dt>Assembly</dt><dd>{component.assembly}</dd><dt>Check</dt><dd>{component.check}</dd></dl><StepIllustration key={`${projectId}:${revision}:concept-${component.key}`} projectId={projectId} revision={revision} stepId={`concept-${component.key}`} title={`Assemble ${component.name}`} capability={imageCapability} /><div className="concept-links"><a href={`${base}/parts/${encodeURIComponent(component.key)}.stl${query}`} download>Download model (STL)</a><StepDownload url={`${base}/parts/${encodeURIComponent(component.key)}.step${query}`} filename={`${component.key}.step`} label={`Download ${component.name} editable model (STEP)`} />{component.source && <a href={component.source.url} target="_blank" rel="noopener noreferrer">{component.source.title} ↗</a>}</div></li>)}</ul></section>}
    </div>}
    {panel === 'parts' && Boolean(design.supplies?.length) && <section className="concept-supplies"><div className="concept-section-heading"><h3>Additional supplies</h3><span>Not shown in the model</span></div><p className="concept-intro">These items support the setup and are included in the parts list. Sourcing references identify candidates; catalog searches require product selection.</p><ul className="concept-parts">{design.supplies?.map((supply) => <li key={supply.key}><strong>{supply.name}</strong><p>{supply.role}</p><p className="concept-part-kind">Quantity: {supply.quantity} {supply.unit} · {supply.source ? 'Sourcing reference' : 'Selection required'}</p>{Boolean(supply.component_names?.length) && <p className="concept-part-kind">For: {supply.component_names?.join(', ')}</p>}{supply.source ? <a href={supply.source.url} target="_blank" rel="noopener noreferrer">{supply.source.title} ↗</a> : supply.catalog_search_url && <a href={supply.catalog_search_url} target="_blank" rel="noopener noreferrer">Search US catalog ↗</a>}</li>)}</ul></section>}
    {(panel === 'instructions' || panel === 'software') && <section className="concept-software"><div className="concept-section-heading"><h3>Controller software</h3></div><p><strong>Proposed sequence:</strong> {design.software.controller}</p><p>The Python controller can run the sequence locally in simulation. Its optional HTTP gateway requires a separately implemented and commissioned device integration.</p><div className="concept-software-actions"><a href={`${base}/controller.py${query}`} download>Download controller (Python)</a><a href={`${base}/project.json${query}`} download>Download project data (JSON)</a><a href={`${base}/gateway-config.json${query}`} download>Download gateway configuration (JSON)</a><a href={`${base}/guide.html${query}#software`} target="_blank" rel="noopener noreferrer">Read software and commissioning guide ↗</a></div><p>Keep the controller and project data together, then run <code>python controller.py project.json --simulate</code>.</p>{design.software.interfaces.length > 0 && <p><strong>Interfaces to specify:</strong> {design.software.interfaces.join(', ')}</p>}<div className="concept-software-columns"><div><h4>Setup</h4><ol>{design.software.setup.map((item, index) => <li key={index}>{item}</li>)}</ol></div><div><h4>Checks</h4><ul>{design.software.checks.map((item, index) => <li key={index}>{item}</li>)}</ul></div></div></section>}
    {(panel === 'instructions' || panel === 'software') && design.open_questions.length > 0 && <section className="concept-questions"><h3>Questions to resolve</h3><ul>{design.open_questions.map((question, index) => <li key={index}>{question}</li>)}</ul></section>}
    {panel === 'design' && <a className="concept-quick-export" href={`${base}/package.zip${query}`} download>Download project package (ZIP)</a>}
    {panel !== 'design' && <section className="concept-downloads"><div><h3>Take the design with you</h3><p>Files reflect revision {revision}. Review dimensions and interfaces before fabrication. The ZIP contains meshes, parts, guide and software. STEP files are separate editable concept solids and require the optional CAD installation.</p><p><a href={`${base}/package.zip${query}`} download>Download project package (ZIP)</a></p></div><div className="concept-download-links"><a href={`${base}/parts.csv${query}`} download>Parts list <span>CSV</span></a><a href={`${base}/machine.stl${query}`} download>Complete model <span>STL</span></a><StepDownload card url={`${base}/machine.step${query}`} filename="machine.step" label="Download editable complete model (STEP)" /><a href={`${base}/guide.html${query}`} download>Assembly guide <span>HTML</span></a><a href={`${base}/controller.py${query}`} download>Controller software <span>Python</span></a><a href={`${base}/gateway-config.json${query}`} download>Gateway configuration <span>JSON</span></a><a href={`${base}/project.json${query}`} download>Project data <span>JSON</span></a></div></section>}
  </section>;
}
