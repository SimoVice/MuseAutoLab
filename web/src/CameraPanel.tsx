import { useCallback, useEffect, useRef, useState } from 'react';
import type { Project } from './types';
import type {
  ReviewAddition,
  ReviewDecision,
  VisionBox,
  VisionComponentId,
  VisionDetection,
  VisionJob,
  VisionKind,
  TipRackContents,
} from './visionTypes';

type Props = {
  project: Project;
  onSelect: (id: string) => void;
};

const KINDS: VisionKind[] = ['tube', 'pipette_tip', 'tip_rack', 'uncertain_labware'];
const COMPONENT_OPTIONS: Array<VisionComponentId | ''> = ['', 'source-rack', 'sample-rack', 'tip-rack'];
const MAX_UPLOAD_BYTES = 16 * 1024 * 1024;
const MAX_FINAL_BYTES = 4 * 1024 * 1024;
const MAX_EDGE = 1600;
const EXAMPLE_URL = '/examples/labware.jpg';
const COMMONS_URL = 'https://commons.wikimedia.org/wiki/File:Laboratory_microcentrifuge_tubes_and_pipette_tips_01.jpg';

function stateLabel(value: string): string { return value.replaceAll('_', ' '); }

function kindLabel(kind: VisionKind): string {
  if (kind === 'tube') return 'Tube';
  if (kind === 'pipette_tip') return 'Pipette tip';
  if (kind === 'tip_rack') return 'Tip rack';
  return 'Uncertain labware';
}

function confidenceText(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return 'no score';
  return `${Math.round(value * 100)}% assessment score, not calibrated`;
}

function validBox(box: VisionBox): string | null {
  const vals = [box.x_min, box.y_min, box.x_max, box.y_max];
  if (vals.some((v) => !Number.isFinite(v))) return 'Box values must be numbers.';
  if (vals.some((v) => v < 0 || v > 1000)) return 'Box values must be within 0 to 1000.';
  if (!(box.x_min < box.x_max)) return 'x_min must be less than x_max.';
  if (!(box.y_min < box.y_max)) return 'y_min must be less than y_max.';
  return null;
}

async function readError(response: Response): Promise<string> {
  const data: unknown = await response.json().catch(() => null);
  if (data && typeof data === 'object' && 'detail' in data && typeof (data as { detail: unknown }).detail === 'string') {
    return (data as { detail: string }).detail;
  }
  return `Request failed (${response.status}). Please try again.`;
}

function approxDataUrlBytes(dataUrl: string): number {
  const comma = dataUrl.indexOf(',');
  const body = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  return Math.floor(body.length * 0.75);
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('The image could not be read. Use a JPEG or PNG photo.'));
    img.src = src;
  });
}

async function downscaleToJpeg(source: string): Promise<string> {
  const img = await loadImage(source);
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  if (!w || !h) throw new Error('The image could not be read.');
  const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
  const cw = Math.max(1, Math.round(w * scale));
  const ch = Math.max(1, Math.round(h * scale));
  const canvas = document.createElement('canvas');
  canvas.width = cw;
  canvas.height = ch;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('The image could not be processed in this browser.');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, cw, ch);
  ctx.drawImage(img, 0, 0, cw, ch);
  let quality = 0.92;
  let out = canvas.toDataURL('image/jpeg', quality);
  while (approxDataUrlBytes(out) > MAX_FINAL_BYTES && quality > 0.55) {
    quality -= 0.1;
    out = canvas.toDataURL('image/jpeg', quality);
  }
  if (approxDataUrlBytes(out) > MAX_FINAL_BYTES) {
    throw new Error('The resized photo is still larger than 4 MiB. Use a smaller photo.');
  }
  return out;
}

function stopStream(stream: MediaStream | null): void {
  if (!stream) return;
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      /* ignore */
    }
  }
}

type DraftEdit = {
  tip_rack_contents: TipRackContents;
  kind: VisionKind;
  label: string;
  x_min: string;
  y_min: string;
  x_max: string;
  y_max: string;
  component_id: string;
};

function draftFromDetection(d: VisionDetection): DraftEdit {
  return {
    kind: d.kind,
    tip_rack_contents: d.tip_rack_contents,
    label: d.label,
    x_min: String(Math.round(d.box.x_min)),
    y_min: String(Math.round(d.box.y_min)),
    x_max: String(Math.round(d.box.x_max)),
    y_max: String(Math.round(d.box.y_max)),
    component_id: d.component_id ?? '',
  };
}

function draftToBox(d: DraftEdit): VisionBox | null {
  if ([d.x_min, d.y_min, d.x_max, d.y_max].some((value) => !value.trim())) return null;
  const box: VisionBox = {
    x_min: Number(d.x_min),
    y_min: Number(d.y_min),
    x_max: Number(d.x_max),
    y_max: Number(d.y_max),
  };
  if ([box.x_min, box.y_min, box.x_max, box.y_max].some((v) => !Number.isFinite(v))) return null;
  return box;
}

export default function CameraPanel({ project, onSelect }: Props) {
  const [photo, setPhoto] = useState<string | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [startingCamera, setStartingCamera] = useState(false);
  const [job, setJob] = useState<VisionJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftEdit>>({});
  const [decisions, setDecisions] = useState<Record<string, 'accept' | 'reject'>>({});
  const [reviewing, setReviewing] = useState(false);
  const [loadingExample, setLoadingExample] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [addDraft, setAddDraft] = useState<DraftEdit>({
    kind: 'tube',
    tip_rack_contents: 'unknown',
    label: '',
    x_min: '100',
    y_min: '100',
    x_max: '300',
    y_max: '300',
    component_id: '',
  });
  const [addError, setAddError] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const epochRef = useRef(0);
  const pollTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const projectKey = `${project.id}:${project.revision}`;

  const clearPoll = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const stopCamera = useCallback(() => {
    stopStream(streamRef.current);
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
    setStartingCamera(false);
  }, []);

  useEffect(() => {
    epochRef.current += 1;
    abortRef.current?.abort();
    clearPoll();
    stopStream(streamRef.current);
    streamRef.current = null;
    setPhoto(null);
    setCameraOn(false);
    setCameraError(null);
    setStartingCamera(false);
    setJob(null);
    setBusy(false);
    setError(null);
    setSelectedId(null);
    setDrafts({});
    setDecisions({});
    setReviewing(false);
    setShowAdd(false);
    setLoadingExample(false);
    setAddError(null);
    return () => {
      epochRef.current += 1;
      abortRef.current?.abort();
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      stopStream(streamRef.current);
      streamRef.current = null;
    };
  }, [projectKey, clearPoll]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      stopStream(streamRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!job?.result) return;
    const next: Record<string, DraftEdit> = {};
    for (const d of job.result.detections) next[d.id] = draftFromDetection(d);
    setDrafts(next);
    setDecisions({});
    setSelectedId(null);
    setReviewing(false);
  }, [job?.id, job?.result?.observation_version]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!cameraOn || !videoRef.current || !streamRef.current) return;
    const video = videoRef.current;
    video.srcObject = streamRef.current;
    void video.play().catch(() => setCameraError('Cannot start the preview. Try capturing again or upload a photo.'));
  }, [cameraOn]);

  async function handleFile(file: File): Promise<void> {
    setLoadingExample(false);
    const epoch = ++epochRef.current;
    abortRef.current?.abort();
    clearPoll();
    stopCamera();
    setBusy(false);
    setJob(null);
    setError(null);
    try {
    if (file.type !== 'image/jpeg' && file.type !== 'image/png') {
      setError('Upload only a JPEG or PNG photo.');
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError('The photo is larger than 16 MiB. Use a smaller file.');
      return;
    }
    const raw = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error('The photo could not be read.'));
      reader.readAsDataURL(file);
    });
      const resized = await downscaleToJpeg(raw);
      if (epochRef.current !== epoch) return;
      setPhoto(resized);
      setJob(null);
      setError(null);
    } catch (e) {
      if (epochRef.current === epoch) setError(e instanceof Error ? e.message : 'The photo could not be processed.');
    }
  }

  async function startCamera(): Promise<void> {
    setLoadingExample(false);
    const epoch = ++epochRef.current;
    abortRef.current?.abort();
    clearPoll();
    setBusy(false);
    setJob(null);
    setPhoto(null);
    setCameraError(null);
    setStartingCamera(true);
    stopStream(streamRef.current);
    streamRef.current = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('This browser does not support camera capture. Upload a photo instead.');
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      if (epochRef.current !== epoch) {
        stopStream(stream);
        return;
      }
      if (!stream.getVideoTracks().some((track) => track.readyState === 'live')) {
        stopStream(stream);
        throw new Error('The camera stopped before a frame was available. Try again or upload a photo.');
      }
      stream.getVideoTracks().forEach((track) => track.addEventListener('ended', () => {
        if (streamRef.current !== stream) return;
        stopCamera();
        setCameraError('The camera disconnected. Reconnect it or upload a photo.');
      }));
      streamRef.current = stream;
      setCameraOn(true);
    } catch (e) {
      if (epochRef.current !== epoch) return;
      setCameraError(e instanceof Error ? e.message : 'Camera unavailable. Upload a photo instead.');
      setCameraOn(false);
    } finally {
      if (epochRef.current === epoch) setStartingCamera(false);
    }
  }

  function handleStopCamera(): void {
    epochRef.current += 1;
    stopCamera();
  }

  async function capture(): Promise<void> {
    const video = videoRef.current;
    if (!video || video.videoWidth < 32 || video.videoHeight < 32) {
      setCameraError('No camera frame available yet. Wait a moment and try again.');
      return;
    }
    const epoch = epochRef.current;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setCameraError('Capture failed in this browser. Upload a photo instead.');
      return;
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    stopStream(streamRef.current);
    streamRef.current = null;
    if (video) video.srcObject = null;
    if (epochRef.current !== epoch) return;
    setCameraOn(false);
    try {
      const resized = await downscaleToJpeg(dataUrl);
      if (epochRef.current !== epoch) return;
      setPhoto(resized);
      setJob(null);
      setCameraError(null);
    } catch (e) {
      setCameraError(e instanceof Error ? e.message : 'Capture failed. Try again.');
    }
  }

  async function loadExample(): Promise<void> {
    const epoch = ++epochRef.current;
    abortRef.current?.abort();
    clearPoll();
    stopCamera();
    setBusy(false);
    setJob(null);
    setLoadingExample(true);
    setError(null);
    try {
      const response = await fetch(EXAMPLE_URL);
      if (!response.ok) throw new Error('Example photo unavailable. Upload a photo instead.');
      const blob = await response.blob();
      if (blob.size > MAX_UPLOAD_BYTES) throw new Error('Example photo is too large.');
      const raw = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error('Example photo could not be read.'));
        reader.readAsDataURL(blob);
      });
      const resized = await downscaleToJpeg(raw);
      if (epochRef.current !== epoch) return;
      setPhoto(resized);
      setJob(null);
    } catch (e) {
      if (epochRef.current === epoch) setError(e instanceof Error ? e.message : 'Example photo unavailable.');
    } finally {
      if (epochRef.current === epoch) setLoadingExample(false);
    }
  }

  const fetchJob = useCallback(
    async (jobId: string, signal: AbortSignal): Promise<VisionJob> => {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(project.id)}/inspections/${encodeURIComponent(jobId)}`,
        { signal },
      );
      if (!response.ok) throw new Error(await readError(response));
      return (await response.json()) as VisionJob;
    },
    [project.id],
  );

  const pollJob = useCallback(
    (jobId: string, epoch: number, signal: AbortSignal) => {
      clearPoll();
      const tick = async (): Promise<void> => {
        if (epochRef.current !== epoch || signal.aborted) return;
        try {
          const updated = await fetchJob(jobId, signal);
          if (epochRef.current !== epoch || signal.aborted) return;
          if (updated.project_revision !== project.revision) return;
          setJob(updated);
          if (updated.status === 'ready' || updated.status === 'failed') {
            setBusy(false);
            return;
          }
          pollTimer.current = window.setTimeout(() => void tick(), 1200);
        } catch (e) {
          if (epochRef.current !== epoch || signal.aborted) return;
          if (signal.aborted) return;
          setError(e instanceof Error ? e.message : 'Could not check inspection. Use Retry.');
          setBusy(false);
        }
      };
      pollTimer.current = window.setTimeout(() => void tick(), 1200);
    },
    [clearPoll, fetchJob, project.revision],
  );

  async function analyze(): Promise<void> {
    if (!photo || busy) return;
    clearPoll();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const epoch = ++epochRef.current;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}/inspections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_revision: project.revision, image_data_url: photo }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readError(response));
      const created = (await response.json()) as VisionJob;
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setJob(created);
      if (created.status === 'ready' || created.status === 'failed') {
        setBusy(false);
        return;
      }
      pollJob(created.id, epoch, controller.signal);
    } catch (e) {
      if (epochRef.current !== epoch || controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : 'Inspection failed. No detections were fabricated.');
      setBusy(false);
    }
  }

  function retryPoll(): void {
    if (!job || job.status === 'ready' || job.status === 'failed') {
      if (photo && !busy) void analyze();
      return;
    }
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const epoch = ++epochRef.current;
    pollJob(job.id, epoch, controller.signal);
  }

  function buildDecisions(): { list: ReviewDecision[]; problem: string | null } {
    if (!job?.result) return { list: [], problem: 'No inspection to review.' };
    const list: ReviewDecision[] = [];
    for (const d of job.result.detections) {
      const action = decisions[d.id];
      if (!action) continue;
      const draft = drafts[d.id];
      if (!draft) continue;
      const entry: ReviewDecision = { id: d.id, action };
      if (action === 'accept') {
        if (draft.kind === 'tip_rack') entry.tip_rack_contents = draft.tip_rack_contents === 'not_applicable' ? 'unknown' : draft.tip_rack_contents;
        const changedKind = draft.kind !== d.kind;
        const changedLabel = draft.label.trim() !== d.label;
        const parsed = draftToBox(draft);
        const boxChanged =
          parsed == null ||
          parsed.x_min !== Math.round(d.box.x_min) ||
          parsed.y_min !== Math.round(d.box.y_min) ||
          parsed.x_max !== Math.round(d.box.x_max) ||
          parsed.y_max !== Math.round(d.box.y_max);
        if (changedKind) entry.kind = draft.kind;
        if (changedLabel) {
          if (draft.label.trim().length === 0 || draft.label.trim().length > 80) {
            return { list: [], problem: `Label for ${d.id} must be 1 to 80 characters.` };
          }
          entry.label = draft.label.trim();
        }
        if (boxChanged) {
          if (!parsed) return { list: [], problem: `Box for ${d.id} must be numeric.` };
          const err = validBox(parsed);
          if (err) return { list: [], problem: `${d.id}: ${err}` };
          entry.box = { x_min: Math.round(parsed.x_min), y_min: Math.round(parsed.y_min), x_max: Math.round(parsed.x_max), y_max: Math.round(parsed.y_max) };
        }
        const comp = draft.component_id.trim();
        const prevComp = d.component_id ?? '';
        if (comp !== prevComp) {
          if (comp !== '' && comp !== 'source-rack' && comp !== 'sample-rack' && comp !== 'tip-rack') {
            return { list: [], problem: `Component mapping for ${d.id} must be source-rack, sample-rack, tip-rack, or empty.` };
          }
          entry.component_id = comp === '' ? null : (comp as VisionComponentId);
        }
      }
      list.push(entry);
    }
    return { list, problem: null };
  }

  function buildAdditions(): { list: ReviewAddition[]; problem: string | null } {
    if (!showAdd) return { list: [], problem: null };
    if (addDraft.label.trim().length === 0 || addDraft.label.trim().length > 80) {
      return { list: [], problem: 'Added object label must be 1 to 80 characters.' };
    }
    const box = draftToBox(addDraft);
    if (!box) return { list: [], problem: 'Added box values must be numeric.' };
    const err = validBox(box);
    if (err) return { list: [], problem: `Added box: ${err}` };
    const comp = addDraft.component_id.trim();
    if (comp !== '' && comp !== 'source-rack' && comp !== 'sample-rack' && comp !== 'tip-rack') {
      return { list: [], problem: 'Added component mapping must be source-rack, sample-rack, tip-rack, or empty.' };
    }
    return {
      list: [
        {
          kind: addDraft.kind,
          tip_rack_contents: addDraft.kind === 'tip_rack' ? addDraft.tip_rack_contents : 'not_applicable',
          label: addDraft.label.trim(),
          box: { x_min: Math.round(box.x_min), y_min: Math.round(box.y_min), x_max: Math.round(box.x_max), y_max: Math.round(box.y_max) },
          component_id: comp === '' ? null : (comp as VisionComponentId),
        },
      ],
      problem: null,
    };
  }

  async function submitReview(sceneReviewed: boolean): Promise<void> {
    if (!job?.result || reviewing) return;
    const dec = buildDecisions();
    if (dec.problem) {
      setError(dec.problem);
      return;
    }
    const add = buildAdditions();
    if (add.problem) {
      setAddError(add.problem);
      return;
    }
    setReviewing(true);
    setError(null);
    const epoch = epochRef.current;
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(project.id)}/inspections/${encodeURIComponent(job.id)}/review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            observation_version: job.result.observation_version,
            scene_reviewed: sceneReviewed,
            decisions: dec.list,
            additions: add.list,
          }),
        },
      );
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as VisionJob;
      if (epochRef.current !== epoch) return;
      setJob(updated);
      setShowAdd(false);
      setAddError(null);
    } catch (e) {
      if (epochRef.current === epoch) setError(e instanceof Error ? e.message : 'Review failed. Try again.');
    } finally {
      if (epochRef.current === epoch) setReviewing(false);
    }
  }

  const result = job?.result ?? null;
  const pending = job != null && (job.status === 'queued' || job.status === 'running');
  const displaySrc = result ? result.image.url : photo;
  const aspect = result ? `${result.image.width} / ${result.image.height}` : undefined;
  const decidedCount = result ? result.detections.filter((d) => d.state === 'confirmed' || d.state === 'rejected' || decisions[d.id] != null).length : 0;
  const totalCount = result?.detections.length ?? 0;
  const allDecided = result != null && result.detections.every((d) => d.state === 'confirmed' || d.state === 'rejected' || decisions[d.id] != null);
  const allowSceneReview = result != null && allDecided;
  const selected = result?.detections.find((d) => d.id === selectedId) ?? null;

  function updateDraft(id: string, patch: Partial<DraftEdit>): void {
    setDrafts((prev) => (prev[id] ? { ...prev, [id]: { ...prev[id], ...patch } } : prev));
  }

  return (
    <section className="camera-card" aria-labelledby="camera-title">
      <div className="camera-heading">
        <div>
          <h2 id="camera-title">Labware photo check</h2>
          <p>Upload or capture a bench photo. Model detections are unverified until you review them. Positions are image fractions, not metric coordinates.</p>
        </div>
        <span className="camera-status">{cameraOn ? 'Live preview' : job ? job.status : 'no photo yet'}</span>
      </div>

      <p className="camera-notice">Only Analyze photo sends this image to Meta Contributor, where it may be used for training. Camera preview stays on this device.</p>

      <div className="camera-grid">
        <div className="camera-preview">
          {cameraOn ? (
            <div className="camera-video-wrap">
              <video ref={videoRef} className="camera-video" playsInline muted aria-label="Live camera preview" />
              <div className="camera-row">
                <button type="button" className="camera-button-primary" onClick={() => void capture()}>Capture</button>
                <button type="button" className="camera-button" onClick={handleStopCamera}>Stop camera</button>
              </div>
            </div>
          ) : (
            <>
              {displaySrc ? (
                <div className="camera-image-wrap" style={aspect ? { aspectRatio: aspect } : undefined}>
                  <img src={displaySrc} alt="Labware photo under review" className="camera-image" />
                  {result && (
                    <svg className="camera-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="false" role="group" aria-label="Detection overlay">
                      {result.detections.map((d) => (
                        <g
                          key={d.id}
                          role="button"
                          tabIndex={0}
                          aria-label={`Select ${d.id} ${d.label}`}
                          className={`${selectedId === d.id ? 'camera-box-selected' : 'camera-box'} camera-box-${d.state}`}
                          onClick={() => setSelectedId(d.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setSelectedId(d.id);
                            }
                          }}
                        >
                          <rect
                            x={d.box.x_min}
                            y={d.box.y_min}
                            width={Math.max(4, d.box.x_max - d.box.x_min)}
                            height={Math.max(4, d.box.y_max - d.box.y_min)}
                          />
                          <text x={d.box.x_min + 6} y={Math.max(24, d.box.y_min + 26)}>{d.id}</text>
                        </g>
                      ))}
                    </svg>
                  )}
                </div>
              ) : (
                <>
                  <video ref={videoRef} className="camera-video-hidden" playsInline muted aria-hidden="true" />
                  <div className="camera-empty">
                    <p>No photo yet. Upload a JPEG or PNG, use the camera, or try the example photo.</p>
                  </div>
                </>
              )}
              {cameraOn === false && displaySrc && (
                <video ref={displaySrc ? videoRef : undefined} className="camera-video-hidden" playsInline muted aria-hidden="true" />
              )}
            </>
          )}
          {cameraError && (
            <div className="camera-error" role="alert">
              <span>{cameraError}</span>
              <button type="button" onClick={() => setCameraError(null)}>Dismiss</button>
            </div>
          )}
        </div>

        <div className="camera-inspector">
          <label className="camera-label" htmlFor="camera-upload">Upload labware photo</label>
          <input
            ref={fileRef}
            id="camera-upload"
            type="file"
            accept="image/jpeg,image/png"
            className="camera-file"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleFile(f);
              e.target.value = '';
            }}
          />
          <div className="camera-row">
            <button type="button" className="camera-button" onClick={() => fileRef.current?.click()}>Upload photo</button>
            <button type="button" className="camera-button" onClick={startCamera} disabled={startingCamera || cameraOn}>
              {startingCamera ? 'Starting…' : 'Use camera'}
            </button>
            <button type="button" className="camera-button" onClick={() => void loadExample()} disabled={loadingExample}>
              {loadingExample ? 'Loading…' : 'Load example photo'}
            </button>
            <button type="button" className="camera-button-primary" onClick={() => void analyze()} disabled={!photo || cameraOn || startingCamera || loadingExample || busy || pending}>
              {busy || pending ? 'Analyzing…' : 'Analyze photo'}
            </button>
          </div>
          <p className="camera-hint">
            JPEG or PNG up to 16 MiB; resized to longest edge 1600 and JPEG before analysis. Example:{' '}
            <a href={COMMONS_URL} target="_blank" rel="noreferrer">Laboratory microcentrifuge tubes and pipette tips 01.jpg, CC BY-SA 4.0, Gannu03</a>.
          </p>

          {error && (
            <div className="camera-error" role="alert">
              <span>{error}</span>
              <button type="button" onClick={retryPoll}>Retry</button>
            </div>
          )}
          {pending && <p className="camera-progress" role="status">{job?.stage || 'Inspecting photo…'} Waiting for image analysis…</p>}
          {job?.status === 'failed' && (
            <div className="camera-error" role="alert">
              <span>{job.error || 'Inspection failed. No detections were fabricated.'}</span>
              <button type="button" onClick={() => void analyze()}>Retry</button>
            </div>
          )}
        </div>
      </div>

      {result && (
        <div className="camera-result">
          <div className="camera-summary">
            <p><strong>Summary:</strong> {result.summary}</p>
            <p>Quality: {result.image_quality} · Coverage: {result.coverage} · Version {result.observation_version}</p>
            <p>Tubes: {stateLabel(result.presence.tubes)} · Pipette tips: {stateLabel(result.presence.pipette_tips)}</p>
            {result.warnings.length > 0 && (
              <ul>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            )}
            <p className="camera-hint">An empty list means nothing was observed, not that the bench is empty. Counts below are observed image regions only.</p>
          </div>

          <ul className="camera-cards">
            {result.detections.map((d) => {
              const draft = drafts[d.id] ?? draftFromDetection(d);
              return (
                <li key={d.id} className={selectedId === d.id ? 'camera-det selected' : 'camera-det'}>
                  <button type="button" className="camera-det-head" onClick={() => setSelectedId(selectedId === d.id ? null : d.id)} aria-expanded={selectedId === d.id} aria-controls={`det-${d.id}`}>
                    <strong>{d.id} · {kindLabel(d.kind)}</strong>
                    <span>{confidenceText(d.confidence)} · {stateLabel(d.state)}{d.uncertain ? ' · uncertain' : ''}</span>
                  </button>
                  <div id={`det-${d.id}`} className="camera-det-body">
                    <p>{d.label} — {d.reason}</p>
                    <div className="camera-field-row">
                      <label>Category
                        <select value={draft.kind} onChange={(e) => updateDraft(d.id, { kind: e.target.value as VisionKind })}>
                          {KINDS.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
                        </select>
                      </label>
                      <label>Label
                        <input value={draft.label} maxLength={80} onChange={(e) => updateDraft(d.id, { label: e.target.value })} />
                      </label>
                    </div>
                    <div className="camera-box-grid" role="group" aria-label={`Bounding box for ${d.id} in 0 to 1000 image units`}>
                      {(['x_min', 'y_min', 'x_max', 'y_max'] as const).map((key) => (
                        <label key={key}>{key}
                          <input
                            type="number"
                            min={0}
                            max={1000}
                            step={1}
                            value={draft[key]}
                            onChange={(e) => updateDraft(d.id, { [key]: e.target.value } as Partial<DraftEdit>)}
                          />
                        </label>
                      ))}
                    </div>
                    {draft.kind === 'tip_rack' && <label>Rack contents
                      <select value={draft.tip_rack_contents === 'not_applicable' ? 'unknown' : draft.tip_rack_contents} onChange={(e) => updateDraft(d.id, { tip_rack_contents: e.target.value as TipRackContents })}>
                        <option value="unknown">Cannot tell</option><option value="tips_visible">Tips visible</option><option value="empty_visible">Rack appears empty</option>
                      </select>
                    </label>}
                    <label>Manual 3D association
                      <select value={draft.component_id} onChange={(e) => updateDraft(d.id, { component_id: e.target.value })}>
                        {COMPONENT_OPTIONS.map((c) => (
                          <option key={c || 'none'} value={c}>{c === '' ? 'Not mapped' : c}</option>
                        ))}
                      </select>
                    </label>
                    <div className="camera-row">
                      <button
                        type="button"
                        className={decisions[d.id] === 'accept' ? 'camera-button-primary' : 'camera-button'}
                        aria-pressed={decisions[d.id] === 'accept'}
                        onClick={() => setDecisions((prev) => ({ ...prev, [d.id]: 'accept' }))}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className={decisions[d.id] === 'reject' ? 'camera-button-primary' : 'camera-button'}
                        aria-pressed={decisions[d.id] === 'reject'}
                        onClick={() => setDecisions((prev) => ({ ...prev, [d.id]: 'reject' }))}
                      >
                        Reject
                      </button>
                      {draft.component_id && (
                        <button type="button" className="camera-button" onClick={() => onSelect(draft.component_id)}>
                          Show in 3D
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          {result.detections.length === 0 && <p className="camera-hint">No regions observed. Add a missed object below if needed.</p>}

          <div className="camera-add">
            <button type="button" className="camera-button" aria-expanded={showAdd} onClick={() => setShowAdd((v) => !v)}>
              {showAdd ? 'Cancel addition' : 'Add missed object'}
            </button>
            {showAdd && (
              <div className="camera-add-form">
                <div className="camera-field-row">
                  <label>Category
                    <select value={addDraft.kind} onChange={(e) => setAddDraft({ ...addDraft, kind: e.target.value as VisionKind })}>
                      {KINDS.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
                    </select>
                  </label>
                  <label>Label
                    <input value={addDraft.label} maxLength={80} onChange={(e) => setAddDraft({ ...addDraft, label: e.target.value })} placeholder="e.g. tube near left edge" />
                  </label>
                </div>
                <div className="camera-box-grid" role="group" aria-label="Added object bounding box in 0 to 1000 image units">
                  {(['x_min', 'y_min', 'x_max', 'y_max'] as const).map((key) => (
                    <label key={key}>{key}
                      <input type="number" min={0} max={1000} step={1} value={addDraft[key]} onChange={(e) => setAddDraft({ ...addDraft, [key]: e.target.value })} />
                    </label>
                  ))}
                </div>
                {addDraft.kind === 'tip_rack' && <label>Rack contents
                  <select value={addDraft.tip_rack_contents} onChange={(e) => setAddDraft({ ...addDraft, tip_rack_contents: e.target.value as TipRackContents })}>
                    <option value="unknown">Cannot tell</option><option value="tips_visible">Tips visible</option><option value="empty_visible">Rack appears empty</option>
                  </select>
                </label>}
                <label>Manual 3D association
                  <select value={addDraft.component_id} onChange={(e) => setAddDraft({ ...addDraft, component_id: e.target.value })}>
                    {COMPONENT_OPTIONS.map((c) => (
                      <option key={c || 'none'} value={c}>{c === '' ? 'Not mapped' : c}</option>
                    ))}
                  </select>
                </label>
                {addError && <p className="camera-error-text" role="alert">{addError}</p>}
              </div>
            )}
          </div>

          <div className="camera-review">
            <div className="camera-row">
              <button type="button" className="camera-button" disabled={reviewing} onClick={() => void submitReview(false)}>
                {reviewing ? 'Saving…' : 'Save decisions'}
              </button>
              <button type="button" className="camera-button" disabled={reviewing} onClick={() => setDecisions(Object.fromEntries(result.detections.filter((d) => d.state !== 'rejected').map((d) => [d.id, 'accept'])))}>Accept visible regions</button>
              <button
                type="button"
                className="camera-button-primary"
                disabled={!allowSceneReview || reviewing}
                onClick={() => void submitReview(true)}
                title={allowSceneReview ? 'Mark scene reviewed' : 'Decide every object first'}
              >
                {reviewing ? 'Saving…' : 'Review scene'}
              </button>
              <a
                className="camera-button camera-link"
                href={`/api/projects/${encodeURIComponent(project.id)}/inspections/${encodeURIComponent(job!.id)}/archive?observation_version=${result.observation_version}`}
                download
              >
                Download inspection zip
              </a>
            </div>
            <p className="camera-hint">
              {result.scene_reviewed ? 'Scene reviewed.' : 'Scene not reviewed yet.'} Review required: {result.review_required ? 'yes' : 'no'}.
              Decided {decidedCount}/{totalCount}. Explicit scene review needs every object confirmed or rejected.
              {selected ? ` Selected: ${selected.id}.` : ''}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
