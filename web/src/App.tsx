import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Scene from './Scene';
import ModelSelector from './ModelSelector';
import type { ImageCapability, VoiceCapability } from './ModelSelector';
import IllustrationPanel from './IllustrationPanel';
import VoiceDictation from './VoiceDictation';
import AgentActivity, { finishAgentReveal } from './AgentActivity';
import ComponentCatalog from './ComponentCatalog';
import ProjectFiles from './ProjectFiles';
import PhysicsPanel from './PhysicsPanel';
import CameraPanel from './CameraPanel';
import DesignSources from './DesignSources';
import './chat-workspace.css';
import type { ConversationEntry, PhysicsView, PreparationPlan, Project, ProjectBrief, ProjectResponse } from './types';

const WELCOME = 'What would you like to automate in your lab? Describe the task and what makes it difficult.';
const LIQUID_NOTE = 'This workflow is at the concept stage. 3D previews and build files are currently available for liquid preparation.';
const LOCAL_PROJECT = 'museautolab.workspace.v1';

type OpenedProject = ProjectResponse & { conversation?: { role: 'user' | 'assistant'; content: string }[] };
type ActionRun = { kind: string; status: 'accepted' | 'rejected' | 'failed' | 'ready'; message?: string; model?: string };
type ChatResponse = ProjectResponse & { action_runs?: ActionRun[] };
type AgentPhase = 'pending' | 'complete' | null;
type WorkspaceRecovery = { project: Project; messages: ConversationEntry[]; input: string; notice: string | null; snapshot: string | null };

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

async function request(path: string, body?: unknown, signal?: AbortSignal): Promise<ProjectResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

function formatMoney(amount: number, currency: string) {
  return new Intl.NumberFormat('en', { style: 'currency', currency }).format(amount);
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
  return JSON.stringify(a?.engineering_design ?? null) === JSON.stringify(b.engineering_design ?? null)
    && JSON.stringify(a?.inspection_extension ?? null) === JSON.stringify(b.inspection_extension ?? null);
}

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<ConversationEntry[]>([{ id: 0, role: 'assistant', text: WELCOME }]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const inputRef = useRef(input);
  inputRef.current = input;
  const [busy, setBusy] = useState(false);
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
  const [resetKey, setResetKey] = useState(0);
  const [physicsView, setPhysicsView] = useState<PhysicsView | null>(null);
  const [physicsActive, setPhysicsActive] = useState(false);
  const [agentPhase, setAgentPhase] = useState<AgentPhase>(null);
  const [actionRuns, setActionRuns] = useState<ActionRun[]>([]);
  const lastMessage = useRef<HTMLDivElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const viewer = useRef<HTMLDivElement>(null);
  const details = useRef<HTMLDetailsElement>(null);
  const sceneCapture = useRef<(() => Promise<string>) | null>(null);
  const preparationDetails = useRef<HTMLDetailsElement>(null);
  const filesSection = useRef<HTMLDivElement>(null);
  const seenRevision = useRef<string | null>(null);
  const newProjectRequested = useRef(true);
  const skipRestore = useRef(false);
  const projectFile = useRef<HTMLInputElement>(null);
  const chatAbort = useRef<AbortController | null>(null);
  const revealRef = useRef<HTMLSpanElement | null>(null);
  const sessionRef = useRef(0);
  const projectRef = useRef<Project | null>(null);
  projectRef.current = project;

  useEffect(() => {
    let active = true;
    setInitializing(true);
    setError(null);
    (async () => {
      let stored: string | null = null;
      try { if (!skipRestore.current) stored = localStorage.getItem(LOCAL_PROJECT); } catch { /* File save remains available. */ }
      skipRestore.current = false;
      if (stored) {
        const data = await request('/api/projects/open', JSON.parse(stored)) as OpenedProject;
        if (active) {
          setProject(data.project);
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
  }, [connectionAttempt]);

  useEffect(() => {
    if (!project || initializing) return;
    const controller = new AbortController();
    fetch(`/api/projects/${encodeURIComponent(project.id)}/snapshot?revision=${project.revision}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) return;
        const snapshot = await response.json();
        if (!controller.signal.aborted) localStorage.setItem(LOCAL_PROJECT, JSON.stringify(snapshot));
      }).catch(() => { /* Explicit file saving still works when browser storage is unavailable. */ });
    return () => controller.abort();
  }, [project, initializing]);

  useEffect(() => {
    if (messages.length < 2 || !conversation.current || !lastMessage.current) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    conversation.current.scrollTo({
      top: Math.max(0, lastMessage.current.offsetTop - conversation.current.clientHeight + 24),
      behavior: reducedMotion ? 'auto' : 'smooth',
    });
  }, [messages, busy, agentPhase]);

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
    viewer.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
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
  const showLiquidParams = supportedLiquid && (Boolean(workflow?.parameters_started) || project?.plan?.status === 'ready');
  const briefHref = project ? `/api/projects/${encodeURIComponent(project.id)}/brief?revision=${encodeURIComponent(String(project.revision))}` : '#';

  const showPreview = project?.status === 'confirmed' && project?.plan?.status === 'ready' && hasEngineeringDesign;
  const acceptedLayoutId = project?.engineering_design?.provenance.run_id;
  useEffect(() => {
    if (actionRuns.some((run) => run.status === 'ready') && details.current) {
      details.current.open = true;
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
    if (!showPreview) setPlaying(false);
  }, [showPreview]);

  function handlePlay() { setResetKey((value) => value + 1); setInspectionTime(0); setPhysicsActive(false); setPhysicsView(null); setPlaying(true); }
  function handlePause() { setPlaying(false); }
  function handleReset() {
    setPlaying(false);
    setResetKey((value) => value + 1);
  }
  const handlePhysicsView = useCallback((view: PhysicsView | null) => { setPhysicsView(view); }, []);
  const handlePhysicsActivate = useCallback(() => { setResetKey((value) => value + 1); setInspectionTime(0); setPlaying(false); setPhysicsActive(true); }, []);
  const handleInspection = useCallback((time: number) => {
    setInspectionTime(time); setPlaying(false); setPhysicsActive(false); setPhysicsView(null);
  }, []);
  const uiBusy = busy || storageBusy || modelBusy;
  const appendTranscript = useCallback((text: string) => {
    const current = inputRef.current;
    const combined = current.trim() ? `${current}\n${text}` : text;
    if (combined.length > 4000) return false;
    setInput(combined);
    field.current?.focus({ preventScroll: true });
    return true;
  }, []);

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
      try { snapshot = localStorage.getItem(LOCAL_PROJECT); } catch { /* In-memory undo remains available. */ }
      const canRecover = project && (messages.length > 1 || input.trim() || hasBrief || hasEngineeringDesign);
      if (canRecover) {
        setRecovery({ project, messages, input, notice: storageNotice, snapshot });
      }
      chatAbort.current?.abort();
      sessionRef.current += 1;
      setAgentPhase(null); setActionRuns([]);
      setStorageNotice(canRecover || recovery ? 'New project ready. Your previous workspace can be restored with Undo.' : null);
      newProjectRequested.current = true;
      seenRevision.current = null;
      setProject(replacement.project);
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
    setProject(recovery.project); setMessages(recovery.messages); setInput(recovery.input);
    setStorageNotice(recovery.notice ?? 'Previous workspace restored.');
    setRecovery(null); setSelectedId(null); setPlaying(false); setActionRuns([]);
    try { if (recovery.snapshot) localStorage.setItem(LOCAL_PROJECT, recovery.snapshot); } catch { /* Explicit project saving remains available. */ }
    field.current?.focus({ preventScroll: true });
  }

  const captureIllustration = useCallback(async () => {
    if (!sceneCapture.current) throw new Error('The model view is not ready yet. Wait for it to load, then try again.');
    return sceneCapture.current();
  }, []);

  function reviewPreparationPlan() {
    if (preparationDetails.current) preparationDetails.current.open = true;
    preparationDetails.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    preparationDetails.current?.focus({ preventScroll: true });
  }

  function showProjectFiles() {
    if (details.current) details.current.open = true;
    requestAnimationFrame(() => {
      filesSection.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      filesSection.current?.focus({ preventScroll: true });
    });
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = input.trim();
    if (!project || !message || uiBusy || voiceBusy) return;
    if (message.length > 4000) { setError('The message exceeds 4,000 characters. Shorten it before sending; your draft is kept.'); return; }
    const session = sessionRef.current;
    const base = projectRef.current;
    chatAbort.current?.abort();
    const controller = new AbortController();
    chatAbort.current = controller;
    setBusy(true);
    setAgentPhase('pending');
    setError(null);
    setInput('');
    setMessages((current) => [...current, { id: Date.now(), role: 'user', text: message }]);
    try {
      const raw = await request(`/api/projects/${encodeURIComponent(project.id)}/messages`, { message }, controller.signal) as ChatResponse;
      if (controller.signal.aborted || sessionRef.current !== session) return;
      const runs = Array.isArray(raw.action_runs) ? raw.action_runs : [];
      const changed = !sameDesign(base, raw.project);
      if (changed) {
        setAgentPhase('complete');
        await finishAgentReveal(controller.signal, revealRef.current);
        if (controller.signal.aborted || sessionRef.current !== session) return;
      } else {
        setAgentPhase(null);
      }
      setProject(raw.project);
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
      if (!controller.signal.aborted && sessionRef.current === session) {
        setBusy(false);
        setAgentPhase(null);
      }
    }
  }

  async function confirm() {
    if (!project || uiBusy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/confirm`);
      setProject(result.project);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The design could not be confirmed.');
    } finally { setBusy(false); }
  }

  async function chooseOption(groupId: string, optionId: string) {
    if (!project || uiBusy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/configuration`, {
        selections: { [groupId]: optionId },
      });
      setProject(result.project);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The component choice could not be applied.');
    } finally { setBusy(false); }
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  const part = hasEngineeringDesign ? project?.design.components.find((component) => component.id === selectedId) : undefined;
  const bounds = project?.inspection_extension?.assembly_bounds ?? project?.design.assembly_bounds;
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
  const sourcing = hasEngineeringDesign ? (project?.sourcing ?? null) : null;
  const estimatedAmount = project?.design.estimated_cost.amount;
  const costCurrency = sourcing?.currency ?? project?.design.estimated_cost.currency ?? 'USD';
  const costAmount = hasEngineeringDesign ? (sourcing ? sourcing.subtotal : estimatedAmount) : null;
  const costText = costAmount == null
    ? 'Not estimated yet'
    : costAmount === 0 && sourcing && sourcing.unpriced_count > 0 ? 'Pricing pending'
    : `${sourcing?.is_lower_bound ? 'from ' : ''}${formatMoney(costAmount, costCurrency)}`;
  const isConfirmed = project?.status === 'confirmed';
  const headerLabel = hasBrief || hasEngineeringDesign ? 'Lab automation project' : 'New automation project';
  const showPhotoCheck = Boolean(project?.inspection_extension) || actionRuns.some((run) => run.kind === 'show_photo_check');
  const requestedSources = actionRuns.some((run) => run.kind === 'show_sources' && run.status === 'ready');
  const requestedPhoto = actionRuns.some((run) => run.kind === 'show_photo_check' && run.status === 'ready');
  const requestedBuildPlan = actionRuns.some((run) => run.kind === 'show_build_plan' && run.status === 'ready');

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="MuseAutoLab home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span>Muse<span className="brand-accent">Auto</span>Lab</span>
        </a>
        <div className="topbar-center"><span className="topbar-divider" /> Workspace <span className="topbar-slash">/</span> <strong>{headerLabel}</strong></div>
        <div className="topbar-end">
          <input ref={projectFile} tabIndex={-1} type="file" accept=".json,application/json" className="sr-only" aria-label="Open saved project" onChange={(event) => { const file = event.target.files?.[0]; if (file) void openProject(file); }} />
          <button type="button" className="new-project-button" onClick={() => projectFile.current?.click()} disabled={uiBusy || initializing}>Open project</button>
          <button type="button" className="new-project-button" onClick={() => void saveProject()} disabled={!project || uiBusy || initializing}>Save project</button>
          <button type="button" className="new-project-button" onClick={() => void handleNewProject()} disabled={uiBusy || initializing}>New project</button>
          {recovery && <button type="button" className="new-project-button" onClick={undoNewProject} disabled={uiBusy || initializing}>Undo new project</button>}
          <span className={`connection-dot ${project ? 'connected' : ''}`} />{project ? 'Workspace ready' : initializing ? 'Connecting' : 'Offline'}
        </div>
      </header>
      <main className={`workspace${!hasBrief && !hasEngineeringDesign ? ' workspace-start' : ''}`}>
        <section className={`design-panel${isConfirmed && hasEngineeringDesign ? ' design-panel-confirmed' : ''}`} aria-labelledby="design-title">
          <div className="design-heading">
            <div>
              <p className="kicker"><span className="kicker-dot" /> Design workspace</p>
              <h1 id="design-title">{headerLabel}</h1>
              <p className="design-intro">Automation designed around your lab.</p>
              {storageNotice && <p className="storage-notice" role="status">{storageNotice}</p>}
            </div>
            <div className="revision"><span>Project revision</span><strong>{(hasBrief || hasEngineeringDesign) && project ? `Revision ${String(project.revision).padStart(2, '0')}` : 'Ready for your brief'}</strong>{!isConfirmed && plan?.status === 'ready' && <button className="review-plan-shortcut" type="button" onClick={reviewPreparationPlan}>Review preparation plan</button>}{isConfirmed && hasEngineeringDesign && <button className="project-files-shortcut" type="button" onClick={showProjectFiles}>Project files</button>}</div>
          </div>

          {!hasEngineeringDesign ? (
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
                  <p className="planning-note">{LIQUID_NOTE}</p>
                ) : status === 'infeasible' ? (
                  <p className="planning-note">Requested width cannot fit this concept. Adjust the available width in chat to continue.</p>
                ) : (
                  <p className="planning-note">No machine has been generated yet. Discuss the equipment in chat so the layout can be proposed for this workflow.</p>
                )}
              </div>
            ) : (
              <div className="workspace-empty" aria-labelledby="design-title">
                <div className="workspace-empty-grid" aria-hidden="true" />
                <h2>Start with your goal</h2>
                <p>{initializing ? 'Preparing your workspace…' : !project ? 'Connect to the local server using Retry to begin your project.' : 'Describe the task you want to automate and what makes it difficult. Your project brief will appear here as we clarify the process, materials, equipment and constraints.'}</p>
              </div>
            )
          ) : (
            <>
              <div ref={viewer} className={`viewer-shell${isConfirmed ? ' viewer-compact' : ''}`}>
                <div className="viewer-topline"><span><Icon name="cube" size={16} /> {hasFoundation ? 'Jubilee CAD · custom layout' : hasPlatform ? 'OT-2 · schematic setup' : 'Interactive 3D concept'}</span><span><span className="viewer-badge">Meta-proposed layout</span></span></div>
                <div className={`viewer-canvas${isConfirmed ? ' viewer-canvas-compact' : ''}`}>
                  {project ? <Scene captureRef={sceneCapture} project={project} selectedId={selectedId} onSelect={setSelectedId} inspectionTime={inspectionTime} operation={{ playing: physicsView ? false : playing, steps: plan?.steps ?? [], onComplete: handlePreviewComplete, resetKey }} physics={physicsView} /> : <div className="scene-fallback">{initializing ? 'Preparing your workspace…' : 'Connect the local server to view your design.'}</div>}
                  <div className="scene-hint"><Icon name="rotate" size={15} /> Drag to rotate <span>·</span> Scroll to zoom</div>
                  <div className="scene-origin"><span className="origin-x">X</span><span className="origin-y">Y</span><span className="origin-z">Z</span></div>
                </div>
                <div className="viewer-bottomline">
                  <div className="footprint"><span>Workspace footprint</span><strong>{dimensions ? `${formatDimension(dimensions.width_mm)} × ${formatDimension(dimensions.depth_mm)}` : '—'} <small>mm</small></strong></div>
                  <div className="viewer-status"><span className={`status-indicator ${status === 'infeasible' ? 'warning' : ''}`} />{status === 'infeasible' ? 'Requested width cannot fit this concept' : status === 'fits' ? 'Within requested width' : 'No width constraint yet'}</div>
                </div>
              </div>

              <div className="below-viewer">
                <div className="cost-block"><span>Known parts subtotal</span><strong>{costText}</strong><small>{sourcing ? `${sourcing.unpriced_count} unpriced group${sourcing.unpriced_count === 1 ? '' : 's'} · Excludes shipping and taxes · Curated snapshot ${sourcing.checked_on}, not a live feed. Partial estimate only.` : 'Pricing is not yet available for this concept.'}</small></div>
                <div className="selection-block"><span>{part ? 'Selected component' : 'Explore the design'}</span><strong>{part ? part.label : 'Select a component'}</strong><small>{part ? `${part.size.map(formatDimension).join(' × ')} mm · schematic dimensions` : 'Select an item in the model or list.'}</small></div>
              </div>

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
                <ComponentCatalog
                  sourcing={sourcing}
                  busy={uiBusy || !project}
                  onChoose={(groupId, optionId) => void chooseOption(groupId, optionId)}
                  onHighlight={(componentId) => setSelectedId(componentId)}
                />
                {project && <div className="part-list" aria-label="Workstation components"><span>Components</span><div>{project.design.components.map((component) => <button type="button" key={component.id} className={selectedId === component.id ? 'part-chip selected' : 'part-chip'} onClick={() => setSelectedId(component.id)} aria-pressed={selectedId === component.id}>{component.label}</button>)}</div></div>}
                {project?.inspection_extension && (
                  <div className="inspection-sweep">
                    <button type="button" className="new-project-button" disabled={uiBusy} onClick={() => handleInspection(0)}>
                      Reset inspection sweep
                    </button>
                    <label htmlFor="inspection-time">Camera sweep <span>{inspectionTime.toFixed(1)} / 6 s</span></label>
                    <input id="inspection-time" type="range" min={0} max={6} step={0.05} value={inspectionTime} disabled={uiBusy} onChange={(event) => { const value = Number(event.target.value); handleInspection(value); }} />
                  </div>
                )}
                {showPreview && (
                  <div className="preview-block">
                    <div className="preview-controls" role="group" aria-label="Preparation preview controls">
                      <button type="button" className="preview-button" onClick={handlePlay} disabled={playing} aria-pressed={playing}>Play preview</button>
                      <button type="button" className="preview-button" onClick={handlePause} disabled={!playing}>Pause preview</button>
                      <button type="button" className="preview-button" onClick={handleReset}>Reset preview</button>
                    </div>
                    <p className="preview-note">Illustrative animation; motion and dispensing are not validated.</p>
                  </div>
                )}
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
            </>
          )}
          {!hasEngineeringDesign && (requestedSources || requestedBuildPlan) && project && (
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
        </section>

        <aside className="conversation-panel" aria-labelledby="conversation-title">
          <div className="chat-heading"><div className="assistant-emblem"><Icon name="spark" size={19} /></div><div><h2 id="conversation-title">Design assistant</h2><p>Let’s make your workflow easier.</p></div><span className="chat-status">{project?.status === 'confirmed' ? 'Confirmed' : 'Draft'}</span></div>
          <div className="assistant-controls">{project && <ModelSelector key={project.id} projectId={project.id} busy={uiBusy || voiceBusy} onBusyChange={setModelBusy} onVoiceCapability={setVoiceCapability} onImageCapability={setImageCapability} />}</div>
          <div className="conversation-scroll" ref={conversation}>
            <div className="chat-date">Your design conversation</div>
            {messages.map((message) => <div key={message.id} className={`message-row ${message.role}`}>
              {message.role === 'assistant' && <span className="message-avatar"><Icon name="spark" size={13} /></span>}
              <div><span className="message-author">{message.role === 'assistant' ? 'MuseAutoLab' : 'You'}</span><div className="message-bubble">{message.text}</div>{message.references && message.references.length > 0 && <div className="message-references">{message.references.map((ref) => <a key={ref.id} href={ref.url} target="_blank" rel="noopener noreferrer">{ref.title} ↗</a>)}</div>}</div>
            </div>)}
            {agentPhase && <AgentActivity phase={agentPhase} fillRef={revealRef} />}
            <div ref={lastMessage} />
            {showLiquidParams && (
              <details className="prep-plan" ref={preparationDetails} tabIndex={-1} aria-label="Preparation plan">
                <summary>Preparation plan</summary>
                <div className="summary-card">
                  <div className="summary-heading"><div><h3>Experiment details</h3><p>Review these before confirming.</p></div><span>{fields.filter((entry) => entry.label !== 'Available width' && entry.value).length}/4 required</span></div>
                  <dl>{fields.map((entry) => <div key={entry.label}><dt>{entry.label}</dt><dd className={entry.value ? '' : 'missing'}>{entry.value || (entry.label === 'Available width' ? 'Optional' : 'Not specified')}</dd></div>)}</dl>
                  {project?.status === 'confirmed' ? <div className="confirmed"><Icon name="check" size={16} /> Design parameters confirmed</div> : <button className="confirm-button" type="button" onClick={() => void confirm()} disabled={!project || uiBusy || !hasEngineeringDesign || plan?.status !== 'ready'}>Confirm design <span>↗</span></button>}
                  <p className="summary-note">{project?.status !== 'confirmed' && (!hasEngineeringDesign ? 'Choose a platform and request a design in chat before confirming. ' : plan?.status !== 'ready' ? 'Complete the missing preparation details in chat before confirming. ' : 'Ready to confirm these parameters. ')}The model is a schematic concept; component fit and laboratory performance remain to be verified.</p>
                </div>
                {project && plan == null && (
                  <div className="plan-card" aria-live="polite">
                    <div className="plan-heading">
                      <div>
                        <h3>Preparation plan</h3>
                        <p>Direct dilution · one tube per target</p>
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
                        <h3>Preparation plan</h3>
                        <p>Direct dilution · one tube per target · no serial dilutions</p>
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
                          <caption className="sr-only">Per-target preparation volumes in microlitres</caption>
                          <thead>
                            <tr>
                              <th scope="col">Target</th>
                              <th scope="col">Stock</th>
                              <th scope="col">Diluent</th>
                              <th scope="col">Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {plan.steps.map((step) => (
                              <tr key={step.id}>
                                <th scope="row">{step.target}</th>
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
            )}
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
            <p className="composer-caption">Designed with Meta AI <span>·</span> Review all suggested parameters</p>
          </div>
        </aside>
      </main>
    </div>
  );
}
