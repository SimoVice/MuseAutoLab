export type VisionKind = 'tube' | 'pipette_tip' | 'tip_rack' | 'uncertain_labware';

export type VisionBox = {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
};

export type DetectionState = 'observed' | 'needs_review' | 'confirmed' | 'rejected';

export type DetectionOrigin = 'model' | 'human';

export type VisionComponentId = 'source-rack' | 'sample-rack' | 'tip-rack';

export type TipRackContents = 'tips_visible' | 'empty_visible' | 'unknown' | 'not_applicable';

export type VisionDetection = {
  id: string;
  kind: VisionKind;
  label: string;
  box: VisionBox;
  confidence: number | null;
  uncertain: boolean;
  reason: string;
  tip_rack_contents: TipRackContents;
  state: DetectionState;
  origin: DetectionOrigin;
  component_id: VisionComponentId | string | null;
};

export type VisionPresenceValue = 'present' | 'not_observed' | 'uncertain';

export type VisionImageInfo = {
  width: number;
  height: number;
  sha256: string;
  url: string;
};

export type VisionUsage = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
};

export type VisionResult = {
  observation_version: number;
  image: VisionImageInfo;
  model: string;
  usage: VisionUsage;
  image_quality: 'clear' | 'uncertain' | 'unusable';
  coverage: 'complete' | 'partial' | 'uncertain';
  summary: string;
  warnings: string[];
  detections: VisionDetection[];
  scene_reviewed: boolean;
  review_required: boolean;
  presence: {
    tubes: VisionPresenceValue;
    pipette_tips: VisionPresenceValue;
  };
};

export type VisionJobStatus = 'queued' | 'running' | 'ready' | 'failed';

export type VisionJob = {
  id: string;
  project_id: string;
  project_revision: number;
  status: VisionJobStatus;
  stage: string;
  error: string | null;
  result: VisionResult | null;
};

export type ReviewAction = 'accept' | 'reject';

export type ReviewDecision = {
  id: string;
  action: ReviewAction;
  tip_rack_contents?: TipRackContents;
  kind?: VisionKind;
  label?: string;
  box?: VisionBox;
  component_id?: VisionComponentId | string | null;
};

export type ReviewAddition = {
  tip_rack_contents?: TipRackContents;
  kind: VisionKind;
  label: string;
  box: VisionBox;
  component_id: VisionComponentId | string | null;
};
