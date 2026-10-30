import { useEffect, useRef, useState } from 'react';

export type VoiceCapability = { available: boolean; unavailable_reason?: string | null; model: string; max_duration_seconds: number };
export type ImageCapability = { available: boolean; unavailable_reason?: string | null; model: string };
type Model = { id: string; label: string; available: boolean; unavailable_reason?: string | null; data_policy?: string; description?: string };
type Catalog = { models: Model[]; active_model: string; default_model: string; capabilities: { voice: VoiceCapability } };

export default function ModelSelector({ projectId, busy, onBusyChange, onVoiceCapability, onImageCapability }: {
  projectId: string; busy: boolean; onBusyChange: (busy: boolean) => void;
  onVoiceCapability: (capability: VoiceCapability | null) => void; onImageCapability: (capability: ImageCapability | null) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [changing, setChanging] = useState(false);
  const selectionAbort = useRef<AbortController | null>(null);
  useEffect(() => () => { selectionAbort.current?.abort(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    onVoiceCapability(null); onImageCapability(null);
    fetch(`/api/models?project_id=${encodeURIComponent(projectId)}`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? 'Model availability could not be checked.');
        if (!Array.isArray(data.models)) throw new Error('The model list is incomplete.');
        if (!controller.signal.aborted) { setCatalog(data); setError(null); onVoiceCapability(data.capabilities?.voice ?? null); onImageCapability(data.capabilities?.image ?? null); }
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Model availability could not be checked.');
          onImageCapability({ available: false, unavailable_reason: 'Illustration availability could not be checked. Use Check models again.', model: '' });
          onVoiceCapability({ available: false, unavailable_reason: 'Voice availability could not be checked. Use Check models again.', model: '', max_duration_seconds: 60 });
        }
      });
    return () => controller.abort();
  }, [projectId, attempt, onVoiceCapability, onImageCapability]);

  async function choose(model: string) {
    if (busy || changing || !catalog) return;
    setChanging(true); onBusyChange(true); setError(null);
    const controller = new AbortController(); selectionAbort.current = controller;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/model`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model }), signal: controller.signal,
      });
      const data = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) throw new Error(data.detail ?? 'The model could not be changed. Try again.');
      setCatalog((current) => current ? { ...current, active_model: data.active_model ?? model } : current);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'The model could not be changed.'); }
    finally { if (!controller.signal.aborted) { setChanging(false); onBusyChange(false); } }
  }
  const active = catalog?.models.find((model) => model.id === catalog.active_model);
  return <div className="model-controls">
    <div className="model-selector-row">
      <label htmlFor="agent-model">Agent model</label>
      <select id="agent-model" value={catalog?.active_model ?? ''} disabled={!catalog || busy || changing}
        onChange={(event) => void choose(event.target.value)} aria-describedby="model-data-note model-session-note">
        {!catalog && <option value="">{error ? 'Models unavailable' : 'Checking models…'}</option>}
        {catalog?.models.map((model) => <option key={model.id} value={model.id} disabled={!model.available}>{model.label}{!model.available ? ' (unavailable)' : ''}</option>)}
      </select>
      {changing && <span role="status">Changing…</span>}
    </div>
    {active && <p className="model-data-note" id="model-data-note">{active.data_policy ?? (active.id.includes('contributor') ? 'Contributor: content may train Meta models. Use shareable inputs only.' : 'Standard mode: Meta states inputs are not used to train its models.')} {active.description}</p>}
    <details className="model-help"><summary>Model usage</summary><p id="model-session-note">This choice applies to this open session. Reopening a project uses the configured default. API usage follows the selected model; Wonder has a higher API cost than Spark.</p>
      {catalog?.models.filter((model) => !model.available).map((model) => <p key={model.id}>{model.label}: {model.unavailable_reason ?? 'Not advertised by this account. Check account access, then check models again.'}</p>)}
      <button type="button" onClick={() => setAttempt((value) => value + 1)} disabled={busy || changing}>Check models again</button>
    </details>
    {catalog && !catalog.models.some((model) => model.available) && <p className="model-error" role="status">No agent model is available for this account. Open Model usage for the reason and recheck access.</p>}
    {error && <p className="model-error" role="alert">{error} <button type="button" onClick={() => setAttempt((value) => value + 1)}>Check models again</button></p>}
  </div>;
}
