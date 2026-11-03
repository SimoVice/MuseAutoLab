import { useEffect, useState } from 'react';
import type { Project } from './types';
import './parts-workspace.css';

type Proposal = {
  project_id: string; project_revision: number;
  rows: { group_id: string; label: string; selected_product_label?: string; source_kind?: string; unit_price_basis?: string; quantity: number; unit: string;
    unit_price_low_usd: number | null; unit_price_high_usd: number | null;
    line_total_low_usd: number | null; line_total_high_usd: number | null;
    price_kind: string; price_note: string; source_url: string | null; fabrication_url?: string;
    fabrication_stl_url?: string;
    reference_observation?: { unit_price_usd: number; observed_on: string; url: string; scope: string };
    evidence: { kind: string; observed_at: string | null; url: string | null };
    alternatives: { label: string; url: string; note: string }[];
    component_ids: string[];
  }[];
  summary: { total_low_usd: number | null; total_high_usd: number | null; priced_count: number; unpriced_count: number; row_count: number; exclusions: string[] };
  limitations: string[];
};
const money = (value: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value);
function range(low: number | null, high: number | null) { return low == null || high == null ? 'Price needed' : low === high ? money(low) : `${money(low)} to ${money(high)}`; }
function safeUrl(value: string | null) { try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } }
const sourceLabels: Record<string, string> = {
  open_design_reference: 'Open design',
  selected_project_reference: 'Source project & files',
  supplier_search: 'Supplier search',
  supplier_category: 'Supplier category',
  fabrication_service: 'Fabrication service',
};

function sourceLabel(value: string) {
  if (/github\.com/.test(value)) return 'Source project & files';
  if (/\.stl|printables|thingiverse/i.test(value)) return '3D print files';
  return 'Purchase / product page';
}


export default function PartsProposal({ project, refreshKey, onSelect, compact = false, onOpen }: { compact?: boolean; onOpen?: () => void; project: Project; refreshKey: string; onSelect: (id: string) => void }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setProposal(null);
    setError('');
    fetch(`/api/projects/${encodeURIComponent(project.id)}/parts?revision=${project.revision}`, { signal: controller.signal })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? 'The parts list could not be loaded.');
        return (data.proposal ?? data.parts_proposal ?? data) as Proposal;
      })
      .then(data => {
        if (!controller.signal.aborted) {
          if (data.project_id !== project.id || data.project_revision !== project.revision) {
            throw new Error('The parts list belongs to another revision. Reload this list.');
          }
          setProposal(data);
        }
      })
      .catch(reason => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'The parts list could not be loaded.');
        }
      });
    return () => controller.abort();
  }, [project.id, project.revision, refreshKey, attempt]);
  if (error) return <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Reload parts</button></p>;
  if (!proposal) return <p role="status">Preparing the parts and price breakdown…</p>;
  const summary = proposal.summary;
  if (compact) return (
    <div className="design-budget-entry">
      <span>
        {summary.unpriced_count ? 'Priced items subtotal' : 'Listed parts estimate'}
        {' '}<strong>{range(summary.total_low_usd, summary.total_high_usd)}</strong>
      </span>
      <button type="button" onClick={onOpen}>View parts &amp; prices</button>
    </div>
  );
  const term = search.trim().toLowerCase();
  const matches = proposal.rows.filter(row => [row.label, row.selected_product_label, row.source_url]
    .some(value => value?.toLowerCase().includes(term)));
  const perPage = 3;
  const lastPage = Math.max(0, Math.ceil(matches.length / perPage) - 1);
  const currentPage = Math.min(page, lastPage);
  const start = currentPage * perPage;
  return <div className="parts-proposal">
    <div className="parts-total">
      <div>
        <h3>{summary.unpriced_count ? 'Priced items subtotal' : 'Listed parts total'}</h3>
        <strong>{range(summary.total_low_usd, summary.total_high_usd)}</strong>
      </div>
      <p>{summary.row_count} items, USD<br />Planning ranges, not a quote.</p>
    </div>

    {(proposal.rows.length > perPage || term) && <div className="parts-browse">
      <label>Find a part<input type="search" value={search} placeholder="Part, product or supplier" onChange={event => { setSearch(event.target.value); setPage(0); }} /></label>
      <nav aria-label="Parts pages"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} aria-label="Previous parts page">Previous</button>
        <span role="status">{matches.length ? `${start + 1}–${Math.min(start + perPage, matches.length)} of ${matches.length}` : '0 matches'}</span>
        <button type="button" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)} aria-label="Next parts page">Next</button>
      </nav>
    </div>}
    <div className="parts-table-scroll">
      <table className="parts-table">
        <caption>Components, quantities and prices for revision {project.revision}</caption>
        <thead>
          <tr>
            <th scope="col">Component / source</th>
            <th scope="col">Qty</th>
            <th scope="col">Unit price</th>
            <th scope="col">Line total</th>
          </tr>
        </thead>
        <tbody>
      {matches.length === 0 && <tr><td colSpan={4}>No matching parts. <button type="button" onClick={() => { setSearch(''); setPage(0); }}>Clear search</button></td></tr>}
      {matches.slice(start, start + perPage).map(row => {
        const source = safeUrl(row.source_url);
        const linkLabel = sourceLabels[row.source_kind ?? ''] ?? sourceLabel(row.source_url ?? '');
        const visibleComponents = row.component_ids
          .filter(id => project.design.components.some(part => part.id === id))
          .slice(0, 1);
        const priceLabel = row.price_kind === 'verified_supplier'
          ? 'Supplier price'
          : row.price_kind === 'model_estimate' ? 'Model estimate' : row.price_kind === 'included_in_base' ? 'Included in base' : 'Estimate';

        return (
          <tr key={row.group_id}>
            <th scope="row">
              <strong>{row.label}</strong>
              {row.selected_product_label && row.selected_product_label !== row.label && (
                <span>{row.selected_product_label}</span>
              )}
              <small>{priceLabel}</small>
              <div className="parts-links">
                {source && (
                  <a href={source} target="_blank" rel="noopener noreferrer">{linkLabel}</a>
                )}
                {visibleComponents.map(id => (
                  <button type="button" key={id} onClick={() => onSelect(id)}>
                    Show in 3D
                  </button>
                ))}
                {row.fabrication_url?.startsWith('/api/projects/') && (
                  <a href={row.fabrication_url} download>Download custom STEP</a>
                )}
                {row.fabrication_stl_url?.startsWith('/api/projects/') && (
                  <a href={row.fabrication_stl_url} download>Download custom STL</a>
                )}
              </div>
              <details className="parts-pricing-details">
                <summary>Price basis &amp; alternatives</summary>
                <p>{row.price_kind.replaceAll('_', ' ')}: {row.price_note}</p>
                <p>{row.unit_price_basis}</p>
                {row.evidence.observed_at && <p>
                  {row.price_kind === 'verified_supplier' ? 'Supplier price checked' : row.price_kind === 'model_estimate' ? 'Estimate generated' : 'Budget reference dated'}
                  {' '}{new Date(row.evidence.observed_at).toLocaleDateString('en-US', { timeZone: 'UTC' })}
                </p>}
                {safeUrl(row.evidence.url) && row.evidence.url !== row.source_url && (
                  <a href={safeUrl(row.evidence.url)} target="_blank" rel="noopener noreferrer">Price observation source</a>
                )}
                {row.reference_observation && (
                  <small>
                    Reference item only: {safeUrl(row.reference_observation.url) ? (
                      <a href={safeUrl(row.reference_observation.url)} target="_blank" rel="noopener noreferrer">{money(row.reference_observation.unit_price_usd)}</a>
                    ) : money(row.reference_observation.unit_price_usd)}
                    {' '}({row.reference_observation.observed_on}); {row.reference_observation.scope}.
                    {' '}Included within the allowance above, never added again.
                  </small>
                )}
                {row.alternatives.length > 0 && (
                  <div className="parts-alternatives">
                    <strong>Alternatives &amp; files</strong>
                    <ul>
                      {row.alternatives.map((alternative, index) => (
                        <li key={index}>
                          {safeUrl(alternative.url) ? (
                            <a href={safeUrl(alternative.url)} target="_blank" rel="noopener noreferrer">
                              {alternative.label}
                            </a>
                          ) : alternative.label}
                          <small>{alternative.note}</small>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </details>
            </th>
            <td>{row.quantity}</td>
            <td>{range(row.unit_price_low_usd, row.unit_price_high_usd)}</td>
            <td><strong>{range(row.line_total_low_usd, row.line_total_high_usd)}</strong></td>
          </tr>
        );
      })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={3}>
              {summary.unpriced_count ? 'Priced items subtotal' : 'Listed parts total'}
            </th>
            <td>{range(summary.total_low_usd, summary.total_high_usd)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
    <details className="resource-detail">
      <summary>Scope, missing costs &amp; exclusions</summary>
      <ul>
        {[...summary.exclusions, ...proposal.limitations].map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </details>
  </div>;
}
