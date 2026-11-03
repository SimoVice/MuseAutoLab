import type { MotionMode, MotionPlan } from './motionPlan';
import { sampleMotionPlan } from './motionPlan';
import './operating-preview.css';

type Props = { machineApproved?: boolean; plan: MotionPlan; playing: boolean; time: number; speed: number; disabled: boolean; hasInspection: boolean; hasColdTransfer: boolean; onMode: (mode: MotionMode) => void; onPlay: () => void; onPause: () => void; onReset: () => void; onSeek: (time: number) => void; onSpeed: (speed: number) => void };
export default function OperatingPreview({ machineApproved = false, plan, playing, time, speed, disabled, hasInspection, hasColdTransfer, onMode, onPlay, onPause, onReset, onSeek, onSpeed }: Props) {
  const frame = sampleMotionPlan(plan, time);
  const unavailable = plan.status !== 'ready';
  function download() {
    if (plan.scope === 'illustrative') return;
    const url = URL.createObjectURL(new Blob([JSON.stringify({ ...plan, execution_enabled: false }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `motion-plan-r${plan.revision}-${plan.mode}.json`; link.click(); URL.revokeObjectURL(url);
  }
  return <section className="operating-preview" aria-label="Operating preview" data-testid="operating-preview">
    <div className="operating-preview-heading"><h2>Operating preview</h2><span>{plan.mode === 'inspection' ? 'Camera sweep' : plan.mode === 'cold-transfer' ? 'Plate transfer' : plan.scope === 'illustrative' ? 'Example motion' : 'Recipe motion'} · r{plan.revision}</span></div>
    {plan.scope === 'illustrative' && plan.illustrative_recipe && <p className="operation-scope">Illustrative example only, not your recipe: stock {plan.illustrative_recipe.stock}; target {plan.illustrative_recipe.target}; final volume {plan.illustrative_recipe.final_volume_ul} µL. The example transfers {plan.illustrative_recipe.stock_volume_ul} µL stock and {plan.illustrative_recipe.diluent_volume_ul} µL diluent to one destination. These example values are not saved. {machineApproved ? 'Create your recipe to preview your own transfers.' : 'Approve the design to program your own transfers.'}</p>}
    {(hasInspection || hasColdTransfer) && <label className="operation-mode">Sequence<select aria-label="Operating sequence" value={plan.mode} onChange={(event) => onMode(event.target.value as MotionMode)} disabled={disabled}>
      <option value="preparation">Preparation</option>
      {hasInspection && <option value="inspection">Camera inspection</option>}
      {hasColdTransfer && <option value="cold-transfer">Cold transfer</option>}
    </select></label>}
    {unavailable ? <p className="operation-scope">{plan.message}</p> : <>
      <div className="operation-now"><strong>{frame.stage}</strong><span>{frame.target}{frame.volume_ul != null ? ` · ${frame.volume_ul.toLocaleString('en-US', { maximumFractionDigits: 3 })} µL total` : ''}</span></div>
      <div className="operation-buttons">
        <button type="button" onClick={onPlay} disabled={disabled || playing}>Play</button>
        <button type="button" onClick={onPause} disabled={!playing}>Pause</button>
        <button type="button" onClick={onReset} disabled={disabled}>Reset</button>
      </div>
    </>}
    {!unavailable && <details className="operation-limits"><summary>Playback details</summary>
      {!unavailable && <>
        <p className="operation-scope">{plan.message}</p>
        <label className="operation-time" htmlFor="operation-time">Preview time <span>{time.toFixed(1)} / {plan.duration_s.toFixed(1)} s</span></label>
        <input id="operation-time" aria-label="Operating timeline" type="range" min={0} max={plan.duration_s} step={0.05} value={time} disabled={disabled} onChange={(event) => onSeek(Number(event.target.value))} />
        <label>Speed<select aria-label="Playback speed" value={speed} onChange={(event) => onSpeed(Number(event.target.value))} disabled={disabled}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
        <ul>{plan.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
        {plan.scope !== 'illustrative' && <button type="button" onClick={download}>Download motion plan</button>}
      </>}
    </details>}
  </section>;
}
