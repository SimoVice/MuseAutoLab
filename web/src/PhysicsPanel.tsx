import { useCallback, useEffect, useRef, useState } from 'react';
import type { PhysicsResult, PhysicsScenario, PhysicsView, Project, SimulationJob } from './types';

type Props = {
  project: Project;
  active: boolean;
  onView: (view: PhysicsView | null) => void;
  onActivate: () => void;
};

async function readError(response: Response): Promise<string> {
  const data: unknown = await response.json().catch(() => null);
  if (data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string') {
    return (data as { detail: string }).detail;
  }
  return `Request failed (${response.status}). Please try again.`;
}

function formatNum(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en', { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

export default function PhysicsPanel({ project, active, onView, onActivate }: Props) {
  const [scenario, setScenario] = useState<PhysicsScenario>('nominal');
  const [job, setJob] = useState<SimulationJob | null>(null);
  const [result, setResult] = useState<PhysicsResult | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeS, setTimeS] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
  const pollRef = useRef<number | null>(null);
  const epochRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);
  const projectKey = `${project.id}:${project.revision}:${project.status}`;

  const clearPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const stopPlayback = useCallback(() => {
    if (rafRef.current !== null) {
      window.clearInterval(rafRef.current);
      rafRef.current = null;
    }
    setPlaying(false);
  }, []);

  // Revision changes clear results/replay.
  useEffect(() => {
    epochRef.current += 1;
    requestRef.current?.abort();
    clearPoll();
    stopPlayback();
    setJob(null);
    setResult(null);
    setError(null);
    setStarting(false);
    setTimeS(0);
    onView(null);
    return () => {
      epochRef.current += 1;
      requestRef.current?.abort();
      clearPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey, clearPoll, stopPlayback]);

  useEffect(() => {
    if (!active) stopPlayback();
  }, [active, stopPlayback]);

  // A separate mode prevents an older replay from taking over the schematic view.
  useEffect(() => {
    if (result && active) onView({ result, time_s: timeS });
    else onView(null);
  }, [result, timeS, active, onView]);

  useEffect(() => () => {
    if (rafRef.current !== null) window.clearInterval(rafRef.current);
  }, []);



  // Playback at 20Hz using interval; stops at final without returning home.
  useEffect(() => {
    if (!playing || !result || result.frames.length === 0) return;
    const duration = result.duration_s > 0 ? result.duration_s : result.frames[result.frames.length - 1].time_s;
    lastTickRef.current = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const dt = Math.min(0.25, (now - lastTickRef.current) / 1000);
      lastTickRef.current = now;
      setTimeS((prev) => {
        const advance = dt * speed;
        const nextVal = prev + advance;
        if (nextVal >= duration) {
          window.clearInterval(id);
          setPlaying(false);
          return duration;
        }
        return nextVal;
      });
    }, 50);
    rafRef.current = id;
    return () => window.clearInterval(id);
  }, [playing, result, speed]);

  const fetchJob = useCallback(
    async (jobId: string, signal: AbortSignal): Promise<SimulationJob> => {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/simulations/${encodeURIComponent(jobId)}`, { signal });
      if (!response.ok) throw new Error(await readError(response));
      return (await response.json()) as SimulationJob;
    },
    [project.id],
  );

  const fetchResult = useCallback(
    async (jobId: string, signal: AbortSignal): Promise<PhysicsResult> => {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/simulations/${encodeURIComponent(jobId)}/result`, { signal });
      if (!response.ok) throw new Error(await readError(response));
      return (await response.json()) as PhysicsResult;
    },
    [project.id],
  );

  const pollUntilDone = useCallback(
    (jobId: string, epoch: number, signal: AbortSignal) => {
      clearPoll();
      const poll = async () => {
        if (epochRef.current !== epoch || signal.aborted) return;
        try {
          const updated = await fetchJob(jobId, signal);
          if (epochRef.current !== epoch || signal.aborted) return;
          setJob(updated);
          if (updated.status === 'ready') {
            try {
              const res = await fetchResult(jobId, signal);
              if (epochRef.current !== epoch || signal.aborted) return;
              setResult(res);
              setTimeS(0);
              setPlaying(false);
            } catch (reason: unknown) {
              if (epochRef.current !== epoch || signal.aborted) return;
              setError(reason instanceof Error ? reason.message : 'Could not load simulation result.');
            }
            return;
          }
          if (updated.status === 'failed') return;
          pollRef.current = window.setTimeout(() => void poll(), 1000);
        } catch (reason: unknown) {
          if (epochRef.current !== epoch || signal.aborted) return;
          if (signal.aborted) return;
          setError(reason instanceof Error ? reason.message : 'Could not check simulation. Retry to reconnect.');
        }
      };
      pollRef.current = window.setTimeout(() => void poll(), 1000);
    },
    [clearPoll, fetchJob, fetchResult],
  );

  async function start() {
    clearPoll();
    stopPlayback();
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const epoch = ++epochRef.current;
    setStarting(true);
    setError(null);
    setResult(null);
    setTimeS(0);
    onView(null);
    onActivate();
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/simulations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readError(response));
      const created = (await response.json()) as SimulationJob;
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setJob(created);
      if (created.status === 'ready') {
        const res = await fetchResult(created.id, controller.signal);
        if (epochRef.current !== epoch || controller.signal.aborted) return;
        setResult(res);
        setTimeS(0);
      } else if (created.status !== 'failed') {
        pollUntilDone(created.id, epoch, controller.signal);
      }
    } catch (reason) {
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : 'Could not start simulation.');
    } finally {
      if (epochRef.current === epoch && !controller.signal.aborted) setStarting(false);
    }
  }

  function retry() {
    setError(null);
    void start();
  }

  const pending = job !== null && (job.status === 'queued' || job.status === 'running');
  const duration = result && result.frames.length > 0
    ? (result.duration_s > 0 ? result.duration_s : result.frames[result.frames.length - 1].time_s)
    : 0;

  function handlePlay() {
    if (!result || result.frames.length === 0) return;
    onActivate();
    if (timeS >= duration && duration > 0) setTimeS(0);
    lastTickRef.current = performance.now();
    setPlaying(true);
  }
  function handlePause() { setPlaying(false); }
  function handleReset() { onActivate(); setPlaying(false); setTimeS(0); }
  function handleSeek(value: number) {
    onActivate();
    setPlaying(false);
    setTimeS(Math.max(0, Math.min(duration, value)));
  }

  const peakForce = result ? Math.max(...result.metrics.peak_actuator_force_n.filter((v) => Number.isFinite(v)), 0) : 0;

  return (
    <section className="physics-card" aria-labelledby="physics-title">
      <div className="physics-heading">
        <div>
          <h2 id="physics-title">Physical simulation</h2>
          <p>MuJoCo forward-dynamics replay of the pipette head. Planned aspirate/dispense events are logical holds, not simulated liquid volume.</p>
        </div>
        {result && <span className={`physics-status physics-status-${result.status}`}>{result.status}</span>}
      </div>

      {project.inspection_extension && <p className="cooling-note">Workstation motion only. The inspection arm and camera are parked and excluded from MuJoCo dynamics and collision checks.</p>}
      <div className="physics-row">
        <label className="physics-label" htmlFor="physics-scenario">Test case</label>
        <select
          id="physics-scenario"
          className="physics-select"
          value={scenario}
          onChange={(event) => {
            stopPlayback();
            setScenario(event.target.value as PhysicsScenario);
            setJob(null);
            setResult(null);
            setError(null);
            setTimeS(0);
            onView(null);
          }}
          disabled={starting || pending}
        >
          <option value="nominal">Normal run</option>
          <option value="blocked_path">Blocked-path test</option>
        </select>
        <button type="button" className="physics-button" onClick={() => void start()} disabled={starting || pending}>
          {starting || pending ? 'Running…' : 'Run physics'}
        </button>
      </div>

      {job && pending && (
        <p className="physics-progress" role="status">
          <progress aria-label="Physics integration progress" value={job.completed_steps} max={Math.max(job.total_steps, 1)} />
          {job.stage || 'Running'} — {job.completed_steps}/{job.total_steps} steps.
        </p>
      )}

      {error && (
        <div className="physics-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={retry}>Retry</button>
        </div>
      )}

      {job && job.status === 'failed' && (
        <div className="physics-error" role="alert">
          <span>{job.error || 'Simulation failed.'}</span>
          <button type="button" onClick={retry}>Retry</button>
        </div>
      )}

      {result && (
        <>
          {job && <div className="physics-downloads">
            <a href={`/api/projects/${encodeURIComponent(project.id)}/simulations/${encodeURIComponent(job.id)}/files/simulation/result.json`} download>Download physics report</a>
            <a href={`/api/projects/${encodeURIComponent(project.id)}/simulations/${encodeURIComponent(job.id)}/files/simulation/model.xml`} download>Download MuJoCo model</a>
          </div>}
          <dl className="physics-metrics">
            <div><dt>Engine</dt><dd>{result.engine} {result.engine_version}</dd></div>
            <div><dt>Result</dt><dd>{result.status}</dd></div>
            <div><dt>Waypoints</dt><dd>{result.metrics.completed_waypoints}/{result.metrics.total_waypoints}</dd></div>
            <div><dt>Max tracking</dt><dd>{formatNum(result.metrics.max_tracking_error_mm)} mm</dd></div>
            <div><dt>Peak contact</dt><dd>{formatNum(result.metrics.max_contact_force_n)} N</dd></div>
            <div><dt>Peak actuator</dt><dd>{formatNum(peakForce)} N</dd></div>
            <div><dt>Duration</dt><dd>{formatNum(result.duration_s)} s</dd></div>
          </dl>

          <div className="physics-playback">
            <div className="physics-playback-controls" role="group" aria-label="Physics replay controls">
              <button type="button" className="preview-button" onClick={handlePlay} disabled={playing || duration <= 0 || result.frames.length < 2}>Play</button>
              <button type="button" className="preview-button" onClick={handlePause} disabled={!playing}>Pause</button>
              <button type="button" className="preview-button" onClick={handleReset}>Reset</button>
              <div className="physics-speed" role="group" aria-label="Replay speed">
                {([1, 2, 4] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={speed === s ? 'preview-button physics-speed-active' : 'preview-button'}
                    aria-pressed={speed === s}
                    onClick={() => setSpeed(s)}
                  >
                    {s}x
                  </button>
                ))}
              </div>
            </div>
            <label className="physics-seek-label" htmlFor="physics-seek">
              Replay time {formatNum(timeS)} s of {formatNum(duration)} s (replay of calculated MuJoCo states)
            </label>
            <input
              id="physics-seek"
              className="physics-seek"
              type="range"
              min={0}
              max={duration}
              step={0.05}
              value={Math.min(timeS, duration)}
              onChange={(event) => handleSeek(Number(event.target.value))}
              disabled={duration <= 0}
            />
          </div>

          <p className="physics-note">
            Replay shows recorded engine states; positions between 20 Hz samples are linearly interpolated for display.
            {result.obstacles.length > 0 ? ' Diagnostic obstacle shown in orange.' : ''}
            {' '}Ideal servo control and contact envelopes are modeled; liquid, material deformation and cooling are not.
          </p>
          {result.status === 'blocked' && <p className="physics-note">Blocked: unexpected contact above threshold stopped the run; later actions were not completed.</p>}
          <details className="physics-assumptions"><summary>Model assumptions and checks</summary>
            <ul>{result.checks.map(check => <li key={check.id}>{check.label}: {check.passed ? 'passed' : 'not passed'}</li>)}</ul>
            <ul>{result.assumptions.map((line, index) => <li key={index}>{line}</li>)}</ul>
          </details>
        </>
      )}
      {!result && !job && <p className="physics-note">Runs the confirmed plan through MuJoCo and replays measured states in the viewer.</p>}
    </section>
  );
}
