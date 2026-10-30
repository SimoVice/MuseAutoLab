import type { LabwareBrief, LabwareRack, RackSpec } from './types';
import './labware-rack.css';

const labels: Record<keyof RackSpec, string> = {
  body_diameter_max_mm: 'Maximum body diameter', rim_diameter_min_mm: 'Minimum support rim diameter',
  cap_diameter_max_mm: 'Maximum closed cap diameter', below_rim_height_mm: 'Height below the support rim',
  count: 'Tube positions', columns: 'Columns', pitch_mm: 'Center spacing', radial_clearance_mm: 'Radial clearance',
  max_width_mm: 'Maximum rack width', max_depth_mm: 'Maximum rack depth', max_height_mm: 'Maximum rack height',
};
const number = (value: number) => new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value);
const dimensions = (size: number[]) => `${size.map(number).join(' × ')} mm`;

export default function LabwareRackPanel({ brief, rack, onSelect, targetCount = 0 }: {
  brief?: LabwareBrief | null; rack?: LabwareRack | null; onSelect: (id: string) => void;
  targetCount?: number;
}) {
  if (!brief && !rack) return null;
  const spec = brief?.spec ?? rack?.spec ?? {};
  const sources = brief?.sources ?? rack?.provenance.sources ?? {};
  const missing = brief?.missing_fields ?? [];
  const needsDimensions = missing.length > 0;
  return <section className="labware-rack-panel" aria-labelledby="rack-title">
    <div className="rack-heading"><div><h2 id="rack-title">{rack ? 'Your tube rack' : 'Tube rack specification'}</h2><p>Rim-supported rack for the sample position.</p></div><span className={needsDimensions ? 'rack-state attention' : 'rack-state'}>{needsDimensions ? 'Dimensions needed' : rack ? 'Parametric design' : 'Ready to design'}</span></div>
    {needsDimensions && <div className="rack-missing"><p>Continue in chat with these tube measurements:</p><ul>{missing.map((field) => <li key={field}>{labels[field as keyof RackSpec] ?? field.replace(/_/g, ' ')}</li>)}</ul><small>Measure the widest body section that must pass through the hole; the smallest supporting rim at its underside; the widest closed cap, including rim and closed hinge protrusions; and the underside-of-rim to tip height. A nominal 1.5–2 mL volume does not define fit.</small></div>}
    {rack && <>
      <div className="rack-results"><div><span>Design capacity</span><strong>{rack.derived.count} tubes</strong><small>{rack.derived.rows} rows × {rack.derived.columns} columns</small></div><div><span>Rack size · width × height × depth</span><strong>{dimensions(rack.size_mm)}</strong><small>One-piece bridge rack · no fasteners</small></div></div>
      <dl className="rack-dimensions"><div><dt>CAD bore</dt><dd>{number(rack.derived.bore_diameter_mm)} mm</dd></div><div><dt>Center spacing</dt><dd>{number(rack.derived.pitch_mm)} mm</dd></div><div><dt>Minimum rim land</dt><dd>{number(rack.derived.rim_land_min_assumed_mm)} mm <small>assumed tolerance</small></dd></div><div><dt>Tip clearance</dt><dd>{number(rack.derived.tip_clearance_mm)} mm <small>nominal</small></dd></div></dl>
      <p className="rack-note">{targetCount} preparation target{targetCount === 1 ? '' : 's'} use{targetCount === 1 ? 's' : ''} this rack; {Math.max(0, rack.derived.count - targetCount)} positions remain free. The model shows occupied body envelopes and closed-cap outlines at the canonical hole centers.</p>
      {rack.provenance.previous_size_mm && <p className="rack-change">Sample-rack envelope: {dimensions(rack.provenance.previous_size_mm)} before → {dimensions(rack.size_mm)} now. The source rack and imported Jubilee frame are unchanged.</p>}
      <p className="rack-note">Sized from your declared tube dimensions. Fit, deck retention and pipetting remain unverified. Review the rack-specific print and first-article checks in Build instructions.</p>
      <button className="rack-inspect" type="button" onClick={() => onSelect(rack.target_component_id)}>Show rack in model</button>
    </>}
    <details className="rack-details"><summary>{rack ? 'Tube inputs and manufacturing assumptions' : 'Recorded tube dimensions'}</summary>
      <p className="rack-note">Tube measurements: maximum body through the hole zone; minimum rim at the underside bearing surface; maximum closed cap including rim and closed hinge; underside of rim to tip. Open-cap motion is outside this envelope.</p>
      <dl>{Object.entries(spec).filter(([, value]) => value != null).map(([field, value]) => <div key={field}><dt>{labels[field as keyof RackSpec] ?? field}</dt><dd>{number(value as number)}{['count', 'columns'].includes(field) ? '' : ' mm'}{sources[field] && <small>Declared: “{sources[field].literal}” · revision {sources[field].recorded_at_revision}</small>}</dd></div>)}</dl>
      {rack && <><p className="rack-note">Calculation assumptions: ±{number(rack.assumptions.bore_diametral_tolerance_plus_minus_mm)} mm bore diameter deviation, minimum {number(rack.assumptions.minimum_rim_bearing_mm)} mm rim land. Measured printer and tube variation must be checked before use.</p><p className="rack-note">{rack.assumptions.process} {rack.assumptions.tube_envelope}</p><ul>{rack.assumptions.unverified.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul><p className="rack-note">Calculated minimum body clearance {number(rack.metrics.body_radial_clearance_min_assumed_mm)} mm radially; closed cap gap {number(rack.metrics.closed_cap_gap_mm)} mm; hole web {number(rack.metrics.hole_web_min_assumed_mm)} mm. These are geometry calculations.</p><ul>{rack.checks.map((check) => <li key={check.id}>{check.passed ? 'Calculated check' : 'Needs attention'}: {check.label}. {check.detail}</li>)}</ul></>}
      <p className="rack-note">Request changes in the design chat.</p>
    </details>
  </section>;
}
