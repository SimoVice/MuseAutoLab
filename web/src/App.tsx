import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Scene from './Scene';
import ComponentCatalog from './ComponentCatalog';
import ProjectFiles from './ProjectFiles';
import PhysicsPanel from './PhysicsPanel';
import type { ConversationEntry, PhysicsView, PreparationPlan, Project, ProjectResponse } from './types';

const EXAMPLE = 'I need to prepare aliquots from a 10 mg/mL stock to a 1 mg/mL target, with 1 mL in each tube. I have a pipette and microcentrifuge tubes.';
const WELCOME = 'Tell me about the preparation you would like to automate. We’ll define the concentrations, final volume and equipment together.';
const PROPOSED_TARGET_C = 4;

function readableError(message: string) {
  return message.replace(/\b(stock_concentration|target_concentrations|final_volume|workspace_width_mm)\b/g, (field) => ({
    stock_concentration: 'stock concentration',
    target_concentrations: 'target concentrations',
    final_volume: 'final volume',
    workspace_width_mm: 'available width',
  }[field] ?? field));
}

async function request(path: string, body?: unknown): Promise<ProjectResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<ConversationEntry[]>([{ id: 0, role: 'assistant', text: WELCOME }]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const [physicsView, setPhysicsView] = useState<PhysicsView | null>(null);
  const [physicsActive, setPhysicsActive] = useState(false);
  const [coolingEnabledDraft, setCoolingEnabledDraft] = useState(false);
  const [coolingTargetDraft, setCoolingTargetDraft] = useState(String(PROPOSED_TARGET_C));
  const lastMessage = useRef<HTMLDivElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const seenRevision = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    setInitializing(true);
    setError(null);
    request('/api/projects').then(({ project: created }) => {
      if (active) setProject(created);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Cannot connect to the local server.');
    }).finally(() => { if (active) setInitializing(false); });
    return () => { active = false; };
  }, [connectionAttempt]);

  useEffect(() => {
    if (messages.length < 2 || !conversation.current || !lastMessage.current) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    conversation.current.scrollTo({
      top: Math.max(0, lastMessage.current.offsetTop - conversation.current.clientHeight + 24),
      behavior: reducedMotion ? 'auto' : 'smooth',
    });
  }, [messages, busy]);
  useEffect(() => {
    if (selectedId && project && !project.design.components.some((part) => part.id === selectedId)) setSelectedId(null);
  }, [project, selectedId]);

  useEffect(() => {
    if (!project) return;
    const enabled = Boolean(project.summary?.cooling_enabled ?? project.design?.cooling?.enabled ?? false);
    const target = project.summary?.cooling_target_c ?? project.design?.cooling?.target_c ?? PROPOSED_TARGET_C;
    setCoolingEnabledDraft(enabled);
    setCoolingTargetDraft(target == null ? String(PROPOSED_TARGET_C) : String(target));
  }, [project]);

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
      setResetKey((value) => value + 1);
    }
  }, [projectId, projectRevision]);

  const handlePreviewComplete = useCallback(() => {
    setPlaying(false);
    setResetKey((value) => value + 1);
  }, []);

  const showPreview = project?.status === 'confirmed' && project?.plan?.status === 'ready';
  useEffect(() => {
    if (!showPreview) setPlaying(false);
  }, [showPreview]);

  function handlePlay() { setPhysicsActive(false); setPhysicsView(null); setPlaying(true); }
  function handlePause() { setPlaying(false); }
  function handleReset() {
    setPlaying(false);
    setResetKey((value) => value + 1);
  }
  const handlePhysicsView = useCallback((view: PhysicsView | null) => { setPhysicsView(view); }, []);
  const handlePhysicsActivate = useCallback(() => { setPlaying(false); setPhysicsActive(true); }, []);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = input.trim();
    if (!project || !message || busy) return;
    setBusy(true);
    setError(null);
    setInput('');
    setMessages((current) => [...current, { id: Date.now(), role: 'user', text: message }]);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/messages`, { message });
      setProject(result.project);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      setInput(message);
      setError(reason instanceof Error ? reason.message : 'The request could not be completed. Please try again.');
    } finally { setBusy(false); }
  }

  async function confirm() {
    if (!project || busy) return;
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

  async function applyCooling() {
    if (!project || busy) return;
    const parsed = Number(coolingTargetDraft);
    if (coolingEnabledDraft && (!coolingTargetDraft.trim() || !Number.isFinite(parsed) || parsed < 2 || parsed > 20)) {
      setError('Enter a target temperature between 2 and 20 °C.');
      return;
    }
    const body: { cooling_enabled: boolean; cooling_target_c?: number } = { cooling_enabled: coolingEnabledDraft };
    if (coolingTargetDraft.trim() !== '' && Number.isFinite(parsed) && parsed >= 2 && parsed <= 20) body.cooling_target_c = parsed;
    setBusy(true);
    setError(null);
    try {
      const result = await request(`/api/projects/${encodeURIComponent(project.id)}/configuration`, body);
      setProject(result.project);
      if (result.assistant_message) setMessages((current) => [...current, { id: Date.now() + 1, role: 'assistant', text: result.assistant_message! }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The cooling settings could not be applied.');
    } finally { setBusy(false); }
  }

  async function chooseOption(groupId: string, optionId: string) {
    if (!project || busy) return;
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

  const part = project?.design.components.find((component) => component.id === selectedId);
  const dimensions = project?.design.footprint;
  const summary = project?.summary;
  const status = project?.design.constraint_status;
  const plan = project?.plan ?? null;
  const fields = [
    { label: 'Stock', value: summary?.stock_concentration },
    { label: 'Targets', value: summary?.target_concentrations },
    { label: 'Final volume', value: summary?.final_volume },
    { label: 'Equipment', value: summary?.equipment },
    { label: 'Available width', value: summary?.workspace_width_mm != null ? `${formatDimension(summary.workspace_width_mm)} mm` : null },
  ];
  const sourcing = project?.sourcing ?? null;
  const estimatedAmount = project?.design.estimated_cost.amount;
  const costCurrency = sourcing?.currency ?? project?.design.estimated_cost.currency ?? 'USD';
  const costAmount = sourcing ? sourcing.subtotal : estimatedAmount;
  const costText = costAmount == null
    ? 'Not estimated yet'
    : `${sourcing?.is_lower_bound ? 'from ' : ''}${formatMoney(costAmount, costCurrency)}`;
  const coolingEnabled = Boolean(project?.summary?.cooling_enabled ?? project?.design?.cooling?.enabled ?? false);
  const effectiveTarget = project?.summary?.cooling_target_c ?? project?.design?.cooling?.target_c ?? PROPOSED_TARGET_C;
  const coolingNotes = project?.design?.cooling?.notes ?? [];
  const isConfirmed = project?.status === 'confirmed';

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="MuseAutoLab home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span>Muse<span className="brand-accent">Auto</span>Lab</span>
        </a>
        <div className="topbar-center"><span className="topbar-divider" /> Workspace <span className="topbar-slash">/</span> <strong>Aliquot workstation</strong></div>
        <div className="topbar-end"><span className={`connection-dot ${project ? 'connected' : ''}`} />{project ? 'Workspace ready' : initializing ? 'Connecting' : 'Offline'}</div>
      </header>
      <main className="workspace">
        <section className={`design-panel${isConfirmed ? ' design-panel-confirmed' : ''}`} aria-labelledby="design-title">
          <div className="design-heading">
            <div>
              <p className="kicker"><span className="kicker-dot" /> Design workspace</p>
              <h1 id="design-title">Your experiment, taking shape.</h1>
              <p className="design-intro">A workstation built around the way you work.</p>
            </div>
            <div className="revision"><span>Current design</span><strong>{project ? `Revision ${String(project.revision).padStart(2, '0')}` : 'Waiting for project'}</strong></div>
          </div>

          <div className={`viewer-shell${isConfirmed ? ' viewer-compact' : ''}`}>
            <div className="viewer-topline"><span><Icon name="cube" size={16} /> Interactive 3D concept</span><span className="viewer-badge">Unverified concept</span></div>
            <div className={`viewer-canvas${isConfirmed ? ' viewer-canvas-compact' : ''}`}>
              {project ? <Scene project={project} selectedId={selectedId} onSelect={setSelectedId} operation={{ playing: physicsView ? false : playing, steps: project.plan?.steps ?? [], onComplete: handlePreviewComplete, resetKey }} physics={physicsView} /> : <div className="scene-fallback">{initializing ? 'Preparing your workspace…' : 'Connect the local server to view your design.'}</div>}
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
          {project && showPreview && (
            <PhysicsPanel project={project} active={physicsActive} onView={handlePhysicsView} onActivate={handlePhysicsActivate} />
          )}
          {project && isConfirmed && <ProjectFiles project={project} onSelect={setSelectedId} />}
          {project && <div className="part-list" aria-label="Workstation components"><span>Components</span><div>{project.design.components.map((component) => <button type="button" key={component.id} className={selectedId === component.id ? 'part-chip selected' : 'part-chip'} onClick={() => setSelectedId(component.id)} aria-pressed={selectedId === component.id}>{component.label}</button>)}</div></div>}


          <section className="cooling-card" aria-labelledby="cooling-title">
            <div className="cooling-heading">
              <div>
                <h2 id="cooling-title">Cold storage</h2>
                <p>Optional refrigerated bay for samples.</p>
              </div>
              <span className="cooling-state">{coolingEnabled ? `Target ${effectiveTarget}°C` : 'Off'}</span>
            </div>
            <label className="cooling-toggle" htmlFor="cooling-enabled">
              <input
                id="cooling-enabled"
                type="checkbox"
                checked={coolingEnabledDraft}
                onChange={(event) => setCoolingEnabledDraft(event.target.checked)}
                disabled={!project || busy}
              />
              Refrigerated sample bay
            </label>
            <div className="cooling-row">
              <div className="cooling-field">
                <label htmlFor="cooling-target">Target temperature (°C)</label>
                <input
                  id="cooling-target"
                  type="number"
                  min={2}
                  max={20}
                  step={0.5}
                  value={coolingTargetDraft}
                  onChange={(event) => setCoolingTargetDraft(event.target.value)}
                  disabled={!project || busy}
                />
              </div>
              <button type="button" className="cooling-apply" onClick={() => void applyCooling()} disabled={!project || busy}>
                Apply cooling settings
              </button>
            </div>
            <p className="cooling-note">
              Proposed cooling with manual sample transfer. Thermal performance remains to be verified.
            </p>
            {coolingNotes.length > 0 && (
              <details className="cooling-notes"><summary>Design assumptions</summary><ul>
                {coolingNotes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul></details>
            )}
          </section>

          <ComponentCatalog
            sourcing={sourcing}
            busy={busy || !project}
            onChoose={(groupId, optionId) => void chooseOption(groupId, optionId)}
            onHighlight={(componentId) => setSelectedId(componentId)}
          />
        </section>

        <aside className="conversation-panel" aria-labelledby="conversation-title">
          <div className="chat-heading"><div className="assistant-emblem"><Icon name="spark" size={19} /></div><div><h2 id="conversation-title">Design assistant</h2><p>Let’s make your workflow easier.</p></div><span className="chat-status">{project?.status === 'confirmed' ? 'Confirmed' : 'Draft'}</span></div>
            <div className="conversation-scroll" ref={conversation}>
            <div className="chat-date">Your design conversation</div>
            {messages.map((message) => <div key={message.id} className={`message-row ${message.role}`}>
              {message.role === 'assistant' && <span className="message-avatar"><Icon name="spark" size={13} /></span>}
              <div><span className="message-author">{message.role === 'assistant' ? 'MuseAutoLab' : 'You'}</span><div className="message-bubble">{message.text}</div></div>
            </div>)}
            {busy && <div className="thinking" role="status"><span className="thinking-dots"><i /><i /><i /></span> Working on your request…</div>}
            <div ref={lastMessage} />
            {messages.length === 1 && <div className="example-prompt"><p>Not sure where to start?</p><button type="button" onClick={() => { setInput(EXAMPLE); field.current?.focus(); }}>Try an example <span>↗</span></button></div>}
            <div className="summary-card">
              <div className="summary-heading"><div><h3>Experiment details</h3><p>Review these before confirming.</p></div><span>{fields.filter((entry) => entry.label !== 'Available width' && entry.value).length}/4 required</span></div>
              <dl>{fields.map((entry) => <div key={entry.label}><dt>{entry.label}</dt><dd className={entry.value ? '' : 'missing'}>{entry.value || (entry.label === 'Available width' ? 'Optional' : 'Not specified')}</dd></div>)}</dl>
              {project?.status === 'confirmed' ? <div className="confirmed"><Icon name="check" size={16} /> Design parameters confirmed</div> : <button className="confirm-button" type="button" onClick={() => void confirm()} disabled={!project || busy}>Confirm design <span>↗</span></button>}
              <p className="summary-note">The model is a schematic concept; component fit and laboratory performance remain to be verified.</p>
            </div>
            {project && plan == null && (
              <div className="plan-card" aria-labelledby="plan-title" aria-live="polite">
                <div className="plan-heading">
                  <div>
                    <h3 id="plan-title">Preparation plan</h3>
                    <p>Direct dilution · one tube per target</p>
                  </div>
                  <span className="plan-status plan-status-missing">Unavailable</span>
                </div>
                <p className="plan-message">The preparation plan is not available yet. It will appear here once the server provides it.</p>
              </div>
            )}
            {project && plan && (
              <div className="plan-card" aria-labelledby="plan-title" aria-live="polite">
                <div className="plan-heading">
                  <div>
                    <h3 id="plan-title">Preparation plan</h3>
                    <p>Direct dilution · one tube per target · no serial dilutions</p>
                  </div>
                  <span className={`plan-status plan-status-${plan.status}`}>{planStatusLabel(plan.status)}</span>
                </div>
                <p className="plan-message">{plan.message}</p>
                <div className="plan-meta">
                  <span><strong>Stock:</strong> {plan.stock ?? 'Not specified'}</span>
                  <span><strong>Final volume:</strong> {plan.final_volume_ul != null ? formatVolumeUl(plan.final_volume_ul) : 'Not specified'}</span>
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
              </div>
            )}
          </div>
          <div className="composer-area">
            {error && <div className="error-message" role="alert"><span>{error}</span>{!project && <button type="button" onClick={() => setConnectionAttempt((value) => value + 1)}>Retry</button>}</div>}
            <form className="composer" onSubmit={(event) => void send(event)}>
              <label className="sr-only" htmlFor="message">Describe your workflow or request a change</label>
              <textarea id="message" ref={field} rows={2} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={keyDown} placeholder="Describe your workflow or request a change…" disabled={!project || busy} />
              <div className="composer-bottom"><span>Enter to send <span className="hide-small">· Shift + Enter for a new line</span></span><button type="submit" aria-label="Send message" disabled={!project || busy || !input.trim()}><Icon name="send" size={18} /></button></div>
            </form>
            <p className="composer-caption">Designed with Meta AI <span>·</span> Review all suggested parameters</p>
          </div>
        </aside>
      </main>
    </div>
  );
}
