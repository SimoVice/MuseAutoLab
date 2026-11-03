import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { ProjectResponse } from './types';

export type SavedEntry = { id: string; title: string; revision: number; status: string; updated_at: string };
export type LibraryOpen = ProjectResponse & { title: string; conversation?: { role: 'user' | 'assistant'; content: string }[] };

type Props = {
  projectId: string | undefined; revision: number | undefined; title: string;
  disabled: boolean; onBusy: (busy: boolean) => void; onOpen: (data: LibraryOpen) => void;
  onSaved: (entry: SavedEntry) => void; onSignOut: () => Promise<void>; hasUnsaved: boolean;
};

async function libraryRequest(path: string, options?: RequestInit) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 401 ? 'Your session ended. Sign in again to continue.' : typeof data?.detail === 'string' ? data.detail : 'The request failed. Check your connection and try again.');
  return data;
}

export default function ProjectLibrary(props: Props) {
  const [view, setView] = useState<'library' | 'save' | 'signout' | null>(null);
  const [entries, setEntries] = useState<SavedEntry[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (view) { dialog.current?.showModal(); } else { dialog.current?.close(); trigger.current?.focus(); }
  }, [view]);
  function show(next: typeof view, button: HTMLButtonElement) { trigger.current = button; setError(''); setView(next); }
  async function browse(button: HTMLButtonElement) {
    show('library', button); setBusy(true);
    try {
      const result = await libraryRequest('/api/library', { cache: 'no-store' });
      if (!result.enabled) throw new Error('Saved projects are not configured for this workspace. You can still export a project file.');
      setEntries(result.projects);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Projects could not be loaded.'); }
    finally { setBusy(false); }
  }
  async function open(entry: SavedEntry) {
    if (busy) return;
    if (props.hasUnsaved && !window.confirm('Open this project? Unsaved changes in the current workspace will be replaced. Export a file or save your project first to keep them.')) return;
    setBusy(true); props.onBusy(true); setError('');
    try { const data = await libraryRequest(`/api/library/${encodeURIComponent(entry.id)}/open`, { method: 'POST' }); props.onOpen({ ...data, title: entry.title }); setView(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'The project could not be opened.'); }
    finally { setBusy(false); props.onBusy(false); }
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!props.projectId || busy || !name.trim()) return;
    setBusy(true); props.onBusy(true); setError('');
    try {
      const data = await libraryRequest(`/api/projects/${encodeURIComponent(props.projectId)}/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: name.trim(), revision: props.revision }) });
      props.onSaved(data.saved_project); setView(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The project could not be saved.'); }
    finally { setBusy(false); props.onBusy(false); }
  }
  async function signOut() {
    setBusy(true); props.onBusy(true); setError('');
    try { await props.onSignOut(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Sign-out failed.'); setBusy(false); props.onBusy(false); }
  }
  return <>
    <button type="button" className="new-project-button" disabled={props.disabled} onClick={event => void browse(event.currentTarget)}>Projects</button>
    <button type="button" className="new-project-button" disabled={props.disabled || !props.projectId} onClick={event => { setName(props.title); show('save', event.currentTarget); }}>{props.title ? 'Rename project' : 'Save project'}</button>
    <button type="button" className="new-project-button" disabled={props.disabled} onClick={event => show('signout', event.currentTarget)}>Sign out</button>
    <dialog className="project-library-dialog" ref={dialog} onCancel={event => { event.preventDefault(); if (!busy) setView(null); }}>
      <div className="library-dialog-heading"><h2>{view === 'save' ? props.title ? 'Rename project' : 'Save project' : view === 'signout' ? 'Sign out' : 'Your projects'}</h2><button type="button" aria-label="Close dialog" disabled={busy} onClick={() => setView(null)}>×</button></div>
      {error && <p className="hosted-error" role="alert">{error}</p>}
      {view === 'save' ? <form onSubmit={event => void save(event)}><p>Name this setup so you can find it again. Once saved, project changes are saved automatically. Text still in the chat box is a draft.</p><label htmlFor="project-name">Project name</label><input autoFocus id="project-name" required maxLength={120} value={name} onChange={event => setName(event.target.value)} disabled={busy} /><div className="library-dialog-actions"><button type="button" disabled={busy} onClick={() => setView(null)}>Cancel</button><button type="submit" className="hosted-primary" disabled={busy || !name.trim()}>{busy ? 'Saving…' : props.title ? 'Save name' : 'Save project'}</button></div></form> : view === 'signout' ? <><p>{props.hasUnsaved ? 'Your current project is unnamed or has a chat draft. Name and save the project, and send or copy your draft before signing out to keep them.' : 'Your saved projects will be here when you return.'}</p><div className="library-dialog-actions"><button disabled={busy} onClick={() => setView(null)}>Stay here</button><button className="hosted-primary" disabled={busy} onClick={() => void signOut()}>{busy ? 'Signing out…' : 'Sign out'}</button></div></> : <>
        <p>Open a saved setup to continue designing. Saved projects update automatically as you work.</p>
        {busy && <p role="status">Loading projects…</p>}
        {!busy && !error && entries.length === 0 && <div className="library-empty"><h3>Your first project starts here</h3><p>Describe a laboratory task in chat, then choose Save project to add it to this library.</p><button className="hosted-primary" onClick={() => setView(null)}>Continue to workspace</button></div>}
        <ul className="saved-project-list">{entries.map(entry => <li key={entry.id}><div><h3>{entry.title}</h3><p>Revision {entry.revision} <span aria-hidden="true">·</span> Saved {new Date(entry.updated_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p></div><button disabled={busy} onClick={() => void open(entry)}>Open<span className="sr-only"> {entry.title}</span></button></li>)}</ul>
        {error && <button disabled={busy} onClick={() => { if (trigger.current) void browse(trigger.current); }}>Try again</button>}
      </>}
    </dialog>
  </>;
}
