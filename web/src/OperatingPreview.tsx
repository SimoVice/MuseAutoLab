import type { MotionMode, MotionPlan } from './motionPlan';
import { sampleMotionPlan } from './motionPlan';
import './operating-preview.css';

type Props = { plan: MotionPlan; playing: boolean; time: number; speed: number; disabled: boolean; hasInspection: boolean; onMode: (mode: MotionMode) => void; onPlay: () => void; onPause: () => void; onReset: () => void; onSeek: (time: number) => void; onSpeed: (speed: number) => void };
export default function OperatingPreview({ plan, playing, time, speed, disabled, hasInspection, onMode, onPlay, onPause, onReset, onSeek, onSpeed }: Props) {
  const frame = sampleMotionPlan(plan, time);
  const unavailable = plan.status !== 'ready';
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ ...plan, execution_enabled: false }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `motion-plan-r${plan.revision}-${plan.mode}.json`; link.click(); URL.revokeObjectURL(url);
  }
  return <section className="operating-preview" aria-label="Operating preview" data-testid="operating-preview">
    <div className="operating-preview-heading"><h2>Operating preview</h2><span>Illustrative motion · r{plan.revision}</span></div>
    {unavailable ? <p className="operation-scope">{plan.message}</p> : <>
      <div className="operation-now"><strong>{frame.stage}</strong><span>{frame.target}{frame.volume_ul != null ? ` · ${frame.volume_ul.toLocaleString('en-US', { maximumFractionDigits: 3 })} µL total` : ''}</span></div>
      <div className="operation-buttons">
        <button type="button" onClick={onPlay} disabled={disabled || playing}>Play</button>
        <button type="button" onClick={onPause} disabled={!playing}>Pause</button>
        <button type="button" onClick={onReset} disabled={disabled}>Reset</button>
      </div>
    </>}
    {(!unavailable || hasInspection) && <details className="operation-limits"><summary>Playback details</summary>
      {hasInspection && <label className="operation-mode">Sequence<select aria-label="Operating sequence" value={plan.mode} onChange={(event) => onMode(event.target.value as MotionMode)} disabled={disabled}><option value="preparation">Preparation</option><option value="inspection">Inspection concept</option></select></label>}
      {!unavailable && <>
        <p className="operation-scope">{plan.message}</p>
        <label className="operation-time" htmlFor="operation-time">Preview time <span>{time.toFixed(1)} / {plan.duration_s.toFixed(1)} s</span></label>
        <input id="operation-time" aria-label="Operating timeline" type="range" min={0} max={plan.duration_s} step={0.05} value={time} disabled={disabled} onChange={(event) => onSeek(Number(event.target.value))} />
        <label>Speed<select aria-label="Playback speed" value={speed} onChange={(event) => onSpeed(Number(event.target.value))} disabled={disabled}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
        <ul>{plan.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
        <button type="button" onClick={download}>Download motion plan</button>
      </>}
    </details>}
  </section>;
}
