import { useEffect, useRef, useState } from 'react';
import type { ImageCapability } from './ModelSelector';

type Illustration = {
  image_data_url: string; model: string; project_id: string; project_revision: number;
  reference_sha256: string; image_sha256: string;
};

export default function IllustrationPanel({ projectId, revision, capability, disabled, capture }: {
  projectId: string; revision: number; capability: ImageCapability | null; disabled: boolean;
  capture: () => Promise<string>;
}) {
  const [phase, setPhase] = useState<'idle' | 'capturing' | 'generating'>('idle');
  const [reference, setReference] = useState<string | null>(null);
  const [illustration, setIllustration] = useState<Illustration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const operation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const busy = phase !== 'idle';
  useEffect(() => () => { operation.current += 1; controller.current?.abort(); }, []);

  function cancel() {
    operation.current += 1; controller.current?.abort(); controller.current = null;
    setPhase('idle'); setReference(null); setError(null); setNotice('Illustration cancelled. Your project files are still available.');
  }
  async function generate() {
    if (busy || disabled || !capability?.available) return;
    const current = ++operation.current;
    const abort = new AbortController(); controller.current = abort;
    setError(null); setNotice(null); setPhase('capturing');
    try {
      const original = await capture();
      if (operation.current !== current) return;
      setReference(original); setPhase('generating');
      const timeout = window.setTimeout(() => abort.abort(), 160000);
      let response: Response;
      let data: Illustration & { detail?: string };
      try {
        response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/illustration`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
          body: JSON.stringify({ project_revision: revision, reference_image_data_url: original }),
        });
        data = await response.json();
      } finally { window.clearTimeout(timeout); }
      if (operation.current !== current) return;
      if (!response.ok) throw new Error(data.detail ?? 'The illustration could not be generated. Your project files are still available.');
      if (data.project_id !== projectId || data.project_revision !== revision) throw new Error('This illustration belongs to an older project view. Generate a new one.');
      if (!data.image_data_url?.startsWith('data:image/png;base64,')) throw new Error('The illustration response was incomplete. Try again when ready.');
      setIllustration(data);
    } catch (reason) {
      if (operation.current !== current) return;
      setError(reason instanceof Error && reason.name !== 'AbortError' ? reason.message : 'Illustration generation timed out. You can try again when ready.');
    } finally {
      if (operation.current === current) { setPhase('idle'); controller.current = null; }
    }
  }
  return <details className="illustration-panel">
    <summary>Project illustration <span>Optional</span></summary>
    <p>Generate a presentation image from the current 3D view with Muse Image. Engineering decisions and assembly steps remain in your project files.</p>
    {!illustration && <div className="illustration-actions">
      <button type="button" onClick={() => void generate()} disabled={disabled || busy || !capability?.available}>Generate with Muse Image</button>
      {busy && <button type="button" onClick={cancel}>Cancel illustration</button>}
    </div>}
    {!capability?.available && <p className="illustration-note">{capability?.unavailable_reason ?? 'Checking illustration availability…'}</p>}
    {busy && <p className="illustration-note" role="status">{phase === 'capturing' ? 'Capturing your current model view…' : 'Generating with Muse Image…'}</p>}
    {notice && <p className="illustration-note" role="status">{notice}</p>}
    {error && <p className="illustration-error" role="alert">{error}</p>}
    {illustration && <figure className="illustration-result">
      <img src={illustration.image_data_url} alt={`AI-generated presentation illustration for project revision ${revision}`} />
      <figcaption><strong>AI-generated illustration — not a technical drawing</strong><span>Revision {revision} · {illustration.model}. Review against the original model view; visual details may differ.</span></figcaption>
      <a className="illustration-download" href={illustration.image_data_url} download={`museautolab-illustration-r${revision}.png`}>Download illustration PNG</a>
    </figure>}
    {reference && <details className="illustration-reference"><summary>Compare with original model view</summary><img src={reference} alt={`Original 3D model view for project revision ${revision}`} /><p>Original model view used for this request.</p></details>}
  </details>;
}
