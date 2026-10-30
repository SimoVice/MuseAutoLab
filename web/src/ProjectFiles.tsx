import { useCallback, useEffect, useRef, useState } from 'react';
import type { AssemblyStep, ExportFileEntry, ExportJob, Project } from './types';

type Props = {
  project: Project;
  onSelect: (componentId: string | null) => void;
};

function encodeFilePath(name: string): string {
  return name.split('/').map((segment) => encodeURIComponent(segment)).join('/');
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return '—';
  if (size < 1024) return `${size} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)} ${units[unit]}`;
}

function stageLabel(job: ExportJob, digitalPlatform: boolean): string {
  if (job.status === 'ready') return 'Ready';
  if (job.status === 'failed') return 'Failed';
  if (job.status === 'stale') return 'Out of date';
  const done = Math.max(0, Math.min(job.completed_stages, job.total_stages));
  const stage = { queued: 'Queued', cad: 'Building CAD files', documents: 'Preparing documents', simulation: digitalPlatform ? 'Recording simulation scope' : 'Running physics', archive: 'Packaging downloads' }[job.stage];
  return stage ?? `Stage ${done}/${job.total_stages}`;
}

async function readError(response: Response): Promise<string> {
  const data: unknown = await response.json().catch(() => null);
  if (data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string') {
    return (data as { detail: string }).detail;
  }
  return `Request failed (${response.status}). Please try again.`;
}

export default function ProjectFiles({ project, onSelect }: Props) {
  const [job, setJob] = useState<ExportJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [guide, setGuide] = useState<string | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [guideError, setGuideError] = useState<string | null>(null);
  const guideRequestRef = useRef<AbortController | null>(null);
  const pollRef = useRef<number | null>(null);
  const epochRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);
  const projectKey = `${project.id}:${project.revision}:${project.status}`;

  const clearPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Reset pending/export views on project id/revision or status change.
  useEffect(() => {
    epochRef.current += 1;
    requestRef.current?.abort();
    clearPoll();
    setJob(null);
    setError(null);
    setStarting(false);
    setStepIndex(0);
    guideRequestRef.current?.abort();
    setGuide(null);
    setGuideLoading(false);
    setGuideError(null);
    return () => {
      epochRef.current += 1;
      requestRef.current?.abort();
      guideRequestRef.current?.abort();
      clearPoll();
    };
  }, [projectKey, clearPoll]);

  const fetchStatus = useCallback(
    async (jobId: string, signal: AbortSignal) => {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/exports/${encodeURIComponent(jobId)}`, { signal });
      if (!response.ok) throw new Error(await readError(response));
      const data = (await response.json()) as ExportJob;
      return data;
    },
    [project.id],
  );

  const pollUntilDone = useCallback(
    (jobId: string, epoch: number, signal: AbortSignal) => {
      clearPoll();
      const poll = async () => {
        if (epochRef.current !== epoch || signal.aborted) return;
        try {
          const updated = await fetchStatus(jobId, signal);
          if (epochRef.current !== epoch || signal.aborted) return;
          setJob(updated);
          if (updated.status === 'queued' || updated.status === 'running') {
            pollRef.current = window.setTimeout(() => void poll(), 1000);
          }
        } catch (reason: unknown) {
          if (epochRef.current !== epoch || signal.aborted) return;
          setError(reason instanceof Error ? reason.message : 'Could not check generation. Retry to reconnect.');
        }
      };
      pollRef.current = window.setTimeout(() => void poll(), 1000);
    },
    [clearPoll, fetchStatus],
  );

  async function start() {
    clearPoll();
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++epochRef.current;
    setStarting(true);
    setError(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/exports`, { method: 'POST', signal: controller.signal });
      if (!response.ok) throw new Error(await readError(response));
      const created = (await response.json()) as ExportJob;
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setJob(created);
      setStepIndex(0);
      if (created.status === 'ready' || created.status === 'failed' || created.status === 'stale') return;
      pollUntilDone(created.id, epoch, controller.signal);
    } catch (reason) {
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : 'Could not start file generation.');
    } finally {
      if (epochRef.current === epoch && !controller.signal.aborted) setStarting(false);
    }
  }

  function retry() {
    clearPoll();
    setError(null);
    if (job && (job.status === 'queued' || job.status === 'running')) {
      // A failed status request does not mean the expensive export stopped.
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      pollUntilDone(job.id, ++epochRef.current, controller.signal);
      return;
    }
    void start();
  }

  async function openGuide() {
    guideRequestRef.current?.abort();
    const controller = new AbortController();
    guideRequestRef.current = controller;
    const epoch = epochRef.current;
    setGuideLoading(true);
    setGuideError(null);
    try {
      const response = await fetch(fileHref('assembly-guide.html'), { signal: controller.signal });
      if (!response.ok) throw new Error(await readError(response));
      const document = await response.text();
      if (epochRef.current === epoch && !controller.signal.aborted) setGuide(document);
    } catch (reason: unknown) {
      if (epochRef.current === epoch && !controller.signal.aborted) {
        setGuideError(reason instanceof Error ? reason.message : 'Could not open the guide. Try the download.');
      }
    } finally {
      if (epochRef.current === epoch && !controller.signal.aborted) setGuideLoading(false);
    }
  }

  const steps: AssemblyStep[] = job?.assembly_steps ?? [];
  const currentStep: AssemblyStep | null = steps.length > 0 ? steps[Math.min(stepIndex, steps.length - 1)] : null;

  // Highlight current step's first component through existing onSelect.
  useEffect(() => {
    if (job?.status !== 'ready' || !currentStep) return;
    const first = currentStep.component_ids[0] ?? null;
    if (first) onSelect(first);
  }, [job?.status, currentStep, onSelect]);

  const pending = job !== null && (job.status === 'queued' || job.status === 'running');
  const isCommercial = project.design.platform?.id === 'opentrons-ot2';
  const digitalPlatform = Boolean(project.design.foundation || isCommercial);
  const files: ExportFileEntry[] = job?.files ?? [];
  const primaryNames = new Set(['assembly-guide.html', 'bill-of-materials.csv', 'cad/workstation.step', 'simulation/result.json', 'automation/preview.py']);
  function fileCards(entries: ExportFileEntry[]) {
    return entries.map((file) => (
      <li key={file.name} className="file-card">
        <div><strong>{file.name}</strong><span>{formatBytes(file.size)}</span></div>
        <a href={fileHref(file.name)} download={file.name.split('/').pop()} aria-label={`Download ${file.name}`}>Download</a>
      </li>
    ));
  }
  const zipHref =
    job?.status === 'ready' && job.download_url
      ? job.download_url
      : job?.status === 'ready'
        ? `/api/projects/${encodeURIComponent(project.id)}/exports/${encodeURIComponent(job.id)}/download`
        : null;

  function fileHref(name: string): string {
    return `/api/projects/${encodeURIComponent(project.id)}/exports/${encodeURIComponent(job?.id ?? '')}/files/${encodeFilePath(name)}`;
  }

  return (
    <section className={`files-card${guide ? ' files-card-guide-open' : ''}`} aria-labelledby="files-title">
      <div className="files-heading">
        <div>
          <h2 id="files-title">Project files</h2>
          <p>{isCommercial ? 'Schematic CAD, setup guide and preparation plan' : 'CAD, assembly guide and preparation plan'} for revision {project.revision}.</p>
          {digitalPlatform && <p className="files-note">Digital proposal only. Physics and hardware control are unavailable for this platform.</p>}
        </div>
        {job && <span className={`files-status files-status-${job.status}`}>{stageLabel(job, digitalPlatform)}</span>}
      </div>

      {!job && (
        <div className="files-start">
          <button type="button" className="files-button" onClick={() => void start()} disabled={starting}>
            {starting ? 'Starting…' : 'Generate project files'}
          </button>
          <p className="files-note">Generates CAD, documents and an archive for revision {project.revision}.</p>
          {project.design.foundation && <p className="files-note">Full source CAD can take several minutes to export. Progress follows completed stages.</p>}
        </div>
      )}

      {job && pending && (
        <div className="files-progress" role="status">
        <progress aria-label="Project generation progress" value={job.completed_stages} max={job.total_stages} />
          {stageLabel(job, digitalPlatform)} — {Math.max(0, Math.min(job.completed_stages, job.total_stages))}/{job.total_stages} stages complete.
        </div>
      )}

      {error && (
        <div className="files-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={retry}>{pending ? 'Reconnect to generation' : 'Retry generation'}</button>
        </div>
      )}

      {job && (job.status === 'failed' || job.status === 'stale') && (
        <div className="files-error" role="alert">
          <span>{job.status === 'stale' ? 'This package is out of date for the current revision.' : job.error || 'File generation failed.'}</span>
          <button type="button" onClick={retry}>Retry generation</button>
        </div>
      )}

      {job && job.status === 'ready' && (
        <>
          {zipHref && (
            <a className="files-button files-zip" href={zipHref} download>
              Download project ZIP
            </a>
          )}
          {files.some((file) => file.name === 'assembly-guide.html') && (
            <div className="files-start">
              <button type="button" className="preview-button" disabled={guideLoading} onClick={() => guide ? setGuide(null) : void openGuide()}>
                {guideLoading ? 'Opening guide…' : guide ? 'Close guide' : 'Read project guide'}
              </button>
              {guideError && <p className="files-error" role="alert">{guideError}</p>}
            </div>
          )}
          {guide && <iframe title={`Project guide — revision ${project.revision}`} srcDoc={guide} sandbox="" referrerPolicy="no-referrer" style={{ width: '100%', height: 'min(75vh, 800px)', minHeight: 420, border: '1px solid #d3e3df', borderRadius: 12, marginTop: 12 }} />}
          <ul className="files-list">
            {fileCards(files.filter((file) => primaryNames.has(file.name)))}
          </ul>
          <details className="files-other"><summary>All supporting files · {files.filter(file => !primaryNames.has(file.name)).length}</summary>
            <ul className="files-list">{fileCards(files.filter((file) => !primaryNames.has(file.name)))}</ul>
          </details>
          {files.length === 0 && <p className="files-note">No files returned.</p>}

          {steps.length > 0 && currentStep && (
            <div className="files-steps" aria-live="polite">
              <div className="files-steps-heading">
                <h3>Assembly guide</h3>
                <span>Step {Math.min(stepIndex + 1, steps.length)} of {steps.length}</span>
              </div>
              <p className="files-step-title">{currentStep.title}</p>
              {currentStep.requires_design && <p className="files-note">Mounts and interfaces require detailed design before assembly.</p>}
              {currentStep.instructions.length > 0 && (
                <ul className="files-step-list">
                  {currentStep.instructions.map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ul>
              )}
              {currentStep.checks.length > 0 && (
                <>
                  <p className="files-subhead">Checks</p>
                  <ul className="files-step-list">
                    {currentStep.checks.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </>
              )}
              <div className="files-step-controls">
                <button type="button" className="preview-button" onClick={() => setStepIndex((v) => Math.max(0, v - 1))} disabled={stepIndex <= 0}>
                  Previous step
                </button>
                <button
                  type="button"
                  className="preview-button"
                  onClick={() => setStepIndex((v) => Math.min(steps.length - 1, v + 1))}
                  disabled={stepIndex >= steps.length - 1}
                >
                  Next step
                </button>
              </div>
            </div>
          )}

          <div className="files-future" aria-label="Planned interfaces">
            <p className="files-subhead">Planned interfaces (future)</p>
            <p>Camera and robot arm control/data adapters are planned only. Mount regions, loads, power, keep-out, field of view, reach and compatibility are to be verified. No reserved physical space is promised.</p>
          </div>
        </>
      )}
    </section>
  );
}
