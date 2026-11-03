import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import App from './App';
import PoweredByMeta from './PoweredByMeta';
import './hosted-workspace.css';

type Access = { enabled: boolean; authenticated: boolean; account?: string | null };

export default function HostedAccess() {
  const [access, setAccess] = useState<Access | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [expired, setExpired] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    fetch('/api/auth/status', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        // Local previews may still use an older API with a live in-memory project.
        if (window.location.protocol === 'http:' && response.status === 404 &&
            ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)) {
          setAccess({ enabled: false, authenticated: true });
          return;
        }
        if (!response.ok) throw new Error('The workspace is unavailable. Check your connection and try again.');
        const data = await response.json() as Access;
        if (typeof data.enabled !== 'boolean' || typeof data.authenticated !== 'boolean') throw new Error('The workspace returned an incomplete response. Try again.');
        setAccess(data);
      }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Cannot reach the workspace.'); });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (!access?.enabled || !access.authenticated) return;
    const original = window.fetch;
    const wrapped: typeof fetch = async (...args) => {
      const response = await original(...args);
      if (response.status === 401) {
        setExpired(true);
        setAccess({ enabled: true, authenticated: false });
      }
      return response;
    };
    window.fetch = wrapped;
    return () => { if (window.fetch === wrapped) window.fetch = original; };
  }, [access?.enabled, access?.authenticated]);

  async function login(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
      if (!response.ok) throw new Error(response.status === 429 ? 'Too many sign-in attempts. Wait a few minutes and try again.' : response.status === 401 ? 'The username or password is incorrect.' : 'Sign-in failed. Try again.');
      setPassword(''); setUsername(''); setExpired(false);
      const status = await fetch('/api/auth/status', { cache: 'no-store' });
      if (!status.ok) throw new Error('Sign-in could not be verified. Try again.');
      setAccess(await status.json() as Access);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Sign-in failed. Check your connection.'); }
    finally { setBusy(false); }
  }

  async function logout() {
    const response = await fetch('/api/auth/logout', { method: 'POST' });
    if (!response.ok) throw new Error('Sign-out failed. Check your connection and try again.');
    setAccess({ enabled: true, authenticated: false });
  }

  if (access && (!access.enabled || access.authenticated)) return <App key={access.account ?? 'local'} hosted={access.enabled} account={access.account ?? ''} onSignOut={logout} />;

  return <main className="access-page">
    <section className="access-story" aria-label="MuseAutoLab">
      <a className="brand" href="/"><span>Muse<span className="brand-accent">Auto</span>Lab</span></a>
      <div><h1>Your lab process.<br />A workspace to build it.</h1><p>Design custom laboratory automation, explore equipment and develop your next setup in one place.</p></div>
      <PoweredByMeta />
    </section>
    <section className="access-form-panel">
      {!access ? <div className="access-form"><h2>Opening your workspace</h2><p role="status">{error || 'Checking the connection…'}</p>{error && <button onClick={() => setAttempt(value => value + 1)}>Try again</button>}</div> :
        <form className="access-form" onSubmit={event => void login(event)}>
          <h2>Sign in</h2><p>{expired ? 'Your session ended. Sign in again to continue your workspace.' : 'Return to your projects or start something new.'}</p>
          <label htmlFor="login-username">Username</label><input id="login-username" name="username" autoComplete="username" required maxLength={200} value={username} onChange={event => setUsername(event.target.value)} disabled={busy} />
          <label htmlFor="login-password">Password</label><input id="login-password" name="password" type="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />
          {error && <p className="hosted-error" role="alert">{error}</p>}
          <button className="hosted-primary" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          <p className="access-help">Use the account provided by your workspace administrator.</p>
        </form>}
    </section>
  </main>;
}
