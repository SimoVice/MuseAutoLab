import { createContext, useContext, useEffect, useId, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react';
import type { ImageCapability } from './ModelSelector';
import './step-illustration.css';

type Illustration = { project_id: string; project_revision: number; step_id: string; image_data_url: string; model: string; input_kind?: string; reference_scope?: string; sources?: { title: string; url: string }[] };
type Entry = { image: Illustration | null; busy: boolean; error: string | null };
const empty: Entry = { image: null, busy: false, error: null };
type Store = { images: Map<string, Entry>; pending: Map<string, AbortController>; listeners: Set<() => void> };
const StoreContext = createContext<Store | null>(null);
export function StepIllustrationProvider({ scope, children }: { scope: string; children: ReactNode }) {
  const store = useMemo<Store>(() => ({ images: new Map(), pending: new Map(), listeners: new Set() }), [scope]);
  useEffect(() => () => {
    for (const controller of store.pending.values()) controller.abort();
    store.pending.clear(); store.images.clear();
  }, [store]);
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>;
}
function update(store: Store, key: string, value: Partial<Entry>) {
  store.images.set(key, { ...(store.images.get(key) ?? empty), ...value });
  for (const listener of store.listeners) listener();
}
export default function StepIllustration({ projectId, revision, stepId, title, capability, disabled = false }: {
  projectId: string; revision: number; stepId: string; title: string; capability: ImageCapability | null; disabled?: boolean;
}) {
  const context = useContext(StoreContext);
  if (!context) throw new Error('Step illustrations require their workspace provider.');
  const store: Store = context;
  const { images, pending, listeners } = store;
  const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
  const key = `${projectId}:${revision}:${stepId}`;
  const { image, busy, error } = useSyncExternalStore(subscribe, () => images.get(key) ?? empty);
  const dialog = useRef<HTMLDialogElement>(null);
  const labelId = useId();
  async function generate() {
    if (pending.has(key) || disabled || !capability?.available) return;
    if (images.size >= 8 && !images.has(key)) {
      const oldest = [...images.keys()].find(candidate => !pending.has(candidate));
      if (oldest) images.delete(oldest);
      else return;
    }
    const controller = new AbortController(); pending.set(key, controller);
    update(store, key, { busy: true, error: null });
    const timeout = window.setTimeout(() => controller.abort(), 160000);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/instructions/illustration`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ project_revision: revision, step_id: stepId }),
      });
      const data = await response.json();
      if (pending.get(key) !== controller) return;
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'This step could not be illustrated. Try again.');
      if (data.project_id !== projectId || data.project_revision !== revision || data.step_id !== stepId) throw new Error('This image belongs to another step or revision. Try again for this step.');
      if (!data.image_data_url?.startsWith('data:image/png;base64,')) throw new Error('The step image is missing. Try again.');
      update(store, key, { image: data });
    } catch (reason) {
      if (pending.get(key) === controller) update(store, key, { error: reason instanceof Error && reason.name !== 'AbortError' ? reason.message : 'Image generation timed out. Try again when ready.' });
    } finally {
      window.clearTimeout(timeout);
      if (pending.get(key) === controller) { pending.delete(key); update(store, key, { busy: false }); }
    }
  }
  return (
    <div className="step-illustration" aria-label={`Illustration for ${title}`}>
      {!image && <>
        <button
          type="button"
          disabled={busy || disabled || !capability?.available}
          onClick={() => void generate()}
        >
          {busy ? 'Illustrating this step…' : error ? 'Try illustration again' : 'Illustrate this step'}
        </button>
        <small>
          {capability?.available
            ? 'Optional · Muse Image · uses your provider allowance'
            : capability?.unavailable_reason ?? 'Checking Muse Image availability…'}
        </small>
      </>}
      {busy && <p role="status">
        Generating an illustration for {title}…{' '}
        <button type="button" onClick={() => {
          pending.get(key)?.abort();
          pending.delete(key);
          update(store, key, { busy: false });
        }}>Cancel</button>
      </p>}
      {error && <p role="alert">{error}</p>}
      {image && <figure>
        <button
          className="step-image-preview"
          type="button"
          aria-label={`Enlarge illustration: ${title}`}
          onClick={() => dialog.current?.showModal()}
        >
          <img
            src={image.image_data_url}
            alt={`AI-generated assembly illustration: ${title}`}
            onError={() => update(store, key, {
              image: null,
              error: 'The generated image could not be displayed. Try again.',
            })}
          />
        </button>
        <figcaption>
          AI-generated {image.input_kind === 'instruction_checklist'
            ? 'instruction checklist' : 'component schematic'} · revision {revision}.
          {' '}Check against the written instructions; details may differ.
        </figcaption>
        <dialog
          ref={dialog}
          aria-labelledby={labelId}
          onClick={(event) => {
            if (event.target === event.currentTarget) dialog.current?.close();
          }}
        >
          <div className="step-image-dialog-heading">
            <h3 id={labelId}>{title}</h3>
            <button type="button" autoFocus onClick={() => dialog.current?.close()}>
              Close image
            </button>
          </div>
          <img
            src={image.image_data_url}
            alt={`Enlarged AI-generated assembly illustration: ${title}`}
          />
          <p>
            {image.reference_scope
              ?? 'Illustrative only. Follow the written instructions and source guides.'}
          </p>
          {image.sources?.filter(source => /^https?:\/\//.test(source.url)).map((source, index) => (
            <p key={index}>
              <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
            </p>
          ))}
          <a href={image.image_data_url} download={`assembly-${stepId}-r${revision}.png`}>
            Download image
          </a>
        </dialog>
      </figure>}
    </div>
  );
}
