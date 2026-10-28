import type { RefObject } from 'react';

export async function finishAgentReveal(signal: AbortSignal, element: HTMLSpanElement | null): Promise<void> {
  if (!element || signal.aborted) return;
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const animation = element.animate(
    [{ width: '30%' }, { width: '100%' }],
    { duration: 650, easing: 'ease', fill: 'forwards' },
  );
  const cancel = () => { try { animation.cancel(); } catch { /* reset cancels */ } };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    await animation.finished;
  } catch { /* abort or reset cancels the presentation */ }
  finally {
    signal.removeEventListener('abort', cancel);
  }
}

type Props = {
  phase: 'pending' | 'complete';
  fillRef: RefObject<HTMLSpanElement | null>;
};

export default function AgentActivity({ phase, fillRef }: Props) {
  return (
    <div className="agent-activity" aria-live="polite">
      <div className="agent-activity-heading">
        <strong>{phase === 'complete' ? 'Update accepted' : 'Working on your request'}</strong>
        <span>{phase === 'complete' ? 'Opening the updated view…' : 'Interpreting and checking…'}</span>
      </div>
      <div
        className={`agent-activity-track${phase === 'complete' ? ' complete' : ' waiting'}`}
        role="progressbar"
        aria-label={phase === 'complete' ? 'Update accepted' : 'Assistant working'}
        aria-valuemin={0}
        aria-valuemax={100}
        {...(phase === 'complete' ? { 'aria-valuenow': 100 as number } : {})}
      >
        <span ref={fillRef} />
      </div>
    </div>
  );
}
