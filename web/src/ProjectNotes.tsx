import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { Project } from './types';
import './project-notes.css';

export default function ProjectNotes({ project, busy, onSave }: {
  project: Project; busy: boolean; onSave: (id: string, notes: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState('');
  const [previous, setPrevious] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);

  function open() {
    setDraft(project.project_notes ?? '');
    setPrevious(project.project_notes ?? '');
    setError('');
    setConflict(false);
    dialog.current?.showModal();
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/notes`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ previous, notes: draft }),
      });
      const data = await response.json();
      if (response.status === 409 && typeof data.detail?.notes === 'string') {
        setPrevious(data.detail.notes);
        setConflict(true);
        onSave(project.id, data.detail.notes);
        return;
      }
      if (!response.ok) throw new Error('Could not save these notes. Try again.');
      onSave(project.id, data.notes);
      dialog.current?.close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save these notes.');
    } finally {
      setSaving(false);
    }
  }

  return <>
    <button type="button" className="project-notes-trigger" onClick={open} disabled={busy}>Project notes</button>
    <dialog ref={dialog} className="project-library-dialog project-notes-dialog" aria-labelledby="notes-title"
      onCancel={event => { if (saving) event.preventDefault(); }}>
      <form onSubmit={save}>
        <h2 id="notes-title">Project notes</h2>
        <p>Muse reads these notes alongside your design and recent conversation. Keep equipment you own, working preferences or constraints here.</p>
        <label htmlFor="project-notes-field">What should Muse remember for this project?</label>
        <textarea id="project-notes-field" autoFocus rows={5} maxLength={2400} value={draft}
          placeholder="We share a printer with the microscopy room. Prefer holders we can print in one piece."
          onChange={event => setDraft(event.target.value)} disabled={saving} />
        {conflict && <div role="alert">
          <p>These notes changed in another session. Review the saved version before saving your edits.</p>
          <blockquote>{previous || 'The saved note is empty.'}</blockquote>
          <button type="button" onClick={() => { setDraft(previous); setConflict(false); }}>Use saved version</button>
        </div>}
        {error && <p role="alert">{error}</p>}
        <div className="library-dialog-actions">
          <button type="button" disabled={saving} onClick={() => dialog.current?.close()}>Cancel</button>
          <button type="submit" className="hosted-primary" disabled={saving}>{saving ? 'Saving…' : 'Save notes'}</button>
        </div>
      </form>
    </dialog>
  </>;
}
