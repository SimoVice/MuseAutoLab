import PartsProposal from './PartsProposal';
import ProjectNotes from './ProjectNotes';
import SoftwareWorkspace from './SoftwareWorkspace';
import PoweredByMeta from './PoweredByMeta';
import ProjectLibrary from './ProjectLibrary';
import type { LibraryOpen, SavedEntry } from './ProjectLibrary';
import BenchStationPanel from './BenchStationPanel';
import ConceptWorkspace from './ConceptWorkspace';
import ConceptPricing from './ConceptPricing';
import FunctionalPlan from './FunctionalPlan';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Scene from './Scene';
import SelectedPlatformPreview from './SelectedPlatformPreview';
import OperatingPreview from './OperatingPreview';
import { compileMotionPlan } from './motionPlan';
import type { MotionMode } from './motionPlan';
import PresentationStage from './PresentationStage';
import ModelSelector from './ModelSelector';
import type { ImageCapability, VoiceCapability } from './ModelSelector';
import IllustrationPanel from './IllustrationPanel';
import { StepIllustrationProvider } from './StepIllustration';
import VoiceDictation from './VoiceDictation';
import AgentActivity, { activityCopy, nextDesignPaint } from './AgentActivity';
import type { AgentPhase } from './AgentActivity';
import { watchChatActivity } from './chatActivity';
import type { RequestActivity } from './chatActivity';
import AssistantMessage from './AssistantMessage';
import ProjectResources from './ProjectResources';
import CostSummary from './CostSummary';
import type { CostEstimateState } from './CostSummary';
import LabwareRackPanel from './LabwareRackPanel';
import MicroplatePanel from './MicroplatePanel';
import TipRackOptions, { tipDimensions } from './TipRackOptions';
import ProjectFiles from './ProjectFiles';
import PhysicsPanel from './PhysicsPanel';
import CameraPanel from './CameraPanel';
import DesignSources from './DesignSources';
import './chat-workspace.css';
import type { ConversationEntry, PhysicsView, PreparationPlan, ProcurementReport, Project, ProjectBrief, ProjectResponse } from './types';

const WELCOME = 'What would you like to automate in your lab? Describe the task and what makes it difficult.';
const LIQUID_NOTE = 'Develop a sequence of operations, or use this brief to design the equipment, model its moving parts and prepare assembly instructions.';
const LOCAL_PROJECT = 'museautolab.workspace.v1';

type OpenedProject = ProjectResponse & { conversation?: { role: 'user' | 'assistant'; content: string }[] };
type ActionRun = { kind: string; status: 'accepted' | 'rejected' | 'failed' | 'ready'; message?: string; model?: string };
type ChatResponse = ProjectResponse & { action_runs?: ActionRun[] };
type WorkspaceRecovery = { project: Project; messages: ConversationEntry[]; input: string; notice: string | null; snapshot: string | null; title: string };

function restoredMessages(data: OpenedProject): ConversationEntry[] {
  return [{ id: 0, role: 'assistant', text: WELCOME }, ...(data.conversation ?? []).map((entry, index) => ({
    id: index + 1, role: entry.role, text: entry.role === 'assistant' ? entry.content.split('\n\nReviewed references:\n')[0] : entry.content,
    references: entry.role === 'assistant' ? data.project.design_basis?.references.filter(
      (ref) => entry.content.includes(`[${ref.id}]`),
    ) : [],
  }))];
}

function readableError(message: string) {
  return message.replace(/\b(stock_concentration|target_concentrations|final_volume|workspace_width_mm)\b/g, (field) => ({
    stock_concentration: 'stock concentration',
    target_concentrations: 'target concentrations',
    final_volume: 'final volume',
    workspace_width_mm: 'available width',
  }[field] ?? field));
}

async function request(path: string, body?: unknown, signal?: AbortSignal, requestId?: string): Promise<ProjectResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(requestId ? { 'X-Chat-Request-Id': requestId } : {}) },
    signal,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const details = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : null;
    throw new Error(typeof details === 'string' ? readableError(details) : `Request failed (${response.status}). Please try again.`);
  }
  if (!data || typeof data !== 'object' || !('project' in data)) throw new Error('The server returned an incomplete response. Please try again.');
  return data as ProjectResponse;
}

function Icon({ name, size = 18 }: { name: 'send' | 'rotate' | 'spark' | 'check' | 'cube'; size?: number }) {
  const paths: Record<typeof name, React.ReactNode> = {
    send: <><path d="m4 12 15-8-5 16-3-6-7-2Z" /><path d="m11 14 8-10" /></>,
    rotate: <><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v5h-5" /></>,
    spark: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" /><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15Z" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    cube: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function formatDimension(value: number) { return new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value); }

function formatVolumeUl(value: number) {
  return `${new Intl.NumberFormat('en', { maximumSignificantDigits: 6 }).format(value)} µL`;
}



function planStatusLabel(status: PreparationPlan['status']) {
  if (status === 'ready') return 'Ready';
  if (status === 'invalid') return 'Needs attention';
  return 'Incomplete';
}

function workflowStage(value: string | undefined) { return value === 'supported_concept' ? 'Concept available' : value === 'planning' ? 'Concept planning' : 'Workflow discovery'; }

function briefEntries(brief: ProjectBrief | null | undefined): { key: keyof ProjectBrief; label: string; value: string }[] {
  if (!brief) return [];
  const labels: { key: keyof ProjectBrief; label: string }[] = [
    { key: 'objective', label: 'Objective' },
    { key: 'process', label: 'Process' },
    { key: 'materials', label: 'Materials' },
    { key: 'equipment', label: 'Equipment' },
    { key: 'constraints', label: 'Constraints' },
  ];
  return labels
    .map(({ key, label }) => ({ key, label, value: (brief[key] ?? '').trim() }))
    .filter((entry) => entry.value !== '');
}

function sameDesign(a: Project | null, b: Project): boolean {
  const renderedDesign = (project: Project | null) => project ? {
    available: Boolean(project.engineering_design),
    custom: project.concept_design,
    station: project.bench_station,
    components: project.design.components.map(({ label: _label, ...component }) => component),
    foundation: project.design.foundation,
    platform: project.design.platform?.id,
    rack: project.labware_rack ? { geometry: project.labware_rack.geometry, spec: project.labware_rack.spec } : null,
    plate: project.labware_plate ? { profile: project.labware_plate.profile_id, geometry: project.labware_plate.geometry, wells: project.labware_plate.derived.wells } : null,
    tips: project.tip_rack ? { profile: project.tip_rack.profile_id, geometry: project.tip_rack.geometry, size: project.tip_rack.size_mm } : null,
    inspection: project.inspection_extension ? { components: project.inspection_extension.components, poses: project.inspection_extension.pose_frames } : null,
  } : null;
  return JSON.stringify(renderedDesign(a)) === JSON.stringify(renderedDesign(b));
}

export default function App({ hosted = false, account = '', onSignOut = async () => {} }: { hosted?: boolean; account?: string; onSignOut?: () => Promise<void> }) {
  const [softwareOpen, setSoftwareOpen] = useState(true);
  const [hardwareDestination, setHardwareDestination] = useState<'design' | 'parts' | 'instructions'>('design');
  const [costVersion, setCostVersion] = useState(0);
  const [costRefreshToken, setCostRefreshToken] = useState(0);
  const [costState, setCostState] = useState<CostEstimateState>({ loading: false, issue: null, updated: false });
  const handleCostState = useCallback((state: CostEstimateState) => {
    setCostState(state);
    if (state.updated) setCostVersion(value => value + 1);
  }, []);
  const [resourceNavigation, setResourceNavigation] = useState(0);
  const [resourcePanel, setResourcePanel] = useState<'parts' | 'instructions'>('parts');
  const resourceAnchor = useRef<HTMLDivElement | null>(null);
  const openHardware = (panel?: 'parts' | 'instructions') => {
    setSoftwareOpen(false); setPlaying(false); setMobileView('design'); setHardwareDestination(panel ?? 'design');
    if (panel) { setResourcePanel(panel); setResourceNavigation(value => value + 1); window.setTimeout(() => { resourceAnchor.current?.scrollIntoView({ block: 'start', behavior: 'instant' }); resourceAnchor.current?.focus({ preventScroll: true }); }, 50); }
  };
  const [savedTitle, setSavedTitle] = useState('');
  const runtimeKey = `museautolab.hosted.${account}`;
  const [project, setProject] = useState<Project | null>(null);
  const [procurementReport, setProcurementReport] = useState<ProcurementReport | null>(null);
  const [messages, setMessages] = useState<ConversationEntry[]>([{ id: 0, role: 'assistant', text: WELCOME }]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [input, setInput] = useState(() => {
    try { return hosted ? sessionStorage.getItem(`${runtimeKey}.draft`) ?? '' : ''; } catch { return ''; }
  });
  useEffect(() => {
    if (hosted) { try { sessionStorage.setItem(`${runtimeKey}.draft`, input); } catch { /* The current draft stays available in memory. */ } }
  }, [hosted, runtimeKey, input]);
  const [mobileView, setMobileView] = useState<'design' | 'chat'>('design');
  const inputRef = useRef(input);
  inputRef.current = input;
  const [busy, setBusy] = useState(false);
  const [requestActivity, setRequestActivity] = useState<RequestActivity | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceEpoch, setVoiceEpoch] = useState(0);
  const [imageCapability, setImageCapability] = useState<ImageCapability | null>(null);
  const [voiceCapability, setVoiceCapability] = useState<VoiceCapability | null>(null);
  const [storageBusy, setStorageBusy] = useState(false);
  const [inspectionTime, setInspectionTime] = useState(0);
  const [storageNotice, setStorageNotice] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<WorkspaceRecovery | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selectedMode, setOperationMode] = useState<MotionMode>('preparation');
  const operationMode = (selectedMode === 'cold-transfer' && !project?.cold_transfer_extension) ||
    (selectedMode === 'inspection' && !project?.inspection_extension) ? 'preparation' : selectedMode;
  const pendingColdPreview = useRef(false);
  const [coldTransferFocusKey, setColdTransferFocusKey] = useState(0);
  const [operationTime, setOperationTime] = useState(0);
  const [operationSpeed, setOperationSpeed] = useState(1);
  const operationClock = useRef(0);
  const motionPlan = useMemo(() => project ? compileMotionPlan(project, operationMode) : null, [project, operationMode]);
  const motionBinding = motionPlan ? `${motionPlan.project_id}:${motionPlan.revision}:${motionPlan.mode}:${motionPlan.scope}` : '';
  const [playbackBinding, setPlaybackBinding] = useState('');
  const currentMotion = motionPlan?.status === 'ready' && playbackBinding === motionBinding;
  useEffect(() => {
    operationClock.current = 0; setOperationTime(0); setInspectionTime(0); setPlaying(false);
    setPlaybackBinding(motionBinding);
  }, [motionBinding]);
  useEffect(() => {
    if (!playing || !motionPlan || !currentMotion) return;
    let frame = 0, previous = performance.now(), lastDisplay = previous;
    const tick = (now: number) => {
      operationClock.current = Math.min(motionPlan.duration_s, operationClock.current + Math.min(0.1, (now - previous) / 1000) * operationSpeed);
      previous = now;
      if (now - lastDisplay >= 100 || operationClock.current >= motionPlan.duration_s) {
        setOperationTime(operationClock.current); lastDisplay = now;
        if (operationMode === 'inspection') setInspectionTime(operationClock.current);
      }
      if (operationClock.current >= motionPlan.duration_s) { setPlaying(false); return; }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, motionPlan, currentMotion, operationSpeed, operationMode]);
  useEffect(() => {
    const narrow = window.matchMedia('(max-width: 760px)');
    const pauseWhenHidden = () => {
      if (document.hidden || (narrow.matches && mobileView === 'chat')) {
        setPlaying(false); setOperationTime(operationClock.current);
        if (operationMode === 'inspection') setInspectionTime(operationClock.current);
      }
    };
    pauseWhenHidden();
    document.addEventListener('visibilitychange', pauseWhenHidden);
    narrow.addEventListener('change', pauseWhenHidden);
    return () => { document.removeEventListener('visibilitychange', pauseWhenHidden); narrow.removeEventListener('change', pauseWhenHidden); };
  }, [mobileView, operationMode]);
  const [resetKey, setResetKey] = useState(0);
  const [physicsView, setPhysicsView] = useState<PhysicsView | null>(null);
  const [physicsActive, setPhysicsActive] = useState(false);
  const [agentPhase, setAgentPhase] = useState<AgentPhase | null>(null);
  const [pendingActivityTitle, setPendingActivityTitle] = useState<string | null>(null);
  const [actionRuns, setActionRuns] = useState<ActionRun[]>([]);
  const lastMessage = useRef<HTMLDivElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const viewer = useRef<HTMLDivElement>(null);
  const details = useRef<HTMLDetailsElement>(null);
  const sceneCapture = useRef<(() => Promise<string>) | null>(null);
  const preparationDetails = useRef<HTMLDetailsElement>(null);
  const designInspector = useRef<HTMLDetailsElement>(null);
  const filesSection = useRef<HTMLDivElement>(null);
  const seenRevision = useRef<string | null>(null);
  const newProjectRequested = useRef(true);
  const skipRestore = useRef(false);
  const projectFile = useRef<HTMLInputElement>(null);
  const chatAbort = useRef<AbortController | null>(null);
  const sessionRef = useRef(0);
  const projectRef = useRef<Project | null>(null);
  projectRef.current = project;

  useEffect(() => {
    let active = true;
    setInitializing(true);
    setError(null);
    (async () => {
      let stored: string | null = null;
      try { if (!skipRestore.current) stored = hosted ? sessionStorage.getItem(runtimeKey) : localStorage.getItem(LOCAL_PROJECT); } catch { /* File save remains available. */ }
      skipRestore.current = false;
      if (stored) {
        let data: OpenedProject & { title?: string };
        if (hosted) {
          const response = await fetch(`/api/projects/${encodeURIComponent(stored)}`, { cache: 'no-store' });
          if (response.status === 404) { sessionStorage.removeItem(runtimeKey); data = await request('/api/projects'); }
          else { if (!response.ok) throw new Error('Your workspace could not be resumed. Try again.'); data = await response.json(); }
        } else data = await request('/api/projects/open', JSON.parse(stored)) as OpenedProject;
        if (active) {
          setProject(data.project);
          setSavedTitle(data.title ?? '');
          setMessages(restoredMessages(data));
          setStorageNotice(data.project.rebuild_notice ?? 'Resumed your last project. Previous runs can be generated again.');
        }
      } else {
        const data = await request('/api/projects');
        if (active) setProject(data.project);
      }
    })().catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Cannot connect to the local server.');
    }).finally(() => { if (active) setInitializing(false); });
    return () => { active = false; };
  }, [connectionAttempt, hosted, runtimeKey]);

  useEffect(() => {
    if (!project || initializing) return;
    if (hosted) {
      try { sessionStorage.setItem(runtimeKey, project.id); } catch { /* The saved project library remains available. */ }
      return;
    }
    const controller = new AbortController();
    fetch(`/api/projects/${encodeURIComponent(project.id)}/snapshot?revision=${project.revision}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) return;
        const snapshot = await response.json();
        if (!controller.signal.aborted) localStorage.setItem(LOCAL_PROJECT, JSON.stringify(snapshot));
      }).catch(() => { /* Explicit file saving still works when browser storage is unavailable. */ });
    return () => controller.abort();
  }, [project, initializing, hosted, runtimeKey]);

  useEffect(() => {
    if (messages.length < 2 || !conversation.current || !lastMessage.current) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const latestMessage = Array.from(conversation.current.querySelectorAll<HTMLElement>('.message-row')).at(-1);
    const bottom = Math.max(0, lastMessage.current.offsetTop - conversation.current.clientHeight + 24);
    conversation.current.scrollTo({
      // Long replies open at their beginning so the next action keeps its context.
      top: latestMessage ? Math.max(0, Math.min(bottom, latestMessage.offsetTop - 16)) : bottom,
      behavior: reducedMotion ? 'auto' : 'smooth',
    });
  }, [messages]);

  useEffect(() => {
    if (selectedId && project && !project.design.components.some((part) => part.id === selectedId)) setSelectedId(null);
  }, [project, selectedId]);

  const projectId = project?.id;
  const projectRevision = project?.revision;
  useEffect(() => {
    if (projectId == null || projectRevision == null) return;
    const key = `${projectId}:${projectRevision}`;
    if (seenRevision.current === null) {
      seenRevision.current = key;
      return;
    }
    if (seenRevision.current !== key) {
      seenRevision.current = key;
      setPlaying(false);
      setPhysicsView(null);
      setInspectionTime(0);
      setResetKey((value) => value + 1);
    }
  }, [projectId, projectRevision]);

  useEffect(() => {
    if (newProjectRequested.current && project && !initializing) {
      newProjectRequested.current = false;
      field.current?.focus({ preventScroll: true });
    }
  }, [project, initializing]);

  useEffect(() => () => { chatAbort.current?.abort(); }, []);

  const handleVisionSelect = useCallback((id: string) => {
    setSelectedId(id);
    setMobileView('design');
    requestAnimationFrame(() => viewer.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }));
  }, []);

  const handlePreviewComplete = useCallback(() => {
    setPlaying(false);
    setResetKey((value) => value + 1);
  }, []);

  const workflow = project?.workflow;
  const supportedLiquid = Boolean(workflow && workflow.kind === 'liquid_preparation' && workflow.design_available);
  const hasEngineeringDesign = Boolean(project?.engineering_design);
  const hasFoundation = Boolean(project?.design.foundation);
  const hasPlatform = Boolean(project?.design.platform);
  const recordedBrief = briefEntries(project?.brief);
  const hasBrief = recordedBrief.length > 0;
  const hasSelectedFoundation = !hasEngineeringDesign && project?.engineering?.selected_platform_id === 'jubilee';
  const hasGeneralDesign = Boolean(project?.bench_station || project?.concept_design);
  const hasWorkspaceContent = hasBrief || hasEngineeringDesign || hasSelectedFoundation || hasGeneralDesign;
  const showLiquidParams = supportedLiquid && (Boolean(workflow?.parameters_started) || project?.plan?.status === 'ready');
  const briefHref = project ? `/api/projects/${encodeURIComponent(project.id)}/brief?revision=${encodeURIComponent(String(project.revision))}` : '#';

  const coldPreviewPlan = project?.cold_transfer_extension ? compileMotionPlan(project, 'cold-transfer') : null;
  const coldPreviewUnavailable = coldPreviewPlan?.status !== 'ready';
  const showPreview = project?.plan?.status === 'ready' && hasEngineeringDesign;
  const acceptedLayoutId = project?.engineering_design?.provenance.run_id;
  useEffect(() => {
    if (actionRuns.some((run) => run.status === 'ready' && !['show_build_plan', 'show_tip_rack_options'].includes(run.kind)) && details.current) {
      details.current.open = true;
      if (designInspector.current) designInspector.current.open = true;
    }
  }, [actionRuns]);
  useEffect(() => {
    if (!acceptedLayoutId) return;
    viewer.current?.scrollIntoView({
      block: 'start',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
  }, [acceptedLayoutId]);
  useEffect(() => {
    if (!currentMotion) setPlaying(false);
    else if (pendingColdPreview.current && operationMode === 'cold-transfer') {
      pendingColdPreview.current = false; setPlaying(true);
    }
  }, [currentMotion, operationMode]);

  function previewPlateTransfer() {
    if (!project?.cold_transfer_extension || compileMotionPlan(project, 'cold-transfer').status !== 'ready') return;
    setMobileView('design'); setSoftwareOpen(false); setSelectedId(null);
    setPhysicsActive(false); setPhysicsView(null);
    setColdTransferFocusKey(value => value + 1);
    if (operationMode === 'cold-transfer' && currentMotion) {
      handleReset(); setPlaying(true);
    } else {
      pendingColdPreview.current = true; setOperationMode('cold-transfer');
    }
    requestAnimationFrame(() => viewer.current?.scrollIntoView({ block: 'start', behavior: 'instant' }));
  }
  function handlePlay() {
    if (!motionPlan || motionPlan.status !== 'ready' || !currentMotion) return;
    if (operationClock.current >= motionPlan.duration_s) { operationClock.current = 0; setOperationTime(0); }
    setPhysicsActive(false); setPhysicsView(null); setPlaying(true);
  }
  function handlePause() { setPlaying(false); setOperationTime(operationClock.current); if (operationMode === 'inspection') setInspectionTime(operationClock.current); }
  function handleReset() {
    operationClock.current = 0; setOperationTime(0); setInspectionTime(0);
    setPlaying(false);
    setResetKey((value) => value + 1);
  }
  const handlePhysicsView = useCallback((view: PhysicsView | null) => { setPhysicsView(view); }, []);
  const handlePhysicsActivate = useCallback(() => { setResetKey((value) => value + 1); setInspectionTime(0); setPlaying(false); setPhysicsActive(true); }, []);
  const uiBusy = busy || storageBusy || modelBusy;
  useEffect(() => { if (uiBusy) setPlaying(false); }, [uiBusy]);
  const appendTranscript = useCallback((text: string) => {
    const current = inputRef.current;
    const combined = current.trim() ? `${current}\n${text}` : text;
    if (combined.length > 4000) return false;
    setInput(combined);
    field.current?.focus({ preventScroll: true });
    return true;
  }, []);

  function acceptLibraryProject(data: LibraryOpen) {
    chatAbort.current?.abort(); sessionRef.current += 1;
    setVoiceEpoch(value => value + 1); setAgentPhase(null); setActionRuns([]);
    setProject(data.project); setMessages(restoredMessages(data));
    setSavedTitle(data.title);
    setRecovery(null); setSelectedId(null); setInput(''); setPlaying(false);
    setPhysicsView(null); setPhysicsActive(false); setInspectionTime(0);
    setProcurementReport(null); setResetKey(value => value + 1);
    setStorageNotice(data.project.rebuild_notice ?? `Opened ${data.title}.`);
    field.current?.focus({ preventScroll: true });
  }
  function acceptSavedProject(entry: SavedEntry) {
    setSavedTitle(entry.title);
    setStorageNotice(`Saved ${entry.title}. Project changes now save automatically.`);
  }

  async function saveProject() {
    if (!project || uiBusy) return;
    setStorageBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/snapshot?revision=${project.revision}`);
      if (!response.ok) throw new Error('The project could not be saved. Try again.');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `museautolab-r${project.revision}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStorageNotice('Project saved to file, including the latest design and conversation.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The project could not be saved.'); }
    finally { setStorageBusy(false); }
  }

  async function openProject(file: File) {
    if (uiBusy || initializing) return;
    chatAbort.current?.abort();
    setVoiceEpoch((value) => value + 1);
    setStorageBusy(true);
    setError(null);
    try {
      if (file.size > 256 * 1024) throw new Error('Choose a project file smaller than 256 KB.');
      const raw = await file.text();
      const response = await fetch('/api/projects/open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw,
      });
      const data = await response.json() as OpenedProject & { detail?: string };
      if (!response.ok || !data.project) throw new Error(data.detail ?? 'Choose a valid MuseAutoLab project file.');
      sessionRef.current += 1;
      setAgentPhase(null);
      setActionRuns([]);
      setProject(data.project);
      setSavedTitle(''); setProcurementReport(null);
      setRecovery(null);
      setMessages(restoredMessages(data));
      setSelectedId(null);
      setInput('');
      setPlaying(false);
      setPhysicsView(null);
      setPhysicsActive(false);
      setStorageNotice(data.project.rebuild_notice ?? 'Project reopened. Geometry was rebuilt; previous runs are ready to regenerate.');
      field.current?.focus({ preventScroll: true });
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The project could not be opened.'); }
    finally { setStorageBusy(false); if (projectFile.current) projectFile.current.value = ''; }
  }

  async function handleNewProject() {
    if (uiBusy || initializing) return;
    setVoiceEpoch((value) => value + 1);
    setStorageBusy(true); setError(null);
    try {
      const replacement = await request('/api/projects');
      let snapshot: string | null = null;
      try { if (!hosted) snapshot = localStorage.getItem(LOCAL_PROJECT); } catch { /* In-memory undo remains available. */ }
      const canRecover = project && (messages.length > 1 || input.trim() || hasBrief || hasEngineeringDesign);
      if (canRecover) {
        setRecovery({ project, messages, input, notice: storageNotice, snapshot, title: savedTitle });
      }
      chatAbort.current?.abort();
      sessionRef.current += 1;
      setAgentPhase(null); setActionRuns([]);
      setStorageNotice(canRecover || recovery ? 'New project ready. Your previous workspace can be restored with Undo.' : null);
      newProjectRequested.current = true;
      seenRevision.current = null;
      setProject(replacement.project);
      setSavedTitle(''); setProcurementReport(null);
      setMessages([{ id: Date.now(), role: 'assistant', text: WELCOME }]);
      setSelectedId(null); setInput(''); setPlaying(false);
      setPhysicsView(null); setPhysicsActive(false); setInspectionTime(0);
      setResetKey((value) => value + 1);
    } catch (reason) {
      setError(`New project could not be created. Your workspace and draft are kept. Try New project again. ${reason instanceof Error ? reason.message : ''}`);
    } finally { setStorageBusy(false); }
  }

  function undoNewProject() {
    if (!recovery || uiBusy) return;
    sessionRef.current += 1;
    setVoiceEpoch((value) => value + 1);
    setSavedTitle(recovery.title); setProcurementReport(null);
    setProject(recovery.project); setMessages(recovery.messages); setInput(recovery.input);
    setStorageNotice(recovery.notice ?? 'Previous workspace restored.');
    setRecovery(null); setSelectedId(null); setPlaying(false); setActionRuns([]);
    try { if (!hosted && recovery.snapshot) localStorage.setItem(LOCAL_PROJECT, recovery.snapshot); } catch { /* Explicit project saving remains available. */ }
    field.current?.focus({ preventScroll: true });
  }

  const captureIllustration = useCallback(async () => {
    if (!sceneCapture.current) throw new Error('The model view is not ready yet. Wait for it to load, then try again.');
    return sceneCapture.current();
  }, []);

  function reviewPreparationPlan() {
    setMobileView('design');
    if (designInspector.current) designInspector.current.open = true;
    requestAnimationFrame(() => {
      if (preparationDetails.current) preparationDetails.current.open = true;
      preparationDetails.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      preparationDetails.current?.focus({ preventScroll: true });
    });
  }

  function showProjectFiles() {
    setMobileView('design');
    if (designInspector.current) designInspector.current.open = true;
    if (details.current) details.current.open = true;
    requestAnimationFrame(() => {
      filesSection.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      filesSection.current?.focus({ preventScroll: true });
    });
  }

  useEffect(() => {
    if (agentPhase !== 'ready') return;
    const timer = window.setTimeout(() => setAgentPhase(null), 1800);
    return () => window.clearTimeout(timer);
  }, [agentPhase]);

  async function presentProject(next: Project, signal: AbortSignal, session: number) {
    const active = () => !signal.aborted && sessionRef.current === session;
    if (!active()) return false;
    const changed = !sameDesign(projectRef.current, next);
    if (changed) {
      setAgentPhase('updating');
      await nextDesignPaint(signal);
      if (!active()) return false;
    }
    if (next.cold_transfer_extension && !projectRef.current?.cold_transfer_extension) {
      setOperationMode('cold-transfer');
      setMobileView('design');
    } else if (projectRef.current?.cold_transfer_extension && !next.cold_transfer_extension) {
      setOperationMode('preparation');
    }
    if (next.design_workflow?.machine_approved && !projectRef.current?.design_workflow?.machine_approved) setSoftwareOpen(true);
    setProject(next);
    if (changed) {
      await nextDesignPaint(signal);
      if (!active()) return false;
    }
    setAgentPhase(changed ? 'ready' : null);
    return true;
  }

  async function send(event?: FormEvent, fromBrief = false) {
    event?.preventDefault();
    const message = fromBrief ? 'Design a custom laboratory assembly for my recorded brief.' : input.trim();
    if (!project || !message || uiBusy || voiceBusy) return;
    if (message.length > 4000) { setError('The message exceeds 4,000 characters. Shorten it before sending; your draft is kept.'); return; }
    setMobileView('chat');
    setRequestActivity(null);
    const session = sessionRef.current;
    chatAbort.current?.abort();
    const controller = new AbortController();
    chatAbort.current = controller;
    setBusy(true);
    setPendingActivityTitle(null);
    setAgentPhase('pending');
    setError(null);
    setInput('');
    setMessages((current) => [...current, { id: Date.now(), role: 'user', text: message }]);
    const requestId = crypto.randomUUID();
    const stopActivity = watchChatActivity(project.id, requestId, controller.signal, activity => {
      if (sessionRef.current === session) setRequestActivity(activity);
    });
    try {
      const root = `/api/projects/${encodeURIComponent(project.id)}`;
      const raw = await request(root + (fromBrief ? '/concept' : '/messages'),
        fromBrief ? { project_revision: project.revision } : { message, project_revision: project.revision }, controller.signal, requestId) as ChatResponse;
      stopActivity();
      setRequestActivity(null);
      if (controller.signal.aborted || sessionRef.current !== session) return;
      const runs = Array.isArray(raw.action_runs) ? raw.action_runs : [];
      if (!await presentProject(raw.project, controller.signal, session)) return;
      setActionRuns(runs);
      const failed = runs.find((run) => run.status === 'rejected' || run.status === 'failed');
      if (raw.assistant_message) {
        setMessages((current) => [...current, {
          id: Date.now() + 1, role: 'assistant', text: raw.assistant_message as string,
          references: raw.recommendations?.map((item) => item.reference),
        }]);
      }
      if (failed) setError(failed.message || 'That change was not applied. The current approved design is unchanged. Try a smaller request in chat.');
    } catch (reason) {
      if (controller.signal.aborted || sessionRef.current !== session) return;
      setAgentPhase(null);
      setInput(message);
      setError(reason instanceof Error ? reason.message : 'The request could not be completed. Please try again.');
    } finally {
      stopActivity();
      if (!controller.signal.aborted && sessionRef.current === session) {
        setRequestActivity(null);
        setBusy(false);
      }
    }
  }

  async function confirm() {
    if (!project || uiBusy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/approve-machine`, { project_revision: project.revision });
      setProject(result.project); setSoftwareOpen(true);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The design could not be confirmed.');
    } finally { setBusy(false); }
  }

  async function chooseOption(groupId: string, optionId: string) {
    if (groupId === 'tip-rack-options') { await chooseTipRack(optionId); return; }
    if (!project || uiBusy) return;
    const session = sessionRef.current;
    const controller = new AbortController();
    chatAbort.current?.abort();
    chatAbort.current = controller;
    setPendingActivityTitle(null);
    setAgentPhase('pending');
    setBusy(true);
    setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/configuration`, {
        selections: { [groupId]: optionId },
      }, controller.signal);
      if (!await presentProject(result.project, controller.signal, session)) return;
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      if (controller.signal.aborted || sessionRef.current !== session) return;
      setAgentPhase(null);
      setError(reason instanceof Error ? reason.message : 'The component choice could not be applied.');
    } finally { if (!controller.signal.aborted && sessionRef.current === session) setBusy(false); }
  }

  async function chooseTipRack(profileId: string) {
    if (!project || uiBusy) return;
    const session = sessionRef.current;
    const controller = new AbortController();
    chatAbort.current?.abort();
    chatAbort.current = controller;
    setPendingActivityTitle('Updating tip rack');
    setAgentPhase('pending');
    setBusy(true); setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/tip-rack-options`, {
        revision: project.revision, profile_id: profileId,
      }, controller.signal) as ChatResponse;
      if (!await presentProject(result.project, controller.signal, session)) return;
      setActionRuns(result.action_runs ?? []);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
      const failed = result.action_runs?.find((run) => run.status === 'failed' || run.status === 'rejected');
      if (failed) setError(failed.message ?? 'That rack could not be applied. Revise the request in chat.');
      if (JSON.stringify(project.tip_rack) !== JSON.stringify(result.project.tip_rack)) setSelectedId('tip-rack');
    } catch (reason) {
      if (controller.signal.aborted || sessionRef.current !== session) return;
      setAgentPhase(null);
      setError(reason instanceof Error ? reason.message : 'The tip rack choice could not be applied. Try again.');
    } finally { if (!controller.signal.aborted && sessionRef.current === session) setBusy(false); }
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  const part = hasEngineeringDesign ? project?.design.components.find((component) => component.id === selectedId) : undefined;
  const bounds = project?.cold_transfer_extension?.assembly_bounds ??
    project?.inspection_extension?.assembly_bounds ?? project?.design.assembly_bounds;
  const dimensions = hasEngineeringDesign ? bounds ? {
    width_mm: bounds.max_mm[0] - bounds.min_mm[0], depth_mm: bounds.max_mm[2] - bounds.min_mm[2],
    height_mm: bounds.max_mm[1] - bounds.min_mm[1],
  } : project?.design.footprint : undefined;
  const summary = project?.summary;
  const status = project?.design.constraint_status;
  const plan = supportedLiquid ? (project?.plan ?? null) : null;
  const fields = [
    { label: 'Stock', value: summary?.stock_concentration },
    { label: 'Targets', value: summary?.target_concentrations },
    { label: 'Final volume', value: summary?.final_volume },
    { label: 'Equipment', value: summary?.equipment },
    { label: 'Available width', value: summary?.workspace_width_mm != null ? `${formatDimension(summary.workspace_width_mm)} mm` : null },
  ];
  const currentProcurement = procurementReport?.project_id === project?.id && procurementReport?.project_revision === project?.revision ? procurementReport : null;
  const isConfirmed = project?.status === 'confirmed';
  const headerLabel = hasWorkspaceContent ? 'Lab automation project' : 'New automation project';
  const showPhotoCheck = Boolean(project?.inspection_extension) || actionRuns.some((run) => run.kind === 'show_photo_check');
  const requestedSources = actionRuns.some((run) => run.kind === 'show_sources' && run.status === 'ready');
  const requestedPhoto = actionRuns.some((run) => run.kind === 'show_photo_check' && run.status === 'ready');
  const requestedBuildPlan = actionRuns.some((run) => run.kind === 'show_build_plan' && run.status === 'ready');

  const preparationPanel = showLiquidParams && project?.design_workflow?.machine_approved && plan?.status === 'ready' && (
              <details className="prep-plan" ref={preparationDetails} tabIndex={-1} aria-label="Preparation plan">
                <summary><span>Preparation plan <small className="prep-plan-preview">{plan?.steps.length ? `${plan.steps.length} targets · ${plan.final_volume_ul != null ? formatVolumeUl(plan.final_volume_ul) : 'Volume pending'} per ${project?.labware_plate ? 'well' : 'tube'}` : 'Create the recipe in Software & protocols'}</small></span><span className="prep-plan-status">{plan ? planStatusLabel(plan.status) : 'Awaiting details'}</span></summary>
                <div className="summary-card">
                  <div className="summary-heading"><div><h3>Preparation details</h3><p>Current saved recipe for this workstation.</p></div><span>{fields.filter((entry) => entry.label !== 'Available width' && entry.value).length}/4 required</span></div>
                  <dl>{fields.map((entry) => <div key={entry.label}><dt>{entry.label}</dt><dd className={entry.value ? '' : 'missing'}>{entry.value || (entry.label === 'Available width' ? 'Optional' : 'Not specified')}</dd></div>)}</dl>
                  <button className="confirm-button" type="button" onClick={() => setSoftwareOpen(true)}>Open software & protocols</button>
                  <p className="summary-note">Edit the recipe and review its program in Software &amp; protocols. Component fit and laboratory performance remain to be verified.</p>
                </div>
                {project && plan == null && (
                  <div className="plan-card" aria-live="polite">
                    <div className="plan-heading">
                      <div>
                        <h3>Volumes per target</h3>
                        <p>Direct dilution · one {project.labware_plate ? 'well' : 'tube'} per target</p>
                      </div>
                      <span className="plan-status plan-status-missing">Unavailable</span>
                    </div>
                    <p className="plan-message">The preparation plan is not available yet. It will appear here once the server provides it.</p>
                  </div>
                )}
                {project && plan && (
                  <div className="plan-card" aria-live="polite">
                    <div className="plan-heading">
                      <div>
                        <h3>Volumes per target</h3>
                        <p>Direct dilution · one {project?.labware_plate ? 'well' : 'tube'} per target · no serial dilutions</p>
                      </div>
                      <span className={`plan-status plan-status-${plan.status}`}>{planStatusLabel(plan.status)}</span>
                    </div>
                    <p className="plan-message">{plan.message}</p>
                    <div className="plan-meta">
                      <span><strong>Stock:</strong> {plan.stock ?? project.summary.stock_concentration ?? 'Not specified'}</span>
                      <span><strong>Final volume:</strong> {plan.final_volume_ul != null ? formatVolumeUl(plan.final_volume_ul) : project.summary.final_volume ?? 'Not specified'}</span>
                    </div>
                    {plan.steps.length > 0 ? (
                      <div className="plan-table-wrap">
                        <table className="plan-table">
                          <caption className="sr-only">{project.labware_plate ? 'Well assignments and preparation volumes in microlitres' : 'Per-target preparation volumes in microlitres'}</caption>
                          <thead>
                            <tr>
                              <th scope="col">{project.labware_plate ? 'Well / target' : 'Target'}</th>
                              <th scope="col">Stock</th>
                              <th scope="col">Diluent</th>
                              <th scope="col">Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {plan.steps.map((step, index) => (
                              <tr key={step.id}>
                                <th scope="row">{project.labware_plate ? `${project.labware_plate.compatibility.occupied_wells[index] ?? 'Unassigned'} · ${step.target}` : step.target}</th>
                                <td>{formatVolumeUl(step.stock_volume_ul)}</td>
                                <td>{formatVolumeUl(step.diluent_volume_ul)}</td>
                                <td>{formatVolumeUl(step.total_volume_ul)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="plan-empty">No per-target volumes to show yet.</p>
                    )}
                    {plan.assumptions.length > 0 && (
                      <div>
                        <p className="plan-assumptions-heading">Assumptions</p>
                        <ul className="plan-assumptions">
                          {plan.assumptions.map((assumption, index) => (
                            <li key={index}>{assumption}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </details>
  );

  return (
    <StepIllustrationProvider scope={`${runtimeKey}:${project?.id ?? ''}:${project?.revision ?? ''}`}>
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="MuseAutoLab home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span>Muse<span className="brand-accent">Auto</span>Lab</span>
        </a>
        <div className="topbar-center"><span className="topbar-divider" /> Workspace <span className="topbar-slash">/</span> <strong>{savedTitle || headerLabel}</strong></div>
        <div className="topbar-end">
          <input ref={projectFile} tabIndex={-1} type="file" accept=".json,application/json" className="sr-only" aria-label="Open saved project" onChange={(event) => { const file = event.target.files?.[0]; if (file) void openProject(file); }} />
          {hosted && <ProjectLibrary projectId={project?.id} revision={project?.revision} title={savedTitle} disabled={uiBusy || initializing} onBusy={setStorageBusy} onOpen={acceptLibraryProject} onSaved={acceptSavedProject} onSignOut={onSignOut} hasUnsaved={Boolean(input.trim() || (!savedTitle && messages.length > 1))} />}
          <button type="button" className="new-project-button" onClick={() => projectFile.current?.click()} disabled={uiBusy || initializing}>{hosted ? 'Import file' : 'Open project'}</button>
          <button type="button" className="new-project-button" onClick={() => void saveProject()} disabled={!project || uiBusy || initializing}>{hosted ? 'Export file' : 'Save project'}</button>
          <button type="button" className="new-project-button" onClick={() => void handleNewProject()} disabled={uiBusy || initializing}>New project</button>
          {recovery && <button type="button" className="new-project-button" onClick={undoNewProject} disabled={uiBusy || initializing}>Undo new project</button>}
          <span className={`connection-dot ${project ? 'connected' : ''}`} />{project ? 'Workspace ready' : initializing ? 'Connecting' : 'Offline'}
        </div>
      </header>
      {(project?.engineering_design || project?.concept_design || project?.bench_station) && !project?.design_workflow?.machine_approved && <div className="machine-approval-bar"><div><strong>Ready to program this workstation?</strong><span>Approve the equipment layout, then create its operating recipe.</span></div><button className="confirm-button" type="button" disabled={uiBusy} onClick={() => void confirm()}>{uiBusy ? 'Approving…' : 'Approve design & open software'}</button></div>}
      {(hasEngineeringDesign || hasGeneralDesign) && <nav className="software-route-nav" aria-label="Project workspace"><button type="button" aria-current={!softwareOpen && hardwareDestination === 'design' ? 'page' : undefined} onClick={() => openHardware()}>3D design</button><button type="button" aria-current={!softwareOpen && hardwareDestination === 'parts' ? 'page' : undefined} onClick={() => openHardware('parts')}>Parts &amp; prices</button><button type="button" aria-current={!softwareOpen && hardwareDestination === 'instructions' ? 'page' : undefined} onClick={() => openHardware('instructions')}>Assembly</button><button type="button" aria-current={project?.design_workflow?.machine_approved && softwareOpen ? 'page' : undefined} disabled={!project?.design_workflow?.machine_approved} title={!project?.design_workflow?.machine_approved ? 'Approve the design to open software' : undefined} onClick={() => { setSoftwareOpen(true); setPlaying(false); }}>Software &amp; protocols</button></nav>}
      {project && (hasEngineeringDesign || hasGeneralDesign) && <CostSummary project={project} report={currentProcurement} headless refreshToken={costRefreshToken} onState={handleCostState} />}
      {project?.design_workflow?.machine_approved && softwareOpen ? <SoftwareWorkspace project={project} onProject={setProject} onConversation={(message, reply) => setMessages(current => [...current, { id: Date.now(), role: 'user', text: message }, { id: Date.now() + 1, role: 'assistant', text: reply }])} /> : <>
      <nav className="workspace-switch" aria-label="Workspace view">
        <button type="button" aria-pressed={mobileView === 'design' && hasWorkspaceContent} aria-controls="design-workspace" disabled={!hasWorkspaceContent} onClick={() => setMobileView('design')}>Design</button>
        <button type="button" aria-pressed={mobileView === 'chat' || !hasWorkspaceContent} aria-controls="chat-workspace" onClick={() => setMobileView('chat')}>Chat</button>
      </nav>
      <span className="sr-only" role="status" aria-live="polite">{agentPhase ? agentPhase === 'pending' && pendingActivityTitle ? pendingActivityTitle : activityCopy[agentPhase].title : ''}</span>
      <main className={`workspace mobile-view-${mobileView}${!hasWorkspaceContent ? ' workspace-start' : ''}`}>
        <section id="design-workspace" className={`design-panel${isConfirmed && hasEngineeringDesign ? ' design-panel-confirmed' : ''}`} aria-labelledby="design-title">
          <div className="design-heading">
            <div>
              <h1 id="design-title">{headerLabel}</h1>
              {storageNotice && <details className="workspace-notice"><summary>Workspace update</summary><p className="storage-notice" role="status">{storageNotice}</p></details>}
            </div>
            <div className="revision"><span>Project revision</span><strong>{(hasBrief || hasEngineeringDesign || hasGeneralDesign) && project ? `Revision ${String(project.revision).padStart(2, '0')}` : 'Ready for your brief'}</strong>{project?.design_workflow?.machine_approved && !isConfirmed && plan?.status === 'ready' && <button className="review-plan-shortcut" type="button" onClick={reviewPreparationPlan}>Review preparation plan</button>}{isConfirmed && hasEngineeringDesign && <button className="project-files-shortcut" type="button" onClick={showProjectFiles}>Project files</button>}</div>
          </div>

          <div className={`design-content${hasEngineeringDesign ? ' design-content-engineering' : ''}`} hidden={hardwareDestination !== 'design'} tabIndex={0} aria-label="Design and project details">
          {!hasGeneralDesign && hasSelectedFoundation && <SelectedPlatformPreview />}
          {project?.concept_design ? (
            <ConceptWorkspace imageCapability={imageCapability} key={`${project.id}:${project.revision}`} projectId={project.id}
              revision={project.revision} design={project.concept_design} pricing={<ConceptPricing project={project} />} />
          ) : project?.bench_station ? <BenchStationPanel key={`${project.id}:${project.revision}`} project={project} station={project.bench_station} projectId={project.id} revision={project.revision} /> : !hasEngineeringDesign ? (
            hasBrief ? (
              <div className="planning-panel" aria-labelledby="design-title">
                <div className="planning-heading">
                  <div>
                    <h2>Project brief</h2>
                    <p>{workflow?.label ?? 'General automation'} · {supportedLiquid ? 'Planning' : workflowStage(workflow?.status)}</p>
                  </div>
                  <span className="planning-status">{supportedLiquid ? 'Planning' : workflowStage(workflow?.status)}</span>
                </div>
                <a className="brief-download" href={briefHref} download="project-brief.json">Download brief</a>
                <dl>
                  {recordedBrief.map((entry) => (
                    <div key={entry.key}><dt>{entry.label}</dt><dd>{entry.value}</dd></div>
                  ))}
                </dl>
                {!supportedLiquid ? (
                  <><p className="planning-note">{LIQUID_NOTE}</p>
                    {workflow?.kind === 'general' && (project?.brief?.objective || project?.brief?.process) &&
                      <button type="button" className="new-project-button" disabled={uiBusy || voiceBusy || Boolean(input.trim())}
                        onClick={() => void send(undefined, true)}>Design equipment from this brief</button>}
                    {project && workflow?.kind === 'general' && (project.brief?.objective || project.brief?.process) &&
                      <FunctionalPlan key={`${project.id}:${project.revision}`} id={project.id} revision={project.revision} />}</>
                ) : status === 'infeasible' ? (
                  <p className="planning-note">Requested width cannot fit this concept. Adjust the available width in chat to continue.</p>
                ) : (
                  <p className="planning-note">No machine has been generated yet. Discuss the equipment in chat so the layout can be proposed for this workflow.</p>
                )}
              </div>
            ) : hasSelectedFoundation ? null : (
              <div className="workspace-empty" aria-labelledby="design-title">
                <div className="workspace-empty-grid" aria-hidden="true" />
                <h2>Start with your goal</h2>
                <p>{initializing ? 'Preparing your workspace…' : !project ? 'Connect to the local server using Retry to begin your project.' : 'Describe the task you want to automate and what makes it difficult. Your project brief will appear here as we clarify the process, materials, equipment and constraints.'}</p>
              </div>
            )
          ) : (
            <div className="engineering-design-layout">
              <PresentationStage viewerRef={viewer} compact={isConfirmed} title={hasFoundation ? 'Jubilee workstation' : hasPlatform ? 'OT-2 setup' : 'Interactive 3D concept'}
                sourceNote={hasFoundation ? 'Approximate source CAD preview with custom layout.' : hasPlatform ? 'Schematic setup; not manufacturer CAD.' : 'Custom concept preview.'}
                actions={project?.cold_transfer_extension && <div className="stage-preview-controls" aria-label="Plate transfer playback">
                  <button type="button" className="stage-expand-button stage-preview-button"
                    title={coldPreviewUnavailable ? coldPreviewPlan?.message : undefined}
                    disabled={uiBusy || coldPreviewUnavailable}
                    onClick={operationMode === 'cold-transfer' && currentMotion && operationTime < (motionPlan?.duration_s ?? 0) && (playing || operationTime > 0) ? (playing ? handlePause : handlePlay) : previewPlateTransfer}>
                    {operationMode === 'cold-transfer' && currentMotion ? playing ? 'Pause transfer' : operationTime >= (motionPlan?.duration_s ?? 0) ? 'Replay transfer' : operationTime > 0 ? 'Resume transfer' : 'Preview plate transfer' : 'Preview plate transfer'}
                  </button>
                  {operationMode === 'cold-transfer' && currentMotion && operationTime > 0 && operationTime < (motionPlan?.duration_s ?? 0) &&
                    <button type="button" className="stage-expand-button" disabled={uiBusy} onClick={previewPlateTransfer}>Replay transfer</button>}

                </div>}
                components={project?.design.components ?? []} selectedPart={part} onSelect={setSelectedId}>
                <div aria-busy={agentPhase === 'pending' || agentPhase === 'updating'} className={`viewer-canvas${isConfirmed ? ' viewer-canvas-compact' : ''}`}>
                  {project ? <Scene coldTransferFocusKey={coldTransferFocusKey} captureRef={sceneCapture} project={project} selectedId={selectedId} onSelect={setSelectedId} inspectionTime={inspectionTime} inspectionPlayback={{ timeRef: operationClock, playing: !uiBusy && Boolean(currentMotion) && operationMode === 'inspection' && playing }} operation={{ playing: !uiBusy && operationMode !== 'inspection' && currentMotion && !physicsView ? playing : false, steps: plan?.steps ?? [], onComplete: handlePreviewComplete, resetKey, timeline: !physicsView ? motionPlan ?? undefined : undefined, time_s: currentMotion ? operationTime : 0, timeRef: operationClock }} physics={physicsView} /> : <div className="scene-fallback">{initializing ? 'Preparing your workspace…' : 'Connect the local server to view your design.'}</div>}
                  {agentPhase && <AgentActivity phase={agentPhase} pendingTitle={pendingActivityTitle} scene />}
                  <div className="scene-hint"><Icon name="rotate" size={15} /> Drag to rotate <span>·</span> Scroll to zoom</div>
                  <div className="scene-origin"><span className="origin-x">X</span><span className="origin-y">Y</span><span className="origin-z">Z</span></div>
                </div>
                <div className="viewer-bottomline">
                  <div className="footprint"><span>Workspace footprint</span><strong>{dimensions ? `${formatDimension(dimensions.width_mm)} × ${formatDimension(dimensions.depth_mm)}` : '—'} <small>mm</small></strong></div>
                  <div className="viewer-status"><span className={`status-indicator ${status === 'infeasible' ? 'warning' : ''}`} />{status === 'infeasible' ? 'Requested width cannot fit this concept' : status === 'fits' ? 'Within requested width' : 'No width constraint yet'}</div>
                </div>
              {motionPlan && <OperatingPreview machineApproved={Boolean(project?.design_workflow?.machine_approved)} plan={motionPlan} playing={playing && Boolean(currentMotion)} time={currentMotion ? operationTime : 0} speed={operationSpeed} disabled={uiBusy} hasInspection={Boolean(project?.inspection_extension)} hasColdTransfer={Boolean(project?.cold_transfer_extension)} onMode={(mode) => { handleReset(); setOperationMode(mode); }} onPlay={handlePlay} onPause={handlePause} onReset={handleReset} onSpeed={(speed) => { if ([0.5, 1, 2, 4].includes(speed)) setOperationSpeed(speed); }} onSeek={(time) => { if (!Number.isFinite(time) || !motionPlan) return; time = Math.max(0, Math.min(motionPlan.duration_s, time)); setPlaying(false); operationClock.current = time; setOperationTime(time); setPhysicsView(null); setPhysicsActive(false); if (operationMode === 'inspection') setInspectionTime(time); }} />}
              </PresentationStage>

              {project && <PartsProposal project={project} refreshKey={String(costVersion)} onSelect={handleVisionSelect} compact onOpen={() => openHardware('parts')} />}
              <details className="engineering-inspector" ref={designInspector}><summary>Specifications &amp; project files</summary><div className="engineering-inspector-scroll">
              <div className="below-viewer">

                {preparationPanel}
              </div>
              {part && <p className="selected-component-note"><strong>{part.label}</strong> · {tipDimensions(part.size)} · {part.id === 'tip-rack' && project?.tip_rack ? project.tip_rack.kind === 'commercial_reference' ? 'Pinned product reference; fit unverified' : 'Custom printable geometry; fit unverified' : 'Schematic dimensions'}</p>}

              <details className="project-details"><summary>Labware specifications</summary>
                {project && !project.labware_plate && <LabwareRackPanel brief={project.labware_brief} rack={project.labware_rack} onSelect={handleVisionSelect} targetCount={project.plan?.steps.length ?? 0} />}
                {project && <MicroplatePanel plate={project.labware_plate} onSelect={handleVisionSelect} />}
              </details>

              <details className="project-details" ref={details}>
                <summary>Project details</summary>
                {project?.engineering_guidance && <details className="photo-check" open={requestedBuildPlan || undefined}>
                  <summary>Purchase and assembly plan</summary>
                  <p className="planning-note">{project.engineering_guidance.message}</p>
                  <ol>{project.engineering_guidance.steps.map((step) => <li key={step.title}>
                    <a href={step.url} target="_blank" rel="noopener noreferrer">{step.title} ↗</a>
                    <p className="planning-note">{step.detail}</p>
                  </li>)}</ol>
                </details>}
                {hasBrief && (
                  <div className="planning-panel" aria-label="Project brief">
                    <div className="planning-heading">
                      <div>
                        <h2>Project brief</h2>
                        <p>{workflow?.label ?? 'General automation'}</p>
                      </div>
                    </div>
                    <a className="brief-download" href={briefHref} download="project-brief.json">Download brief</a>
                    <dl>
                      {recordedBrief.map((entry) => (
                        <div key={entry.key}><dt>{entry.label}</dt><dd>{entry.value}</dd></div>
                      ))}
                    </dl>
                  </div>
                )}
                {project && <DesignSources project={project} showBindings={hasEngineeringDesign} onHighlight={handleVisionSelect} />}
                {project && <div className="part-list" aria-label="Workstation components"><span>Components</span><div>{project.design.components.map((component) => <button type="button" key={component.id} className={selectedId === component.id ? 'part-chip selected' : 'part-chip'} onClick={() => setSelectedId(component.id)} aria-pressed={selectedId === component.id}>{component.label}</button>)}</div></div>}
                {showPhotoCheck && project && (
                  <details className="photo-check" open={requestedPhoto || undefined}>
                    <summary>Photo check</summary>
                    <CameraPanel project={project} onSelect={handleVisionSelect} />
                  </details>
                )}
                {project && hasEngineeringDesign && <IllustrationPanel key={`${project.id}:${project.revision}`} projectId={project.id} revision={project.revision} capability={imageCapability} disabled={uiBusy} capture={captureIllustration} />}
                {project && isConfirmed && <div ref={filesSection} tabIndex={-1} aria-label="Project files" className="project-files-section"><ProjectFiles project={project} onSelect={setSelectedId} /></div>}
                {project && !hasFoundation && !hasPlatform && showPreview && (
                  <PhysicsPanel project={project} active={physicsActive} onView={handlePhysicsView} onActivate={handlePhysicsActivate} />
                )}
              </details>
              </div></details>
            </div>
          )}
          {!hasGeneralDesign && !hasEngineeringDesign && project && <CostSummary project={project} report={currentProcurement} />}
          {!hasGeneralDesign && !hasEngineeringDesign && preparationPanel}
          {!hasGeneralDesign && !hasEngineeringDesign && project && !project.labware_plate && <LabwareRackPanel brief={project.labware_brief} rack={project.labware_rack} onSelect={handleVisionSelect} targetCount={project.plan?.steps.length ?? 0} />}
          {!hasGeneralDesign && !hasEngineeringDesign && (requestedSources || requestedBuildPlan) && project && (
            <details className="project-details" ref={details}>
              <summary>Project details</summary>
              <DesignSources project={project} showBindings={false} onHighlight={handleVisionSelect} />
              {requestedBuildPlan && project.engineering_guidance && <>
                <p>{project.engineering_guidance.message}</p>
                <ol>{project.engineering_guidance.steps.map((step) => <li key={step.title}>
                  <a href={step.url} target="_blank" rel="noopener noreferrer">{step.title} ↗</a>
                  <p>{step.detail}</p>
                </li>)}</ol>
              </>}
            </details>
          )}
          </div>
          {project && (hasEngineeringDesign || hasGeneralDesign) && hardwareDestination !== 'design' && <div className="project-resource-anchor" ref={resourceAnchor} tabIndex={-1}><ProjectResources imageCapability={imageCapability} key={`${project.id}:${project.revision}`} project={project} activePanel={resourcePanel} navigationKey={resourceNavigation} costVersion={costVersion} costLoading={costState.loading} costIssue={costState.issue} onRefreshEstimate={() => setCostRefreshToken(value => value + 1)} busy={uiBusy} onSelect={(id) => { handleVisionSelect(id); openHardware(); }} onChoose={(groupId, optionId) => void chooseOption(groupId, optionId)} onReport={setProcurementReport} instructionRequest={actionRuns.find(run => run.kind === 'show_build_plan' && run.status === 'ready')} /></div>}
        </section>

        <aside id="chat-workspace" className="conversation-panel" aria-labelledby="conversation-title">
          <div className="chat-heading"><div className="assistant-emblem"><Icon name="spark" size={19} /></div><div><h2 id="conversation-title">Design assistant</h2><p>Let’s make your workflow easier.</p></div><span className="chat-status">{project?.status === 'confirmed' ? 'Confirmed' : 'Draft'}</span>
            {project && <ProjectNotes key={project.id} project={project} busy={uiBusy}
              onSave={(id, notes) => setProject(current => current?.id === id ? { ...current, project_notes: notes } : current)} />}
          </div>
          <div className="assistant-controls">{project && <ModelSelector key={project.id} projectId={project.id} busy={uiBusy || voiceBusy} onBusyChange={setModelBusy} onVoiceCapability={setVoiceCapability} onImageCapability={setImageCapability} />}</div>
          <div className="conversation-scroll" ref={conversation}>
            <div className="chat-date">Your design conversation</div>
            {messages.map((message, index) => <div key={message.id} className={`message-row ${message.role}`}>
              {message.role === 'assistant' && <span className="message-avatar"><Icon name="spark" size={13} /></span>}
              <div><span className="message-author">{message.role === 'assistant' ? 'MuseAutoLab' : 'You'}</span><div className="message-bubble">{message.role === 'assistant' ? <AssistantMessage text={message.text} /> : message.text}</div>{message.role === 'assistant' && index === messages.length - 1 && project?.cold_transfer_extension && /preview plate transfer|cold.transfer|refrigerator|fridge/i.test(message.text) && <button type="button" className="stage-expand-button chat-preview-button" title={coldPreviewUnavailable ? coldPreviewPlan?.message : undefined} disabled={uiBusy || coldPreviewUnavailable} onClick={previewPlateTransfer}>Preview plate transfer</button>}{message.references && message.references.length > 0 && <div className="message-references">{message.references.map((ref) => <a key={ref.id} href={ref.url} target="_blank" rel="noopener noreferrer">{ref.title} ↗</a>)}</div>}</div>
            </div>)}
            {project?.tip_rack_request?.alternatives_requested && hasEngineeringDesign && (!agentPhase || agentPhase === 'ready') && <TipRackOptions project={project} busy={uiBusy} onChoose={(profileId) => void chooseTipRack(profileId)} onInspect={() => handleVisionSelect('tip-rack')} />}
            {agentPhase && <AgentActivity phase={agentPhase} pendingTitle={pendingActivityTitle} activity={requestActivity} />}
            {!agentPhase && costState.loading && <AgentActivity phase="pending" activity={{ title: 'Updating budget', detail: 'Preparing the cost estimate for the current project revision.' }} />}
            <div ref={lastMessage} />

          </div>
          <div className="composer-area">
            {error && <div className="error-message" role="alert"><span>{error}</span>{!project && <button type="button" onClick={() => setConnectionAttempt((value) => value + 1)}>Retry</button>}</div>}
            <form className="composer" onSubmit={(event) => void send(event)}>
              <label className="sr-only" htmlFor="message">Describe your workflow or request a change</label>
              <textarea id="message" ref={field} rows={2} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={keyDown} placeholder="Describe the task you want to automate…" disabled={!project || uiBusy} />
              <div className="composer-bottom"><span>Enter to send <span className="hide-small">· Shift + Enter for a new line</span></span><button type="submit" aria-label="Send message" disabled={!project || uiBusy || voiceBusy || !input.trim() || input.trim().length > 4000}><Icon name="send" size={18} /></button></div>
            </form>
            {input.length > 3600 && <p className="draft-length" role="status">{input.length.toLocaleString()} / 4,000 characters{input.length > 4000 ? ' — shorten before sending.' : ''}</p>}
            {project && <VoiceDictation key={`${project.id}:${voiceEpoch}`} capability={voiceCapability} disabled={uiBusy} onBusyChange={setVoiceBusy} onTranscript={appendTranscript} />}
            <PoweredByMeta />
          </div>
        </aside>
      </main>
      </>}
    </div>
    </StepIllustrationProvider>
  );
}
