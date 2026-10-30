import { useEffect, useRef, useState } from 'react';
import type { VoiceCapability } from './ModelSelector';
import { startVoiceCapture } from './voiceCapture';
import type { VoiceCapture } from './voiceCapture';

type Phase = 'idle' | 'permission' | 'recording' | 'transcribing';
export default function VoiceDictation({ capability, disabled, onBusyChange, onTranscript }: {
  capability: VoiceCapability | null; disabled: boolean; onBusyChange: (busy: boolean) => void; onTranscript: (text: string) => boolean;
}) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recoveryTranscript, setRecoveryTranscript] = useState<string | null>(null);
  const operation = useRef(0);
  const capture = useRef<VoiceCapture | null>(null);
  const tracks = useRef<MediaStream | null>(null);
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const limit = Math.min(60, capability?.max_duration_seconds ?? 60);
  const supported = Boolean(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function' && typeof window.AudioContext === 'function' && window.isSecureContext);

  function release() {
    window.clearInterval(timer.current);
    capture.current?.cancel(); capture.current = null;
    tracks.current?.getTracks().forEach((track) => track.stop()); tracks.current = null;
    abort.current?.abort(); abort.current = null;
  }
  function cancel() {
    operation.current += 1; release(); setPhase('idle'); onBusyChange(false);
    setError(null); setNotice('Recording cancelled. Your draft is unchanged.');
  }
  useEffect(() => () => { operation.current += 1; release(); onBusyChange(false); }, [onBusyChange]);

  async function stop() {
    if (!capture.current) return;
    const current = operation.current;
    const recording = capture.current; capture.current = null;
    window.clearInterval(timer.current);
    setPhase('transcribing'); setNotice(null);
    try {
      const audio = await recording.finish();
      tracks.current = null;
      if (operation.current !== current) return;
      const controller = new AbortController(); abort.current = controller;
      const timeout = window.setTimeout(() => controller.abort(), 90000);
      let response: Response;
      try { response = await fetch('/api/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: audio, signal: controller.signal }); }
      finally { window.clearTimeout(timeout); }
      const data = await response.json();
      if (operation.current !== current) return;
      if (!response.ok) throw new Error(data.detail ?? 'Transcription failed. Record again or type your message.');
      if (typeof data.text !== 'string' || !data.text.trim()) throw new Error('No speech was found. Record again or type your message.');
      if (onTranscript(data.text.trim())) {
        setNotice('Transcript added to your draft. Review it, then send when ready.');
      } else {
        setRecoveryTranscript(data.text.trim());
        setNotice('The combined draft exceeds 4,000 characters. Your draft is kept. Copy or edit the transcript below before sending.');
      }
    } catch (reason) {
      if (operation.current !== current) return;
      setError(reason instanceof Error && reason.name !== 'AbortError' ? reason.message : 'Transcription timed out. Record again or type your message.');
    } finally {
      if (operation.current === current) { release(); setPhase('idle'); onBusyChange(false); }
    }
  }
  async function start() {
    if (disabled || !capability?.available || !supported || phase !== 'idle') return;
    const current = ++operation.current;
    setPhase('permission'); onBusyChange(true); setError(null); setNotice(null); setElapsed(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      if (operation.current !== current) { stream.getTracks().forEach((track) => track.stop()); return; }
      tracks.current = stream;
      const recording = await startVoiceCapture(stream);
      if (operation.current !== current) { recording.cancel(); return; }
      capture.current = recording; setPhase('recording');
      const started = performance.now();
      timer.current = window.setInterval(() => {
        const seconds = Math.floor((performance.now() - started) / 1000);
        setElapsed(Math.min(seconds, limit));
        if (seconds >= limit) void stop();
      }, 200);
    } catch (reason) {
      if (operation.current !== current) return;
      release(); setPhase('idle'); onBusyChange(false);
      const name = reason instanceof DOMException ? reason.name : '';
      setError(name === 'NotAllowedError' ? 'Microphone access is blocked. Allow it in your browser, or type your message.' : name === 'NotFoundError' ? 'No microphone was found. Connect one, or type your message.' : 'The microphone could not start. Check your device, or type your message.');
    }
  }
  const unavailable = !supported ? 'Voice needs a supported browser on localhost or HTTPS.' : capability?.unavailable_reason ?? 'Checking voice availability…';
  return <div className="voice-dictation">
    <div className="voice-actions">
      {phase === 'idle' ? <button type="button" className="voice-start" onClick={() => void start()} disabled={disabled || !supported || !capability?.available}
        title={capability?.available && supported ? 'Record up to 60 seconds; transcription is added to your draft.' : unavailable} aria-describedby="voice-help">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" /></svg>
        Muse Voice
      </button> : <>
        <span className="voice-phase" role="status">{phase === 'recording' ? `Recording ${elapsed}s / ${limit}s` : phase === 'permission' ? 'Allow microphone access…' : 'Transcribing with Muse Voice…'}</span>
        {phase === 'recording' && <button type="button" className="voice-stop" onClick={() => void stop()}>Stop and transcribe</button>}
        <button type="button" className="voice-cancel" onClick={cancel}>Cancel</button>
      </>}
    </div>
    <p id="voice-help" className="voice-help">{phase === 'idle' ? capability?.available && supported ? 'Dictate, review, then send. Audio goes to Meta for transcription.' : unavailable : 'Your typed draft is kept. Nothing is sent to the chat automatically.'}</p>
    {notice && <p className="voice-notice" role="status">{notice}</p>}
    {error && <p className="voice-error" role="alert">{error}</p>}
    {recoveryTranscript !== null && <div className="voice-recovery"><label htmlFor="recovery-transcript">Transcript to copy</label><textarea id="recovery-transcript" value={recoveryTranscript} onChange={(event) => setRecoveryTranscript(event.target.value)} rows={3} /><button type="button" onClick={() => setRecoveryTranscript(null)}>Dismiss transcript</button></div>}
  </div>;
}
