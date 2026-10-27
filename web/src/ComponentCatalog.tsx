import type { Sourcing, SourcingOption } from './types';

type CatalogProps = {
  sourcing: Sourcing | null | undefined;
  busy: boolean;
  onChoose: (groupId: string, optionId: string) => void;
  onHighlight: (componentId: string) => void;
};

function formatUnitPrice(option: SourcingOption, currency: string): string {
  if (option.unit_price == null || option.price_kind === 'unpriced') return 'Unpriced';
  const formatted = new Intl.NumberFormat('en', { style: 'currency', currency }).format(option.unit_price);
  return option.price_kind === 'starting_at' ? `from ${formatted}` : formatted;
}

export default function ComponentCatalog({ sourcing, busy, onChoose, onHighlight }: CatalogProps) {
  if (!sourcing) {
    return (
      <section className="catalog-block" aria-labelledby="catalog-title">
        <div className="catalog-heading">
          <div>
            <h2 id="catalog-title">Component catalogue</h2>
            <p>Source-backed options for this concept.</p>
          </div>
        </div>
        <p className="catalog-empty">The component catalogue is not available yet. It will appear here once the server provides it.</p>
      </section>
    );
  }

  return (
    <section className="catalog-block" aria-labelledby="catalog-title">
      <div className="catalog-heading">
        <div>
          <h2 id="catalog-title">Component catalogue</h2>
          <p>Source-backed options for this concept.</p>
        </div>
        <span className="catalog-checked">Checked {sourcing.checked_on}</span>
      </div>
      <p className="catalog-note">
        Curated snapshot, not a live feed. Prices in {sourcing.currency}; unpriced groups need specification.
      </p>
      <div className="catalog-groups">
        {sourcing.groups.map((group) => {
          const selected = group.options.find((option) => option.id === group.selected_id) ?? group.options[0];
          return (
            <section key={group.id} className="catalog-group" aria-label={group.label}>
              <div className="catalog-group-top">
                <div>
                  <h3>{group.label}</h3>
                  <p className="catalog-qty">Qty {group.quantity}</p>
                </div>
                <div className="catalog-price">
                  <span>{selected ? formatUnitPrice(selected, sourcing.currency) : 'Unpriced'}{selected?.unit_price != null ? ' / unit' : ''}</span>
                  {selected?.unit_price != null && group.quantity > 1 && <small style={{ display: 'block', marginTop: 4 }}>{new Intl.NumberFormat('en', { style: 'currency', currency: sourcing.currency }).format(selected.unit_price * group.quantity)} for {group.quantity}</small>}
                </div>
              </div>
              <label className="catalog-label" htmlFor={`choose-${group.id}`}>
                Choose {group.label}
              </label>
              <select
                id={`choose-${group.id}`}
                className="catalog-select"
                value={group.selected_id}
                disabled={busy}
                onFocus={() => {
                  const target = group.component_ids[0];
                  if (target) onHighlight(target);
                }}
                onChange={(event) => {
                  const next = event.target.value;
                  const target = group.component_ids[0];
                  if (target) onHighlight(target);
                  onChoose(group.id, next);
                }}
              >
                {group.options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label} — {formatUnitPrice(option, sourcing.currency)}
                  </option>
                ))}
              </select>
              {selected && (
                <div className="catalog-selected">
                  <div className="catalog-meta">
                    <span>{selected.supplier}</span>
                    <span>Checked {selected.checked_on}</span>
                    <span>{selected.availability}</span>
                  </div>
                  {selected.source_url ? (
                    <a className="catalog-link" href={selected.source_url} target="_blank" rel="noopener noreferrer">
                      Supplier / price source
                    </a>
                  ) : (
                    <span className="catalog-nolink">Supplier to be specified</span>
                  )}
                  <details className="catalog-details">
                    <summary>Details and integration notes</summary>
                    <div className="catalog-details-body">
                      {selected.sku && (
                        <p>
                          <strong>SKU:</strong> {selected.sku}
                        </p>
                      )}
                      {selected.pros.length > 0 && (
                        <div>
                          <p className="catalog-subhead">Pros</p>
                          <ul>
                            {selected.pros.map((pro, index) => (
                              <li key={index}>{pro}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {selected.cons.length > 0 && (
                        <div>
                          <p className="catalog-subhead">Cons</p>
                          <ul>
                            {selected.cons.map((con, index) => (
                              <li key={index}>{con}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {selected.compatibility_note && <p className="catalog-compat">{selected.compatibility_note}</p>}
                      {group.options.length > 1 && (
                        <div>
                          <p className="catalog-subhead">Other options in this group</p>
                          <ul className="catalog-others">
                            {group.options
                              .filter((option) => option.id !== selected.id)
                              .map((option) => (
                                <li key={option.id}>
                                  <strong>{option.label}</strong> — {formatUnitPrice(option, sourcing.currency)}
                                  {option.compatibility_note ? ` · ${option.compatibility_note}` : ''}
                                </li>
                              ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </details>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}
