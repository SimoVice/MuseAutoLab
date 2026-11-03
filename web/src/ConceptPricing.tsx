import { useEffect, useState } from 'react';
import CostSummary from './CostSummary';
import type { ProcurementReport, ProcurementResponse, Project } from './types';

export default function ConceptPricing({ project }: { project: Project }) {
  const [report, setReport] = useState<ProcurementReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const cancel = new AbortController();
    const base = `/api/projects/${encodeURIComponent(project.id)}/procurement`;
    setLoading(true); setError(''); setReport(null);
    async function load() {
      try {
        const response = refresh
          ? await fetch(base + '/refresh', { method: 'POST', signal: cancel.signal,
              headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_revision: project.revision }) })
          : await fetch(base + `?revision=${project.revision}`, { signal: cancel.signal });
        if (!response.ok) throw new Error('Supplier prices could not be checked.');
        const data: ProcurementResponse = await response.json();
        if (!cancel.signal.aborted) setReport(data.state === 'current' && data.report?.project_id === project.id &&
          data.report.project_revision === project.revision ? data.report : null);
      } catch (issue) {
        if (!cancel.signal.aborted) setError(issue instanceof Error ? issue.message : 'Supplier prices unavailable.');
      } finally {
        if (!cancel.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => cancel.abort();
  }, [project.id, project.revision, refresh]);
  return <div>
    {!loading && <CostSummary project={project} report={
      report?.project_id === project.id && report.project_revision === project.revision ? report : null
    } />}
    <button type="button" className="new-project-button" disabled={loading}
      onClick={() => setRefresh(value => value + 1)}>{loading ? 'Checking supplier prices…' : 'Check US supplier prices'}</button>
    {error && <p role="status">{error}</p>}
  </div>;
}
