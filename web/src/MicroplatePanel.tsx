import type { LabwarePlate } from './types';
import './labware-rack.css';

const number = (value: number) => new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(value);

export default function MicroplatePanel({ plate, onSelect }: { plate?: LabwarePlate | null; onSelect: (id: string) => void }) {
  if (!plate) return null;
  const { compatibility, derived, profile } = plate;
  const count = compatibility.occupied_wells.length;
  const volumeConflict = compatibility.status === 'volume_conflict';
  return <section className="labware-rack-panel microplate-panel" aria-labelledby="microplate-title">
    <div className="rack-heading"><div><h2 id="microplate-title">96-well plate</h2><p>{profile.display_name}</p></div><span className={`rack-state${volumeConflict ? ' attention' : ''}`}>{volumeConflict ? 'Revise recipe volume' : 'Selected labware profile'}</span></div>
    <div className="rack-results"><div><span>Plate capacity</span><strong>{derived.well_count} wells</strong><small>8 rows × 12 columns</small></div><div><span>Recipe occupancy</span><strong>{count} occupied · {derived.well_count - count} free</strong><small>The switch adds no preparation targets.</small></div></div>
    {compatibility.blocking_issues.length > 0 && <div className="rack-missing microplate-volume-error" role="alert"><strong>Recipe needs attention</strong><ul>{compatibility.blocking_issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul><p>Revise the final volume in chat, or ask to return to the previous tube rack. Your recipe has not been scaled.</p></div>}
    <dl className="rack-dimensions"><div><dt>Requested per target</dt><dd>{compatibility.requested_volume_ul == null ? 'Not specified' : `${number(compatibility.requested_volume_ul)} µL`}</dd></div><div><dt>Definition capacity</dt><dd>{number(derived.well_capacity_ul)} µL <small>per well, not a working-volume validation</small></dd></div><div><dt>Holder pocket</dt><dd>{derived.holder_pocket_mm.map(number).join(' × ')} mm</dd></div><div><dt>Holder + reference</dt><dd>{plate.size_mm.map(number).join(' × ')} mm</dd></div></dl>
    <p className="rack-note">Assigned wells: {compatibility.occupied_wells.join(', ') || 'none yet'}. Colored wells mark targets, not measured fill.</p>
    <p className="rack-note">Pinned Opentrons reference, not vendor CAD. Print the custom holder only. Fit, working volume and pipette access remain unverified.</p>
    <button className="rack-inspect" type="button" onClick={() => onSelect(plate.target_component_id)}>Show plate in model</button>
    <details className="rack-details"><summary>Profile source, orientation and export scope</summary>
      <p><a href={profile.source.source_url} target="_blank" rel="noopener noreferrer">Pinned Opentrons labware definition</a></p>
      <p className="rack-note">Revision {profile.source.revision} · checked {profile.source.checked_on} · {profile.source.license}. {profile.scope}</p>
      <p className="rack-note">A1 is at positive model Z; columns increase along X and rows A–H run toward negative Z. Current assignment: {compatibility.occupied_wells.join(', ') || 'no targets'}. Orientation must be confirmed on the actual plate.</p>
      <p className="rack-note">Print cad/plate-holder.stl after reviewing the holder fit and process assumptions. cad/plate-holder.step is editable. cad/plate-reference.step is schematic reference geometry and must not be fabricated as a laboratory plate.</p>
      <ul>{plate.checks.map((check) => <li key={check.id}>{check.passed ? 'Calculated check' : 'Needs attention'}: {check.label}. {check.detail}</li>)}</ul>
      <p className="rack-note">Request changes in the design chat. Your previous tube measurements are retained for a later return to the tube rack.</p>
    </details>
  </section>;
}
