import { useEffect, useState } from 'react';

type Result = {
  project_id: string; project_revision: number; model: string;
  plan: { objective: string; steps: { task: string; equipment_role: string; handoff: string; acceptance_check: string }[]; open_questions: string[] };
};

export default function FunctionalPlan({ id, revision }: { id: string; revision: number }) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [download, setDownload] = useState('');
  useEffect(() => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    setDownload(url);
    return () => URL.revokeObjectURL(url);
  }, [result]);
  async function generate() {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}/functional-plan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_revision: revision }),
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'The plan is unavailable.');
      const data: Result = await response.json();
      if (data.project_id !== id || data.project_revision !== revision) throw new Error('The brief has changed. Open its current revision.');
      setResult(data);
    } catch (issue) { setError(issue instanceof Error ? issue.message : 'The plan could not be prepared.'); }
    finally { setBusy(false); }
  }

  return <section aria-label="Functional plan" className="functional-plan">
    <h3>Functional plan</h3>
    {result ? <>
      <p>{result.plan.objective}</p>
      <ol>{result.plan.steps.map((step, i) => <li key={i}>
        <strong>{step.task}</strong><p>{step.equipment_role}</p>
        <p><b>Handoff</b> {step.handoff}</p><p><b>Acceptance check</b> {step.acceptance_check}</p>
      </li>)}</ol>
      <h4>Open specifications</h4><ul>{result.plan.open_questions.map((item, i) => <li key={i}>{item}</li>)}</ul>
      <p>Proposed for review · revision {revision} · {result.model}</p>
      {download && <a className="brief-download" href={download} download="functional-plan.json">Download functional plan</a>}
    </> : <>
      <p>Turn the recorded brief into proposed operations, equipment roles, handoffs and checks to run before selecting hardware.</p>
      <button className="new-project-button" onClick={() => void generate()} disabled={busy}>{busy ? 'Preparing functional plan…' : 'Develop functional plan'}</button>
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
