export type AgentPhase = 'pending' | 'updating' | 'ready';

export const activityCopy = {
  pending: { title: 'Reviewing your request', detail: 'The assistant is checking your request.' },
  updating: { title: 'Updating design', detail: 'Applying the accepted changes to the model.' },
  ready: { title: 'Design updated', detail: 'Review the accepted changes in the model.' },
} satisfies Record<AgentPhase, { title: string; detail: string }>;

/** Yield to the browser paint; no estimated work percentage or artificial progress delay. */
export function nextDesignPaint(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return; }
    let frame = 0;
    const finish = () => { cancelAnimationFrame(frame); signal.removeEventListener('abort', finish); resolve(); };
    signal.addEventListener('abort', finish, { once: true });
    frame = requestAnimationFrame(() => { frame = requestAnimationFrame(finish); });
  });
}

export default function AgentActivity({ phase, pendingTitle, scene = false }: { phase: AgentPhase; pendingTitle?: string | null; scene?: boolean }) {
  const copy = phase === 'pending' && pendingTitle
    ? { title: pendingTitle, detail: 'Checking the selected product and placement.' }
    : activityCopy[phase];
  return <div className={scene ? `design-activity design-activity-${phase}` : 'agent-activity'} aria-hidden="true" data-phase={phase}>
    <span className={`activity-indicator${phase === 'ready' ? ' activity-ready' : ''}`}>
      {phase === 'ready' ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg> : <span />}
    </span>
    <div className="agent-activity-heading"><strong>{copy.title}</strong><span>{copy.detail}</span></div>
    {!scene && phase !== 'ready' && <span className="sr-only" role="progressbar" aria-label={copy.title} />}
  </div>;
}
