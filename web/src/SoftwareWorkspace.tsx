import ConceptWorkspace from './ConceptWorkspace';
import BenchStationPanel from './BenchStationPanel';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Scene from './Scene';
import OperatingPreview from './OperatingPreview';
import { compileMotionPlan } from './motionPlan';
import type { MotionMode } from './motionPlan';
import type { Project } from './types';
import PoweredByMeta from './PoweredByMeta';
import AssistantMessage from './AssistantMessage';
import './software-workspace.css';

type Props = {
  project: Project;
  onProject: (project: Project) => void;
  onConversation: (message: string, reply: string) => void;
};
const number = (value: number) => value.toLocaleString('en-US', { maximumFractionDigits: 3 });

export default function SoftwareWorkspace({ project, onProject, onConversation }: Props) {
  const [stock, setStock] = useState(project.summary.stock_concentration ?? '');
  const [targets, setTargets] = useState(project.summary.target_concentrations ?? '');
  const [volume, setVolume] = useState(project.summary.final_volume ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(false);
  const [codeError, setCodeError] = useState('');
  const [tab, setTab] = useState<'transfers' | 'code'>('code');
  const [chat, setChat] = useState('');
  const [mode, setMode] = useState<MotionMode>('preparation');
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [speed, setSpeed] = useState(1);
  const clock = useRef(0);
  const requestEpoch = useRef(0);
  const plan = useMemo(() => compileMotionPlan(project, mode), [project, mode]);
  const key = `${project.id}:${project.revision}:${plan.mode}:${plan.scope}`;
  const dirty = stock !== (project.summary.stock_concentration ?? '')
    || targets !== (project.summary.target_concentrations ?? '')
    || volume !== (project.summary.final_volume ?? '');
  const ready = project.plan?.status === 'ready';
  const liquid = project.workflow.kind === 'liquid_preparation';
  const base = `/api/projects/${encodeURIComponent(project.id)}`;
  const download = `${base}/instructions/download?revision=${project.revision}`;
  const platform = project.design.platform?.label
    ?? (project.design.foundation ? 'Jubilee' : 'Custom workstation');
  useEffect(() => {
    setStock(project.summary.stock_concentration ?? '');
    setTargets(project.summary.target_concentrations ?? '');
    setVolume(project.summary.final_volume ?? '');
    setPlaying(false);
    setTime(0);
    clock.current = 0;
  }, [
    key,
    project.summary.stock_concentration,
    project.summary.target_concentrations,
    project.summary.final_volume,
  ]);

  useEffect(() => {
    requestEpoch.current += 1;
    return () => {
      requestEpoch.current += 1;
    };
  }, [project.id]);

  useEffect(() => {
    if (!ready) {
      setCode('');
      return;
    }
    const controller = new AbortController();
    setCodeLoading(true);
    setCodeError('');
    setCode('');
    fetch(`${download}&format=program`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) {
          throw new Error(
            'Cannot load the current protocol. Return to the transfer view and try again.',
          );
        }
        return response.text();
      })
      .then(data => {
        if (!controller.signal.aborted) setCode(data);
      })
      .catch(reason => {
        if (!controller.signal.aborted) setCodeError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setCodeLoading(false);
      });
    return () => controller.abort();
  }, [download, ready]);

  useEffect(() => {
    if (!playing || plan.status !== 'ready') return;
    let frame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      clock.current = Math.min(
        plan.duration_s,
        clock.current + Math.min((now - previous) / 1000, .1) * speed,
      );
      previous = now;
      setTime(clock.current);
      if (clock.current >= plan.duration_s) {
        setPlaying(false);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, plan, speed]);

  useEffect(() => {
    const pause = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener('visibilitychange', pause);
    return () => document.removeEventListener('visibilitychange', pause);
  }, []);

  async function update(path: string, body: object) {
    const epoch = requestEpoch.current;
    setBusy(true);
    setPlaying(false);
    setError(null);
    setNotice('');
    try {
      const response = await fetch(`${base}/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_revision: project.revision, ...body }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : 'The recipe could not be updated. Check the values and try again.',
        );
      }
      if (epoch !== requestEpoch.current) return;
      onProject(data.project);
      setNotice(data.assistant_message ?? 'Protocol updated for this project revision.');
      if (path === 'messages') {
        onConversation(
          String((body as { message?: string }).message ?? ''),
          data.assistant_message ?? 'Program updated.',
        );
        setChat('');
      }
    } catch (reason) {
      if (epoch === requestEpoch.current) {
        setError(
          reason instanceof Error ? reason.message : 'Cannot update the protocol. Try again.',
        );
      }
    } finally {
      if (epoch === requestEpoch.current) setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void update('program-recipe', {
      stock_concentration: stock,
      target_concentrations: targets,
      final_volume: volume,
    });
  }

  function reset() {
    setPlaying(false);
    clock.current = 0;
    setTime(0);
  }

  return (
    <main className="software-workspace" aria-labelledby="software-title">
      <div className="software-heading">
        <div>
          <h1 id="software-title">Software & protocols</h1>
          <p>
            {liquid
              ? 'Write a recipe for your workstation and see how it runs in the 3D preview.'
              : 'Review the operating sequence and software for your workstation.'}
          </p>
        </div>
      </div>

      <div className="software-machine">
        <div>
          <span>Selected platform</span>
          <strong>{platform}</strong>
        </div>
        <div>
          <span>Controller / software</span>
          <strong>
            {project.design.platform?.id === 'opentrons-ot2'
              ? 'Opentrons Protocol Designer / Python API'
              : project.design.foundation
                ? 'Science Jubilee / Duet integration'
                : project.concept_design
                  ? project.concept_design.software.controller
                  : project.bench_station
                    ? 'Local Python assisted runner'
                    : 'Integration to be specified'}
          </strong>
        </div>
        <div>
          <span>Project binding</span>
          <strong>Revision {project.revision} · approved hardware</strong>
        </div>
      </div>

      <div className="software-grid">
        <section className="software-editor" aria-labelledby="recipe-title">
          <h2 id="recipe-title">{liquid ? 'Preparation recipe' : 'Operating program'}</h2>
          {liquid ? (
            <form onSubmit={submit}>
              <p>
                Include units in every quantity. Targets use the same concentration unit as the stock.
              </p>
              <label htmlFor="recipe-stock">
                Stock concentration
                <input
                  id="recipe-stock"
                  required
                  value={stock}
                  onChange={e => {
                    setStock(e.target.value);
                    setPlaying(false);
                  }}
                  placeholder="e.g. 100 mM"
                  disabled={busy}
                />
              </label>
              <div className="software-field">
                <label htmlFor="recipe-targets">Target concentrations</label>
                <textarea
                  id="recipe-targets"
                  required
                  rows={3}
                  value={targets}
                  onChange={e => {
                    setTargets(e.target.value);
                    setPlaying(false);
                  }}
                  placeholder="e.g. 10 mM, 25 mM, 50 mM"
                  disabled={busy}
                />
              </div>
              <label htmlFor="recipe-volume">
                Final volume per destination
                <input
                  id="recipe-volume"
                  required
                  value={volume}
                  onChange={e => {
                    setVolume(e.target.value);
                    setPlaying(false);
                  }}
                  placeholder="e.g. 200 µL"
                  disabled={busy}
                />
              </label>
              <button
                className="software-primary"
                type="submit"
                disabled={busy || !stock.trim() || !targets.trim() || !volume.trim()}
              >
                {busy ? 'Updating protocol…' : ready ? 'Update protocol' : 'Create protocol'}
              </button>
              {dirty && (
                <p className="software-draft" role="status">
                  Unapplied changes. Update the protocol to refresh the preview and downloads.
                </p>
              )}
            </form>
          ) : (
            <p>
              Describe the operation, inputs, sequence and required outputs below.
              Programming support depends on the selected equipment.
            </p>
          )}

          <form
            className="software-chat"
            onSubmit={e => {
              e.preventDefault();
              if (chat.trim()) void update('messages', { message: chat });
            }}
          >
            <h3>Describe a program change</h3>
            <div className="software-field">
              <label htmlFor="software-chat">Ask the assistant</label>
              <textarea
                id="software-chat"
                rows={3}
                value={chat}
                onChange={e => setChat(e.target.value)}
                maxLength={4000}
                placeholder="Describe the next operation or change to this recipe"
                disabled={busy}
              />
            </div>
            <button type="submit" disabled={busy || !chat.trim()}>
              Apply request
            </button>
          </form>
          {error && <p className="software-error" role="alert">{error}</p>}
          {notice && <div className="software-notice" role="status"><AssistantMessage text={notice} /></div>}
        </section>

        {liquid && (
          <section className="software-output" aria-labelledby="protocol-title">
            <div className="software-output-heading">
              <h2 id="protocol-title">Protocol preview</h2>
              <span>
                {ready
                  ? `${project.plan?.steps.length} ${project.plan?.steps.length === 1 ? 'destination' : 'destinations'}`
                  : 'Recipe needed'}
              </span>
            </div>
            <div className="software-tabs" role="group" aria-label="Protocol view">
              <button
                type="button"
                aria-pressed={tab === 'transfers'}
                onClick={() => setTab('transfers')}
              >
                Operations & volumes
              </button>
              <button
                type="button"
                aria-pressed={tab === 'code'}
                onClick={() => setTab('code')}
              >
                Python program
              </button>
            </div>

            {!ready ? (
              <div className="software-empty">
                <h3>Create your first recipe</h3>
                <p>
                  The generated transfer volumes, operation sequence and downloadable protocol
                  will appear here.
                </p>
              </div>
            ) : tab === 'transfers' ? (
              <>
                <div className="software-table-scroll">
                  <table>
                    <caption>Current saved recipe · revision {project.revision}</caption>
                    <thead>
                      <tr>
                        <th>Target</th>
                        <th>Stock (µL)</th>
                        <th>Diluent (µL)</th>
                        <th>Total (µL)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {project.plan?.steps.map(step => (
                        <tr key={step.id}>
                          <th scope="row">{step.target}</th>
                          <td>{number(step.stock_volume_ul)}</td>
                          <td>{number(step.diluent_volume_ul)}</td>
                          <td>{number(step.total_volume_ul)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ol className="software-operations">
                  <li>
                    Load stock, diluent, tips and destination labware at their assigned locations.
                  </li>
                  <li>For each destination, transfer its calculated stock and diluent volumes.</li>
                  <li>Discard used tips and review the prepared destinations.</li>
                </ol>
                <p className="software-scope">
                  Logical transfer schedule. Pipette configuration, calibration and robot
                  integration require review.
                </p>
              </>
            ) : (
              <div className="software-code">
                {codeLoading ? (
                  <p role="status">Loading current protocol…</p>
                ) : codeError ? (
                  <p role="alert">{codeError}</p>
                ) : (
                  <pre tabIndex={0} aria-label="Generated Python program">
                    <code>{code}</code>
                  </pre>
                )}
              </div>
            )}

            {ready && (
              <div className="software-downloads">
                <a
                  className="software-program-download"
                  href={`${download}&format=program`}
                  download="program.py"
                >
                  Download Python program
                </a>
                <a href={`${download}&format=protocol`} download>Protocol data (JSON)</a>
                <p>
                  Run locally: <code>python program.py</code>. Prints the calculated transfer
                  sequence without connecting to hardware.
                </p>
              </div>
            )}
          </section>
        )}

        {liquid ? (
          <section className="software-preview" aria-label="Program operating preview">
            <div className="software-scene">
              <Scene
                project={project}
                selectedId={null}
                onSelect={() => {}}
                inspectionTime={mode === 'inspection' ? time : 0}
                inspectionPlayback={{ timeRef: clock, playing: playing && mode === 'inspection' }}
                operation={{
                  playing: playing && mode !== 'inspection',
                  steps: project.plan?.steps ?? [],
                  onComplete: () => setPlaying(false),
                  resetKey: project.revision,
                  timeline: plan,
                  time_s: time,
                  timeRef: clock,
                }}
              />
            </div>
            <OperatingPreview
              machineApproved
              plan={plan}
              playing={playing}
              time={time}
              speed={speed}
              disabled={busy || dirty}
              hasInspection={Boolean(project.inspection_extension)}
              hasColdTransfer={Boolean(project.cold_transfer_extension)}
              onMode={value => {
                reset();
                setMode(value);
              }}
              onPlay={() => {
                if (clock.current >= plan.duration_s) reset();
                setPlaying(true);
              }}
              onPause={() => setPlaying(false)}
              onReset={reset}
              onSeek={value => {
                setPlaying(false);
                clock.current = value;
                setTime(value);
              }}
              onSpeed={setSpeed}
            />
            <p className="software-scope">
              Play moves the 3D model in your browser. No commands are sent to a physical machine.
            </p>
            {project.design.foundation && <details className="software-scope software-hardware-guide">
              <summary>How would I run this on my Jubilee?</summary>
              <p>Use the transfer list to write a Science Jubilee protocol for your controller.
                Configure the pipette, calibrate the deck positions and dry-run the moves before loading samples.</p>
              <a href="https://science-jubilee.readthedocs.io/en/latest/getting_started/index.html"
                target="_blank" rel="noopener noreferrer">Science Jubilee setup guide</a>
            </details>}
          </section>
        ) : (
          <div className="software-general-program">
            {project.concept_design ? (
              <ConceptWorkspace
                key={key}
                projectId={project.id}
                revision={project.revision}
                design={project.concept_design}
              />
            ) : project.bench_station ? (
              <BenchStationPanel
                key={key}
                project={project}
                station={project.bench_station}
                projectId={project.id}
                revision={project.revision}
              />
            ) : (
              <p>Continue in chat to specify the controller and supported operations.</p>
            )}
          </div>
        )}
      </div>
      <PoweredByMeta />
    </main>
  );
}
