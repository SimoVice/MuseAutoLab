import { useCallback, useEffect, useRef, useState } from 'react';
import ComponentCatalog from './ComponentCatalog';
import type { InstructionGuide, InstructionStep, ProcurementReport, ProcurementResponse, Project } from './types';
import './project-resources.css';

type Props = {
  project: Project; busy: boolean; onSelect: (id: string) => void;
  onChoose: (groupId: string, optionId: string) => void;
  onReport: (report: ProcurementReport | null) => void;
  instructionRequest?: object | null;
};

const money = (value: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
function date(value: string | null) { return value ? new Date(value).toLocaleString('en-US') : 'Not checked'; }
function sourceUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
async function read<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `Request failed (${response.status}). Try again.`);
  if (!data) throw new Error('The server returned an empty response. Try again.');
  return data as T;
}

function timeAware(data: ProcurementResponse): ProcurementResponse {
  const report = data.report;
  if (!report || Date.parse(report.expires_at) > Date.now() || !report.coverage.fresh_priced_count) return data;
  const rows = report.rows.map((row) => row.freshness === 'fresh' ? {
    ...row, freshness: 'stale' as const, last_known_price: row.unit_price,
    last_known_line_total: row.line_total, last_known_fetched_at: row.fetched_at,
    unit_price: null, line_total: null, issue: 'This observation expired. Refresh before budgeting.',
  } : row);
  return { ...data, report: { ...report, rows, known_partial_subtotal: 0,
    stale_last_known_subtotal: rows.reduce((total, row) => total + (row.last_known_line_total ?? 0), 0),
    coverage: { ...report.coverage, fresh_priced_count: 0, unpriced_count: rows.length,
      stale_priced_count: rows.filter((row) => row.last_known_line_total != null).length } } };
}

function Step({ step, guide, onSelect }: { step: InstructionStep; guide: InstructionGuide; onSelect: Props['onSelect'] }) {
  const status = { ready: 'Review step', reference_only: 'Follow source guide', needs_design: 'Design required' }[step.status];
  return <article className="instruction-step" aria-label={step.title}>
    <div className="resource-heading"><h3>{step.title}</h3><span className={`resource-status ${step.status === 'needs_design' ? 'attention' : ''}`}>{status}</span></div>
    {step.prerequisites.length > 0 && <p className="resource-note">Before this step: {step.prerequisites.map((id) => guide.steps.find((item) => item.id === id)?.title ?? id).join('; ')}.</p>}
    {step.component_ids.length > 0 && <div className="instruction-parts" aria-label="Parts in this step">{step.component_ids.map((id) => <button key={id} type="button" onClick={() => onSelect(id)}>Show {guide.parts.find((part) => part.component_id === id)?.label ?? id} in model</button>)}</div>}
    <ol className="instruction-actions">{step.instructions.map((instruction, index) => <li key={index}>{instruction}</li>)}</ol>
    {step.engineering_tasks.length > 0 && <div className="instruction-blockers"><h4>Resolve before building</h4>{step.engineering_tasks.map((task) => <div key={task.id}><p>{task.action}</p><ul>{(Array.isArray(task.acceptance_criteria) ? task.acceptance_criteria : [task.acceptance_criteria]).map((criterion, index) => <li key={index}>{criterion}</li>)}</ul></div>)}</div>}
    {step.checks.length > 0 && <div><h4>Check before continuing</h4><ul>{step.checks.map((check, index) => <li key={index}>{check}</li>)}</ul></div>}
    {(step.required_tools.length > 0 || step.required_materials.length > 0 || step.parts.length > 0) && <details className="resource-detail"><summary>Parts, tools and materials</summary>
      <ul>{step.required_tools.map((tool, index) => <li key={`tool-${index}`}>Tool: {tool.label}</li>)}{step.required_materials.map((material, index) => <li key={`material-${index}`}>Material: {material.label}</li>)}{step.parts.map((part) => <li key={part.component_id}>{part.label} ({part.component_id}) · {part.slot_id ? `slot ${part.slot_id}` : `center ${part.position_mm.join(', ')} mm`} · {part.geometry_basis.replace(/_/g, ' ')}{part.selected_variants.map((variant) => <div key={variant.group_id}>Selected: {variant.label} · procurement group quantity {variant.quantity}{sourceUrl(variant.source_url) && <> · <a href={sourceUrl(variant.source_url)} target="_blank" rel="noopener noreferrer">Component source</a></>}</div>)}</li>)}</ul>
      <p className="resource-note">{guide.coordinate_system}</p>
    </details>}
    {step.sources.length > 0 && <div className="instruction-sources"><h4>Source instructions</h4>{step.sources.map((source) => <div key={source.id}><a href={sourceUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title}</a><small>{source.scope} · checked {source.checked_on}</small></div>)}</div>}
  </article>;
}

export default function ProjectResources({ project, busy, onSelect, onChoose, onReport, instructionRequest }: Props) {
  const [panel, setPanel] = useState<'parts' | 'instructions' | null>(null);
  const [procurement, setProcurement] = useState<ProcurementResponse>({ state: 'not_refreshed', report: null });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [guide, setGuide] = useState<InstructionGuide | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [guideError, setGuideError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [guideAttempt, setGuideAttempt] = useState(0);
  const [focusInstructions, setFocusInstructions] = useState(false);
  const refreshRequest = useRef<AbortController | null>(null);
  const savedRequest = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);
  const procurementRef = useRef(procurement);
  procurementRef.current = procurement;
  const resourceBody = useRef<HTMLDivElement | null>(null);
  const base = `/api/projects/${encodeURIComponent(project.id)}`;
  const revision = project.revision;
  const report = procurement.report;
  const currentReport = report?.project_id === project.id && report.project_revision === revision && procurement.state === 'current' ? report : null;
  const reportId = currentReport?.report_id ?? null;

  const loadSaved = useCallback(() => {
    if (refreshRequest.current) return;
    savedRequest.current?.abort();
    const controller = new AbortController();
    savedRequest.current = controller;
    const sequence = ++requestSequence.current;
    const aged = timeAware(procurementRef.current);
    setProcurement(aged); onReport(aged.state === 'current' ? aged.report : null);
    setLoading(true);
    fetch(`${base}/procurement?revision=${revision}`, { signal: controller.signal })
      .then(read<ProcurementResponse>).then(timeAware).then((data) => { if (!controller.signal.aborted && sequence === requestSequence.current) { setProcurement(data); setPriceError(null); onReport(data.state === 'current' ? data.report : null); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setPriceError(reason instanceof Error ? reason.message : 'Cannot load saved prices. Refresh to try again.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
  }, [base, revision, onReport]);

  useEffect(() => {
    loadSaved();
    const visible = () => { if (document.visibilityState === 'visible') loadSaved(); };
    window.addEventListener('focus', loadSaved);
    document.addEventListener('visibilitychange', visible);
    return () => { savedRequest.current?.abort(); refreshRequest.current?.abort(); window.removeEventListener('focus', loadSaved); document.removeEventListener('visibilitychange', visible); };
  }, [loadSaved]);

  useEffect(() => {
    if (!currentReport?.coverage.fresh_priced_count) return;
    const delay = Date.parse(currentReport.expires_at) - Date.now();
    const timer = window.setTimeout(loadSaved, Math.max(0, delay) + 20);
    return () => window.clearTimeout(timer);
  }, [currentReport, loadSaved]);

  useEffect(() => {
    if (!instructionRequest) return;
    setPanel('instructions'); setFocusInstructions(true);
  }, [instructionRequest]);

  useEffect(() => {
    if (panel !== 'instructions' || !focusInstructions) return;
    const timer = requestAnimationFrame(() => { resourceBody.current?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }); resourceBody.current?.focus({ preventScroll: true }); setFocusInstructions(false); });
    return () => cancelAnimationFrame(timer);
  }, [panel, focusInstructions]);

  useEffect(() => {
    setGuide(null); setGuideError(null); setStepIndex(0);
    if (panel !== 'instructions') return;
    const controller = new AbortController();
    setGuideLoading(true);
    fetch(`${base}/instructions?revision=${revision}`, { signal: controller.signal })
      .then(read<InstructionGuide>).then((data) => {
        if (data.project_id !== project.id || data.project_revision !== revision) throw new Error('The instructions belong to an earlier revision. Load the current guide again.');
        if (data.procurement_report_id !== reportId) { loadSaved(); throw new Error('The pricing report changed while preparing instructions. Reload the current guide.'); }
        if (!controller.signal.aborted) setGuide(data);
      }).catch((reason: unknown) => { if (!controller.signal.aborted) setGuideError(reason instanceof Error ? reason.message : 'Cannot prepare instructions. Try again.'); })
      .finally(() => { if (!controller.signal.aborted) setGuideLoading(false); });
    return () => controller.abort();
  }, [panel, base, project.id, revision, reportId, guideAttempt, loadSaved]);

  async function refresh() {
    const controller = new AbortController();
    savedRequest.current?.abort(); requestSequence.current += 1; setLoading(false);
    refreshRequest.current?.abort(); refreshRequest.current = controller;
    setRefreshing(true); setPriceError(null);
    try {
      const response = await fetch(`${base}/procurement/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_revision: revision }), signal: controller.signal });
      const data = timeAware(await read<ProcurementResponse>(response));
      if (data.report?.project_id !== project.id || data.report?.project_revision !== revision) throw new Error('Prices belong to an earlier revision. Refresh this revision again.');
      if (!controller.signal.aborted) { setProcurement(data); onReport(data.state === 'current' ? data.report : null); }
    } catch (reason: unknown) { if (!controller.signal.aborted) setPriceError(reason instanceof Error ? reason.message : 'Catalog refresh failed. Try again.'); }
    finally { if (!controller.signal.aborted) { setRefreshing(false); refreshRequest.current = null; } }
  }

  const downloadsAvailable = !busy && !refreshing && !loading;
  const step = guide?.steps[stepIndex];
  return <section className="project-resources" aria-label="Parts and build resources">
    <div className="resource-entries">
      <button type="button" aria-expanded={panel === 'parts'} aria-controls="parts-pricing-panel" onClick={() => setPanel(panel === 'parts' ? null : 'parts')}>Parts &amp; pricing <small>US catalog · USD</small></button>
      <button type="button" aria-expanded={panel === 'instructions'} aria-controls="build-instructions-panel" onClick={() => setPanel(panel === 'instructions' ? null : 'instructions')}>Build instructions <small>Revision {revision} · preview and downloads</small></button>
    </div>
    {panel === 'parts' && <div id="parts-pricing-panel" className="resource-body">
      <div className="resource-heading"><div><h2>Parts &amp; pricing</h2><p>Selected parts for revision {revision}. US market, prices in USD.</p></div><button className="resource-primary" type="button" disabled={busy || refreshing || loading} onClick={() => void refresh()}>{refreshing ? 'Checking supplier catalogs…' : 'Refresh US prices'}</button></div>
      <p className="resource-note">Refresh checks supported supplier pages. It never purchases parts. Quotes, custom fabrication and unresolved specifications remain separate.</p>
      {loading && <p role="status">Loading saved catalog report…</p>}
      {refreshing && <p role="status">Retrieving catalog listings. Prices appear after the supplier checks finish.</p>}
      {priceError && <p className="resource-error" role="alert">{priceError} {report ? 'The previous report is retained below; its check dates still apply.' : 'Use Refresh US prices to try again.'}</p>}
      {procurement.state === 'stale_revision' && <p className="resource-error" role="status">The saved report belongs to an earlier project revision. Refresh for revision {revision}; downloads are disabled until then.</p>}
      {!report && !loading && <p className="resource-empty">No prices checked for this revision. Refresh US prices to retrieve a catalog report. Unknown costs are never counted as zero.</p>}
      {report && <>
        <div className="pricing-summary"><div><span>Fresh listed parts subtotal</span><strong>{report.coverage.fresh_priced_count ? money(report.known_partial_subtotal) : 'No fresh prices'}</strong><small>{report.coverage.fresh_priced_count} of {report.coverage.row_count} groups freshly priced</small></div><p>{report.coverage.unpriced_count} without fresh prices; {report.coverage.stale_priced_count} have last-known prices.<br />This is a partial parts subtotal. Complete machine cost is unknown.</p></div>
        {report.coverage.stale_priced_count > 0 && <p className="resource-note">Last-known prices, excluded from the fresh subtotal: {money(report.stale_last_known_subtotal)}. Recheck these listings before budgeting.</p>}
        {report.rows.some((row) => row.is_candidate) && <p className="resource-note">This subtotal includes sourcing candidates for review. Candidate listings do not replace accepted geometry or establish complete compatibility.</p>}
        <p className="resource-note">Report checked {date(report.fetched_at)}. Fresh through {date(report.expires_at)}.</p>
        <div className="procurement-rows">{report.rows.map((row) => <article className="procurement-row" key={row.group_id}>
          <div className="resource-heading"><h3>{row.label}</h3><span className={`resource-status ${row.freshness !== 'fresh' || row.status !== 'priced' ? 'attention' : ''}`}>{row.freshness === 'stale' ? 'Last-known price' : row.status === 'priced' ? 'Fresh listed price' : ({ unavailable: 'Unavailable', missing: 'Price missing', quote_needed: 'Quote needed', unsupported: 'Custom / not priced' }[row.status])}</span></div>
          {row.is_candidate && <p className="procurement-candidate">Sourcing candidate for review · accepted geometry unchanged</p>}
          <div className="procurement-facts"><span>Qty {row.quantity}{row.pack_size ? ` · pack of ${row.pack_size}` : ''}{row.pack_count ? ` · ${row.pack_count} pack${row.pack_count === 1 ? '' : 's'}` : ''}</span><span>SKU {row.sku ?? 'not specified'}</span>{row.freshness === 'fresh' && row.unit_price != null && <span>{money(row.unit_price)} / unit{row.pack_price != null && (row.pack_size ?? 1) > 1 ? ` · ${money(row.pack_price)} / pack` : ''}</span>}<strong>{row.freshness === 'fresh' && row.line_total != null ? `${money(row.line_total)} line total` : row.last_known_price != null ? `${money(row.last_known_price)} last known / unit` : row.unit_price != null ? 'Listed price excluded from subtotal' : 'Cost unknown'}</strong></div>
          {row.variant_title && <p className="resource-note">Variant: {row.variant_title}</p>}
          <p>{row.availability.replace(/([a-z])([A-Z])/g, '$1 $2')}</p>{row.issue && <p className="resource-note">{row.issue}</p>}{row.compatibility_note && <p className="resource-note">{row.compatibility_note}</p>}
          <div className="resource-links">{sourceUrl(row.price_source_url) && <a href={sourceUrl(row.price_source_url)} target="_blank" rel="noopener noreferrer">Price source</a>}{sourceUrl(row.availability_source_url) && row.availability_source_url !== row.price_source_url && <a href={sourceUrl(row.availability_source_url)} target="_blank" rel="noopener noreferrer">Availability source</a>}{sourceUrl(row.source_bom_url ?? null) && <a href={sourceUrl(row.source_bom_url ?? null)} target="_blank" rel="noopener noreferrer">Upstream BOM{row.source_bom_row ? ` · ${row.source_bom_row}` : ''}</a>}{row.component_ids.filter((id) => project.design.components.some((part) => part.id === id)).map((id) => <button key={id} type="button" onClick={() => onSelect(id)}>Show part in model</button>)}</div>
          {row.source_project_revision && <p className="resource-note">Source project revision: {row.source_project_revision}</p>}
          <small>Checked {date(row.freshness === 'stale' ? row.last_known_fetched_at : row.fetched_at)}</small>
        </article>)}</div>
        <details className="resource-detail"><summary>What the subtotal excludes</summary><ul>{report.exclusions.map((item, index) => <li key={index}>{item}</li>)}</ul></details>
        {currentReport && downloadsAvailable && <div className="resource-downloads" aria-label="Pricing report downloads">{['csv', 'json'].map((format) => <a key={format} href={`${base}/procurement/download?revision=${revision}&report_id=${encodeURIComponent(currentReport.report_id)}&format=${format}`} download>Download pricing {format.toUpperCase()}</a>)}</div>}
      </>}
      <details className="resource-detail"><summary>Component alternatives and integration notes</summary><ComponentCatalog sourcing={project.sourcing} busy={busy || refreshing} onChoose={onChoose} onHighlight={onSelect} /></details>
    </div>}
    {panel === 'instructions' && <div id="build-instructions-panel" className="resource-body" ref={resourceBody} tabIndex={-1}>
      <div className="resource-heading"><div><h2>Build instructions</h2><p>Technical review guide for the current design, revision {revision}.</p></div></div>
      <p className="resource-note">These steps combine source assembly references with your selected layout. Resolve design tasks before building; a preview does not establish hardware compatibility or tested operation.</p>
      {guideLoading && <p role="status">Preparing instructions from the current project…</p>}
      {guideError && <div className="resource-error" role="alert">{guideError} <button type="button" onClick={() => setGuideAttempt((attempt) => attempt + 1)}>Try instructions again</button></div>}
      {guide && <>
        <p className="resource-note">{guide.summary.total_steps} steps · {guide.summary.needs_design_steps} require design work · {guide.summary.reference_steps} use source guides. {guide.procurement_report_id ? 'Includes the selected procurement report.' : 'Pricing has not been refreshed; source and specification checks still apply.'}</p>
        <div className="instruction-navigation"><label htmlFor="instruction-step">Go to step</label><select id="instruction-step" value={stepIndex} onChange={(event) => { const index = Number(event.target.value); setStepIndex(index); const id = guide.steps[index]?.component_ids[0]; if (id && project.design.components.some((part) => part.id === id)) onSelect(id); }}>{guide.steps.map((item, index) => <option key={item.id} value={index}>{index + 1}. {item.title}</option>)}</select></div>
        {step && <Step step={step} guide={guide} onSelect={onSelect} />}
        <div className="instruction-pagination"><button type="button" disabled={stepIndex === 0} onClick={() => setStepIndex((index) => index - 1)}>Previous step</button><span>Step {guide.steps.length ? stepIndex + 1 : 0} of {guide.steps.length}</span><button type="button" disabled={stepIndex >= guide.steps.length - 1} onClick={() => setStepIndex((index) => index + 1)}>Next step</button></div>
        {downloadsAvailable && <div className="resource-downloads" aria-label="Instruction downloads">{['html', 'md', 'json'].map((format) => <a key={format} href={`${base}/instructions/download?revision=${revision}${guide.procurement_report_id ? `&report_id=${encodeURIComponent(guide.procurement_report_id)}` : ''}&format=${format}`} download>Download guide {format === 'md' ? 'Markdown' : format.toUpperCase()}</a>)}</div>}
      </>}
    </div>}
  </section>;
}
