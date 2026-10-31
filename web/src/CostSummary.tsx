import { useEffect, useRef, useState } from 'react';
import type { ProcurementReport, Project } from './types';

type Estimate = {
  expires_at?: string; project_id: string; project_revision: number; status: 'ready' | 'partial' | 'failed' | 'stale';
  summary: { known_plus_estimated_low_usd?: number | null; known_plus_estimated_high_usd?: number | null; verified_subtotal_usd: number; estimated_additional_low_usd: number | null; estimated_additional_high_usd: number | null; project_total_low_usd: number | null; project_total_high_usd: number | null; missing_count: number; estimated_count: number; verified_count: number; coverage_complete: boolean };
  rows: { group_id: string; label: string; source_kind: string; low_usd: number | null; high_usd: number | null; rationale?: string; assumptions?: string[]; issue?: string | null }[];
  exclusions: string[]; issue?: string | null;
};
const money = (value: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
const range = (low: number | null, high: number | null) => low == null || high == null ? 'Not estimated' : low === high ? money(low) : `${money(low)}–${money(high)}`;

export default function CostSummary({ project, report }: { project: Project; report: ProcurementReport | null }) {
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [loading, setLoading] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [expiryEpoch, setExpiryEpoch] = useState(0);
  const [estimateContext, setEstimateContext] = useState('');
  const manualRefresh = useRef(false);
  const hasDesign = Boolean(project.engineering_design);
  // A new supplier report invalidates the previous estimate once; failed calls never loop.
  const reportSignature = report ? JSON.stringify([report.report_id, report.expires_at, report.coverage, report.known_partial_subtotal]) : '';
  const contextKey = `${project.id}:${project.revision}:${reportSignature}`;
  useEffect(() => {
    const expires = estimate?.expires_at ? Date.parse(estimate.expires_at) : NaN;
    if (!estimate || ['failed', 'stale'].includes(estimate.status) || !Number.isFinite(expires) || expires <= Date.now()) return;
    const timer = window.setTimeout(() => setExpiryEpoch(value => value + 1), Math.min(expires - Date.now() + 20, 2147483647));
    return () => window.clearTimeout(timer);
  }, [estimate]);
  useEffect(() => {
    setEstimate(null); setIssue(null);
    const force = manualRefresh.current; manualRefresh.current = false;
    if (!hasDesign) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    async function load() {
      const endpoint = `/api/projects/${encodeURIComponent(project.id)}/cost-estimate`;
      try {
        let response = await fetch(`${endpoint}?revision=${project.revision}`, { signal: controller.signal });
        let data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? 'Cost estimate could not be checked.');
        if (!data.estimate || data.state !== 'current' || force || (data.estimate.expires_at && Date.parse(data.estimate.expires_at) <= Date.now())) {
          response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_revision: project.revision, force }), signal: controller.signal });
          data = await response.json();
          if (!response.ok) throw new Error(data.detail ?? 'Cost estimate could not be prepared.');
        }
        if (!controller.signal.aborted) { setEstimate(data.estimate ?? null); setEstimateContext(contextKey); setIssue(data.estimate?.issue ?? null); }
      } catch (error) { if (!controller.signal.aborted) setIssue(error instanceof Error ? error.message : 'Cost estimate is unavailable.'); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [project.id, project.revision, hasDesign, contextKey, attempt, expiryEpoch]);
  const current = estimateContext === contextKey && (!estimate?.expires_at || Date.parse(estimate.expires_at) > Date.now()) && estimate?.project_id === project.id && estimate.project_revision === project.revision && !['failed', 'stale'].includes(estimate.status) ? estimate : null;
  const summary = current?.summary;
  const verified = report ? (report.coverage.fresh_priced_count && Date.parse(report.expires_at) > Date.now() ? report.known_partial_subtotal : null) : summary?.verified_count ? summary.verified_subtotal_usd : null;
  return <section className="cost-block cost-summary" aria-label="Project cost estimate" aria-busy={loading}>
    <span>Project cost · USD</span>
    <strong>{!hasDesign ? 'Estimate appears with your design' : loading ? 'Estimating project cost…' : !summary ? 'Estimate unavailable' : summary.coverage_complete ? range(summary.project_total_low_usd, summary.project_total_high_usd) : summary.known_plus_estimated_low_usd != null && summary.known_plus_estimated_high_usd != null ? `${range(summary.known_plus_estimated_low_usd, summary.known_plus_estimated_high_usd)} covered items` : 'Partial cost estimate'}</strong>
    {hasDesign && <dl className="cost-breakdown">
      <div><dt>Verified supplier prices</dt><dd>{verified == null ? 'Not checked' : money(verified)}</dd></div>
      <div><dt>Additional model estimate</dt><dd>{range(summary?.estimated_additional_low_usd ?? null, summary?.estimated_additional_high_usd ?? null)}</dd></div>
      <div><dt>Missing prices</dt><dd>{summary ? `${summary.missing_count} groups` : 'Coverage not established'}</dd></div>
    </dl>}
    <small>{hasDesign ? 'Planning estimate, not a quote. Complete machine cost remains unknown until every required item is covered. Excludes shipping and taxes.' : 'US supplier prices and model estimates will be shown separately.'}</small>
    {issue && <small role="status">{issue}</small>}
    {hasDesign && !loading && <details className="cost-estimate-details"><summary>Estimate details & refresh</summary>
      {current?.rows.map(row => <div key={row.group_id}><strong>{row.label}</strong><p>{row.source_kind === 'model_estimate' ? 'Model estimate' : row.source_kind === 'verified_supplier' ? 'Verified supplier' : 'Missing price'}: {range(row.low_usd, row.high_usd)}. {row.rationale ?? row.issue}</p>{row.assumptions?.length ? <ul>{row.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul> : null}</div>)}
      {current?.exclusions.length ? <p>Excluded: {current.exclusions.join('; ')}</p> : null}
      <button type="button" className="new-project-button" onClick={() => { manualRefresh.current = true; setAttempt(value => value + 1); }}>Refresh cost estimate</button>
    </details>}
  </section>;
}
