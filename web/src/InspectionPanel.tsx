import { useEffect, useRef, useState } from 'react';
import { finishReveal } from './DesignAgentPanel';
import type { DesignRun, Project } from './types';

export default function InspectionPanel({ project, busy, resetKey, onProject, onBusy, onInspect }: {
  project: Project; busy: boolean; resetKey: number; onProject: (project: Project) => void;
  onBusy: (value: boolean) => void; onInspect: (time: number) => void;
}) {
  const [instruction, setInstruction] = useState('Add an inspection arm with a downward camera to check the sample rack. Preserve my workstation.');
  const [pending, setPending] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [run, setRun] = useState<DesignRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const fill = useRef<HTMLSpanElement>(null);
  const key = `${project.id}:${project.revision}`;
  const extension = project.inspection_extension;

  useEffect(() => {
    controller.current?.abort();
    setPending(false); setAccepted(false); setError(null); setPlaying(false); setTime(0);
    onBusy(false); onInspect(0);
    return () => { controller.current?.abort(); onBusy(false); };
  }, [key, onBusy, onInspect]);

  useEffect(() => { setPlaying(false); setTime(0); }, [resetKey]);

  useEffect(() => {
    if (!playing) return;
    const started = performance.now() - time * 1000;
    let frame = 0;
    const tick = (now: number) => {
      const value = Math.min(6, (now - started) / 1000);
      setTime(value); onInspect(value);
      if (value < 6) frame = requestAnimationFrame(tick); else setPlaying(false);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // Time is sampled when playback starts; the slider pauses before changing it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, onInspect]);

  async function develop() {
    if (pending || busy || !instruction.trim()) return;
    const abort = new AbortController(); controller.current = abort;
    setPending(true); setAccepted(false); setError(null); setPlaying(false); onBusy(true);
    try {
      const response = await fetch(`/api/projects/${project.id}/inspection-extension`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ project_revision: project.revision, instruction: instruction.trim() }),
      });
      const data = await response.json() as { project?: Project; design_run?: DesignRun; detail?: string };
      if (!response.ok || !data.project || !data.design_run) throw new Error(data.detail ?? 'The inspection proposal could not be developed. Try again.');
      if (data.design_run.status === 'accepted') {
        setAccepted(true); await finishReveal(abort.signal, fill.current);
      }
      if (abort.signal.aborted) return;
      setRun(data.design_run); onProject(data.project);
    } catch (reason) {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : 'The inspection proposal failed.');
    } finally { if (!abort.signal.aborted) { setPending(false); onBusy(false); } }
  }

  async function remove() {
    if (busy || pending) return;
    setError(null); onBusy(true); setPlaying(false);
    const abort = new AbortController(); controller.current = abort;
    try {
      const response = await fetch(`/api/projects/${project.id}/inspection-extension/remove`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ project_revision: project.revision }),
      });
      const data = await response.json() as { project?: Project; detail?: string };
      if (!response.ok || !data.project) throw new Error(data.detail ?? 'The module could not be removed.');
      if (!abort.signal.aborted) { setRun(null); onProject(data.project); }
    } catch (reason) { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : 'The module could not be removed.'); }
    finally { if (!abort.signal.aborted) onBusy(false); }
  }

  return <section className="inspection-panel" aria-labelledby="inspection-extension-title">
    <div className="design-agent-heading"><div>
      <h2 id="inspection-extension-title">{extension ? 'Inspection arm and camera' : 'Expand this workstation'}</h2>
      <p>{extension ? 'Your workstation is preserved. Preview the camera sweep over the sample rack.' : 'Ask Meta to add a two-link inspection arm and camera to this project.'}</p>
    </div><span className="planning-status">{extension ? 'Concept module' : 'Next capability'}</span></div>
    <label className="design-agent-label" htmlFor="inspection-request">Expansion request</label>
    <textarea id="inspection-request" className="design-agent-input" value={instruction} maxLength={2000} rows={2} disabled={busy || pending} onChange={(event) => setInstruction(event.target.value)} />
    <div className="design-agent-row">
      <button className="design-agent-button" type="button" disabled={busy || pending || !instruction.trim()} onClick={() => void develop()}>{pending ? 'Developing inspection module…' : extension ? 'Revise inspection module with Meta' : 'Add arm and camera with Meta'}</button>
      {extension && <button className="new-project-button" type="button" disabled={busy || pending} onClick={() => void remove()}>Remove module</button>}
    </div>
    {pending && <div className="design-progress" aria-live="polite">
      <div className="design-progress-heading"><strong>{accepted ? 'Inspection layout accepted' : 'Designing the inspection module'}</strong><span>{accepted ? 'Opening the expanded view…' : 'Waiting for Meta and reach checks…'}</span></div>
      <div className={`design-progress-track ${accepted ? 'complete' : 'waiting'}`} role="progressbar" aria-label="Inspection module progress" aria-valuemin={0} aria-valuemax={100} {...(accepted ? { 'aria-valuenow': 100 } : {})}><span ref={fill} /></div>
    </div>}
    {error && <p className="inline-error" role="alert">{error}</p>}
    {run && run.status !== 'accepted' && <p role="status">{run.message}</p>}
    {extension && <>
      <div className="inspection-sweep">
        <button type="button" className="new-project-button" disabled={busy} onClick={() => { if (time >= 6) { setTime(0); onInspect(0); } setPlaying(!playing); }}>{playing ? 'Pause inspection preview' : 'Preview inspection sweep'}</button>
        <label htmlFor="inspection-time">Camera sweep <span>{time.toFixed(1)} / 6 s</span></label>
        <input id="inspection-time" type="range" min={0} max={6} step={0.05} value={time} disabled={busy} onChange={(event) => { const value = Number(event.target.value); setPlaying(false); setTime(value); onInspect(value); }} />
      </div>
      <p className="cooling-note">Kinematic preview. Camera images come from a separate photo check; motion clearance, mounting loads and image coverage remain unverified.</p>
      <details><summary>Module decisions and checks</summary>
        <p>{extension.proposal.rationale}</p>
        <p>Link lengths: {extension.proposal.link_lengths_mm.join(' + ')} mm. Mast: {extension.proposal.mast_height_mm} mm.</p>
        <p>Recorded model: {String(extension.provenance?.model ?? 'Not recorded')}{project.restored_from ? ' (saved proposal)' : ''}</p>
        <ul>{extension.checks.map((check) => <li key={check.id}>{check.detail}</li>)}</ul>
      </details>
    </>}
  </section>;
}
