import { useEffect, useRef, useState } from 'react';
import type { DesignRun, Project } from './types';

type Props = {
  project: Project;
  onProject: (project: Project) => void;
  onBusy?: (busy: boolean) => void;
};

const DEFAULT_INSTRUCTION =
  'Propose a workstation layout for the recorded workflow, keeping sample access clear and respecting the equipment.';

async function finishReveal(signal: AbortSignal, element: HTMLSpanElement | null): Promise<void> {
  // Presentation transition only: the server has already accepted the layout.
  if (!element || signal.aborted || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const animation = element.animate(
    [{ width: '30%', transform: 'none' }, { width: '100%', transform: 'none' }],
    { duration: 650, easing: 'ease', fill: 'forwards' },
  );
  const cancel = () => animation.cancel();
  signal.addEventListener('abort', cancel, { once: true });
  try { await animation.finished; } catch { /* Reset cancels the presentation. */ }
  finally { signal.removeEventListener('abort', cancel); }
}

function readDetail(data: unknown, status: number): string {
  if (data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string') {
    return (data as { detail: string }).detail;
  }
  return `Request failed (${status}). Please try again.`;
}

function attemptRationale(attempt: DesignRun['attempts'][number]): string | null {
  const proposal = attempt.proposal as Record<string, unknown> | null;
  if (proposal && typeof proposal === 'object' && typeof proposal.rationale === 'string' && proposal.rationale.trim() !== '') {
    return proposal.rationale;
  }
  return null;
}

export default function DesignAgentPanel({ project, onProject, onBusy }: Props) {
  const [instruction, setInstruction] = useState(DEFAULT_INSTRUCTION);
  const [pending, setPending] = useState(false);
  const [layoutReady, setLayoutReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [storedRun, setRun] = useState<DesignRun | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const progressFillRef = useRef<HTMLSpanElement | null>(null);
  const projectKey = `${project.id}:${project.revision}`;
  const hasAccepted = Boolean(project.engineering_design);
  const run = storedRun && (storedRun.status === 'accepted'
    ? project.engineering_design?.provenance.run_id === storedRun.id
    : project.revision === storedRun.source_revision) ? storedRun : null;

  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setPending(false);
    setLayoutReady(false);
    setError(null);
    onBusy?.(false);
    return () => {
      controllerRef.current?.abort();
      onBusy?.(false);
    };
  }, [projectKey, onBusy]);

  async function develop() {
    const trimmed = instruction.trim();
    if (trimmed === '' || pending) {
      if (trimmed === '') setError('Describe the layout change you want before developing a design.');
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestKey = projectKey;
    setPending(true);
    setLayoutReady(false);
    setError(null);
    onBusy?.(true);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/design`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_revision: project.revision, instruction: trimmed }),
        signal: controller.signal,
      });
      const data = (await response.json().catch(() => null)) as {
        project?: Project; design_run?: DesignRun; assistant_message?: string;
      } | null;
      if (controller.signal.aborted || requestKey !== `${project.id}:${project.revision}`) return;
      if (!response.ok) {
        if (data?.design_run) setRun(data.design_run);
        throw new Error(readDetail(data, response.status));
      }
      if (!data || typeof data !== 'object' || !data.project || !data.design_run) {
        throw new Error('The server returned an incomplete response. Please try again.');
      }
      if (data.design_run.status === 'accepted') {
        setLayoutReady(true);
        await finishReveal(controller.signal, progressFillRef.current);
        if (controller.signal.aborted) return;
      }
      setRun(data.design_run);
      onProject(data.project);
    } catch (reason: unknown) {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : 'The design request could not be completed. Please try again.');
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        onBusy?.(false);
      }
    }
  }

  const lastAttempt = run && run.attempts.length > 0 ? run.attempts[run.attempts.length - 1] : null;
  const rationale = lastAttempt ? attemptRationale(lastAttempt) : null;

  return (
    <section className="design-agent-card" aria-labelledby="design-agent-title">
      <div className="design-agent-heading">
        <div>
          <h2 id="design-agent-title">Workstation layout</h2>
          <p>Meta proposes a layout within one supported pipetting architecture. Geometry checks protect the accepted project.</p>
        </div>
        {run && (
          <span className={`design-agent-status design-agent-status-${run.status}`}>
            {run.status === 'accepted' ? 'Accepted' : run.status === 'failed' ? 'Failed' : 'Rejected'}
          </span>
        )}
      </div>

      <label className="design-agent-label" htmlFor="design-agent-instruction">
        Layout request
      </label>
      <textarea
        id="design-agent-instruction"
        className="design-agent-input"
        rows={3}
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        disabled={pending}
        maxLength={2000}
      />
      <div className="design-agent-row">
        <button
          type="button"
          className="design-agent-button"
          onClick={() => void develop()}
          disabled={pending || instruction.trim() === ''}
        >
          {pending ? 'Developing design…' : hasAccepted ? 'Revise design with Meta' : 'Develop design with Meta'}
        </button>
      </div>

      {pending && (
        <div className="design-progress" aria-live="polite">
          <div className="design-progress-heading">
            <strong>{layoutReady ? 'Layout accepted' : 'Developing your workstation'}</strong>
            <span>{layoutReady ? 'Opening the 3D view…' : 'Waiting for Meta and geometry checks…'}</span>
          </div>
          <div
            className={`design-progress-track${layoutReady ? ' complete' : ' waiting'}`}
            role="progressbar"
            aria-label="Workstation design progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={layoutReady ? 100 : undefined}
            aria-valuetext={layoutReady ? 'Layout accepted. Opening the 3D view.' : 'Waiting for Meta and geometry checks.'}
          ><span ref={progressFillRef} /></div>
        </div>
      )}

      {error && (
        <div className="design-agent-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void develop()}>Retry</button>
        </div>
      )}

      {run && (
        <div className="design-agent-result" aria-live="polite">
          <p className="design-agent-message">{run.message}</p>
          <p className="design-agent-meta">
            Model {run.model} · {run.attempts.length} attempt{run.attempts.length === 1 ? '' : 's'} · source revision {run.source_revision}
          </p>
          {rationale && <p className="design-agent-rationale">{rationale}</p>}
          {lastAttempt && lastAttempt.checks.length > 0 && (
            <details className="design-agent-details" open={run.status === 'rejected'}>
              <summary>{lastAttempt.checks.filter((check) => check.passed).length}/{lastAttempt.checks.length} geometry checks passed</summary>
            <ul className="design-agent-checks">
              {lastAttempt.checks.map((check) => (
                <li key={check.id} className={check.passed ? 'passed' : 'failed'}>
                  <strong>{check.passed ? 'Passed' : 'Failed'} — {check.label}</strong>
                  {check.detail && <span>{check.detail}</span>}
                </li>
              ))}
            </ul>
            </details>
          )}
          {run.attempts.length > 1 && (
            <details className="design-agent-details">
              <summary>Earlier attempt ({run.attempts.length - 1} before the final check)</summary>
              <ul className="design-agent-checks">
                {run.attempts[0].checks.map((check) => (
                  <li key={check.id} className={check.passed ? 'passed' : 'failed'}>
                    <strong>{check.passed ? 'Passed' : 'Failed'} — {check.label}</strong>
                    {check.detail && <span>{check.detail}</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <details className="design-agent-details">
        <summary>Conservative-check assumptions</summary>
        <p>
          Checks verify the five movable parts against deck edges, mutual spacing and the rear gantry strip.
          They do not validate robot collisions, full fit or laboratory performance.
        </p>
      </details>
    </section>
  );
}
