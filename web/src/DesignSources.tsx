import type { DesignReference, Project } from './types';

function Reference({ source }: { source: DesignReference }) {
  const open = source.kind === 'open_hardware' || source.kind === 'open_source';
  return <article className="design-reference">
    <div className="reference-title"><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title} ↗</a><span>{open ? 'Open-source reference' : 'Manufacturer specification'}</span></div>
    <p>{source.use}</p>
    <details><summary>Evidence and scope</summary>
      <p>{source.publisher}. Reviewed {source.checked_on}.</p>
      <p>{source.facts.join('. ')}.</p>
      <p>{source.revision}</p>
      <p>{source.license}{source.license_url && <> · <a href={source.license_url} target="_blank" rel="noopener noreferrer">License source</a></>}</p>
      <p>{source.limits}</p>
    </details>
  </article>;
}

export default function DesignSources({ project, showBindings, onHighlight }: {
  project: Project; showBindings: boolean; onHighlight: (id: string) => void;
}) {
  const basis = project.design_basis;
  if (!basis) return null;
  const bound = showBindings ? basis.bindings.filter((item) => item.reference_id) : [];
  const custom = showBindings ? basis.bindings.filter((item) => !item.reference_id) : [];
  const ids = new Set(bound.map((item) => item.reference_id));
  return <section className="design-sources" aria-labelledby="design-sources-title">
    <div className="design-agent-heading"><div>
      <h2 id="design-sources-title">Design foundations</h2>
      <p>Reviewed open projects and official specifications. Each source has a defined role.</p>
    </div><span className="planning-status">Reviewed {basis.checked_on}</span></div>
    {showBindings && <div className="source-bindings">
      {bound.map((item) => <div key={`${item.component_id}:${item.primitive_id ?? ''}`}>
        <button type="button" onClick={() => onHighlight(item.component_id)}>{project.design.components.find((part) => part.id === item.component_id)?.label ?? item.component_id}</button>
        <span>{item.basis === 'imported_open_hardware_cad' ? 'Original open hardware CAD' : 'Manufacturer dimensions'}</span><p>{item.detail}</p>
      </div>)}
      <p className="source-scope">{project.design.foundation
        ? 'The platform is original Jubilee CAD. The insert, pipette adapter, labware fixtures and inspection arm are custom concepts; interfaces and physical operation remain unverified.'
        : 'The frame, labware fixtures, pipette mechanism and inspection arm remain custom concepts. No source platform is imported in this revision.'}</p>
    </div>}
    <details className="source-library"><summary>Browse references and technical scope</summary>
      {basis.references.filter((source) => ids.has(source.id)).map((source) => <Reference key={source.id} source={source} />)}
      {basis.references.filter((source) => !ids.has(source.id)).map((source) => <Reference key={source.id} source={source} />)}
      {custom.length > 0 && <div className="source-custom"><h3>Custom geometry still to engineer</h3><ul>{custom.map((item) => <li key={item.component_id}>{project.design.components.find((part) => part.id === item.component_id)?.label ?? item.component_id}</li>)}</ul></div>}
    </details>
    <a className="brief-download" href={`/api/projects/${project.id}/sources?revision=${project.revision}`} download="design-sources.json">Download design sources</a>
  </section>;
}
