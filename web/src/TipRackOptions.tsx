import { useEffect, useState } from 'react';
import type { Project, TipRackOptions as Options } from './types';
import './tip-rack-options.css';

const number = (value: number) => new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value);
export function tipDimensions(size: number[]) { return `${size.map(number).join(' × ')} mm`; }

function safeUrl(value: string | null | undefined) {
  try { const url = new URL(value ?? ''); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}

export default function TipRackOptions({ project, busy, onChoose, onInspect }: {
  project: Project; busy: boolean; onChoose: (profileId: string) => void; onInspect: () => void;
}) {
  const [data, setData] = useState<Options | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(null);
    fetch(`/api/projects/${encodeURIComponent(project.id)}/tip-rack-options?revision=${project.revision}`, { signal: controller.signal })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : 'Cannot load tip rack alternatives. Try again.');
        if (result.revision !== project.revision) throw new Error('These alternatives belong to an earlier revision. Try again.');
        return result as Options;
      }).then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Cannot load alternatives. Try again.'); });
    return () => controller.abort();
  }, [project.id, project.revision, attempt]);

  const current = project.design.components.find((component) => component.id === 'tip-rack');
  const options = data?.options.filter((option) => option.geometry?.profile_id &&
    (option.geometry.effect !== 'printable_geometry' && option.geometry.profile_id !== 'custom_printed_tip_rack' || data.printer_available === 'yes')) ?? [];
  return <section className="tip-rack-options" aria-label="Tip rack alternatives">
    <div className="tip-options-heading"><h3>Tip rack alternatives</h3><span>Revision {project.revision}</span></div>
    {current && <p className="tip-options-current">Current model: {tipDimensions(current.size)} <small>width × height × depth</small> <button type="button" onClick={onInspect}>Inspect tip rack</button></p>}
    {!data && !error && <p role="status">Loading source-backed alternatives…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt((value) => value + 1)}>Try alternatives again</button></p>}
    {data && !data.supported && <p>This platform does not support replacing the tip rack. Discuss a supported layout in chat.</p>}
    {data?.supported && <>
      <p className="tip-options-note">Selecting a different product updates its actual model dimensions. A supplier change for the same product keeps its geometry.</p>
      <div className="tip-options-list">{options.map((option) => {
        const geometry = option.geometry!;
        const selected = data.selected_profile_id === geometry.profile_id;
        const printable = geometry.profile_id === 'custom_printed_tip_rack';
        const dimensionsNeeded = geometry.effect === 'requires_dimensions';
        const source = safeUrl(geometry.source?.source_url ?? geometry.source_url ?? option.source_url);
        const size = geometry.size_mm ?? (selected ? project.tip_rack?.size_mm : null);
        return <article key={option.id} className={`tip-option ${selected ? 'selected' : ''}`} aria-label={option.label}>
          <div className="tip-option-title"><h4>{option.label}</h4>{selected && <span>In the model</span>}</div>
          <p>{option.supplier}{option.sku ? ` · ${option.sku}` : ''}</p>
          {size ? <p className="tip-option-dimensions">{tipDimensions(size)} <small>width × height × depth</small></p> : <p className="tip-option-dimensions">{printable ? 'Sized from your tip measurements' : 'Product dimensions required'}</p>}
          {geometry.details && <p className="tip-option-pattern">{geometry.details.positions != null && `${geometry.details.positions} positions`}{geometry.details.bore_diameter_mm != null && ` · ${number(geometry.details.bore_diameter_mm)} mm reference opening`}{geometry.details.first_center_xz_mm && <small>First position X/Z: {geometry.details.first_center_xz_mm.map(number).join(' / ')} mm from rack center</small>}</p>}
          {geometry.placement && !selected && <p className={`tip-option-placement ${geometry.placement.status}`}><strong>{geometry.placement.status === 'requires_shift' ? `Requires ${number(geometry.placement.shift_mm ?? 0)} mm repositioning` : geometry.placement.status === 'unavailable' ? 'Does not fit this layout' : 'Fits the current position'}</strong><span>{geometry.placement.message}</span>{geometry.placement.status === 'requires_shift' && geometry.placement.shift_xz_mm && <small>Tip rack only: X {number(geometry.placement.shift_xz_mm[0])} mm, Z {number(geometry.placement.shift_xz_mm[1])} mm. Choosing this rack accepts this draft placement.</small>}</p>}
          <p className="tip-options-note">{geometry.basis?.replace(/_/g, ' ')}{geometry.source?.scope || geometry.scope ? ` · ${geometry.source?.scope ?? geometry.scope}` : ''}</p>
          {geometry.source?.revision && <details className="tip-option-provenance"><summary>Geometry provenance</summary><p>Source revision {geometry.source.revision}</p>{geometry.source.sha256 && <p>SHA-256 {geometry.source.sha256}</p>}{geometry.source.license && <p>Source license: {safeUrl(geometry.source.license_url) ? <a href={safeUrl(geometry.source.license_url)} target="_blank" rel="noopener noreferrer">{geometry.source.license}</a> : geometry.source.license}</p>}</details>}
          <p className="tip-option-price">{option.unit_price == null || option.price_kind === 'unpriced' ? 'Price and availability not verified' : `${option.price_kind === 'starting_at' ? 'From ' : ''}${new Intl.NumberFormat('en-US', { style: 'currency', currency: project.sourcing.currency }).format(option.unit_price)} · catalog snapshot`}<small>{option.unit_price != null && option.checked_on && option.checked_on !== 'Not researched' ? `Price checked ${option.checked_on}` : 'No dated price observation'}</small></p>
          {option.compatibility_note !== (geometry.source?.scope ?? geometry.scope) && <p className="tip-options-note">{option.compatibility_note}</p>}
          <div className="tip-option-actions">{source && <a href={source} target="_blank" rel="noopener noreferrer">{printable ? 'Design basis' : 'Product / geometry source'}</a>}<button type="button" disabled={busy || selected || geometry.placement?.status === 'unavailable'} onClick={() => onChoose(geometry.profile_id)}>{selected ? 'Selected' : geometry.placement?.status === 'unavailable' ? 'Revise layout in chat' : dimensionsNeeded || printable && !geometry.size_mm ? 'Discuss dimensions in chat' : geometry.effect === 'supplier_only' ? 'Use this supplier' : 'Use this rack'}</button></div>
        </article>;
      })}</div>
      <p className="tip-options-note tip-printer-status">{data.printer_available === 'yes' ? '3D printer access confirmed in this project. Printable fit still requires actual tip dimensions.' : data.printer_available === 'no' ? 'No 3D printer access recorded. Commercial alternatives are shown.' : '3D printer access is not confirmed. Continue in chat before exploring a printable rack.'}</p>
    </>}
  </section>;
}
