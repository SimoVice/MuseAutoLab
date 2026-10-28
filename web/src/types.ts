export type Component = {
  id: string;
  kind: string;
  label: string;
  position: [number, number, number];
  size: [number, number, number];
};

export type PlanStep = {
  id: string;
  target: string;
  stock_volume_ul: number;
  diluent_volume_ul: number;
  total_volume_ul: number;
};

export type PlanStatus = 'incomplete' | 'invalid' | 'ready';

export type PreparationPlan = {
  status: PlanStatus;
  message: string;
  stock: string | null;
  final_volume_ul: number | null;
  steps: PlanStep[];
  assumptions: string[];
};

export type SourcingPriceKind = 'listed' | 'starting_at' | 'unpriced';

export type SourcingOption = {
  id: string;
  label: string;
  supplier: string;
  sku: string | null;
  unit_price: number | null;
  price_kind: SourcingPriceKind;
  source_url: string | null;
  checked_on: string;
  availability: string;
  pros: string[];
  cons: string[];
  compatibility_note: string;
};

export type SourcingGroup = {
  id: string;
  label: string;
  component_ids: string[];
  quantity: number;
  selected_id: string;
  options: SourcingOption[];
};

export type Sourcing = {
  checked_on: string;
  currency: string;
  subtotal: number;
  is_lower_bound: boolean;
  incomplete: boolean;
  unpriced_count: number;
  groups: SourcingGroup[];
  exclusions: string[];
};

export type CoolingTargetSource = 'assumed' | 'user';

export type DesignCooling = {
  enabled: boolean;
  target_c: number;
  target_source: CoolingTargetSource;
  variant_id: string;
  transfer_mode: 'manual';
  validation: 'unverified';
  notes: string[];
};

export type WorkflowKind = 'unclassified' | 'general' | 'liquid_preparation';

export type WorkflowStatus = 'discovery' | 'planning' | 'supported_concept';

export type ProjectBrief = {
  objective: string | null;
  process: string | null;
  materials: string | null;
  equipment: string | null;
  constraints: string | null;
};

export type ProjectWorkflow = {
  kind: WorkflowKind;
  label: string;
  status: WorkflowStatus;
  design_available: boolean;
  parameters_started: boolean;
};

export type Project = {
  id: string;
  revision: number;
  status: 'draft' | 'confirmed';
  brief: ProjectBrief;
  workflow: ProjectWorkflow;
  summary: {
    stock_concentration: string | null;
    target_concentrations: string | null;
    final_volume: string | null;
    equipment: string | null;
    workspace_width_mm: number | null;
    cooling_enabled: boolean;
    cooling_target_c: number | null;
  };
  selections: Record<string, string>;
  sourcing: Sourcing;
  design: {
    footprint: { width_mm: number; depth_mm: number; height_mm: number };
    components: Component[];
    constraint_status: 'unconstrained' | 'fits' | 'infeasible';
    estimated_cost: { amount: number | null; currency: string };
    cooling: DesignCooling;
  };
  plan?: PreparationPlan | null;
};

export type ConversationEntry = { id: number; role: 'assistant' | 'user'; text: string };

export type AssemblyStep = {
  id: string;
  title: string;
  component_ids: string[];
  instructions: string[];
  checks: string[];
  requires_design: boolean;
};

export type ExportFileEntry = {
  name: string;
  size: number;
  media_type: string;
  sha256: string;
};

export type ExportStatus = 'queued' | 'running' | 'ready' | 'failed' | 'stale';

export type ExportJob = {
  id: string;
  project_id: string;
  revision: number;
  status: ExportStatus;
  stage: string;
  completed_stages: number;
  total_stages: number;
  error: string | null;
  files: ExportFileEntry[];
  assembly_steps: AssemblyStep[];
  download_url: string | null;
};

export type ProjectResponse = { project: Project; assistant_message?: string };

export type PhysicsScenario = 'nominal' | 'blocked_path';

export type PhysicsFrame = {
  time_s: number;
  carriage_mm: [number, number, number];
  pipette_mm: [number, number, number];
  tip_mm: [number, number, number];
  target_mm: [number, number, number];
  phase: string;
  station_id: string | null;
  transfer_id: string | null;
};

export type PhysicsWaypoint = {
  time_s: number;
  carriage_mm: [number, number, number];
  phase: string;
  station_id: string | null;
  transfer_id: string | null;
  volume_ul: number | null;
};

export type PhysicsMetrics = {
  max_tracking_error_mm: number;
  final_tracking_error_mm: number;
  peak_actuator_force_n: [number, number, number];
  max_contact_force_n: number;
  contact_count: number;
  completed_waypoints: number;
  total_waypoints: number;
};

export type PhysicsContact = { time_s: number; component_id: string; force_n: number };

export type PhysicsCheck = { id: string; label: string; passed: boolean; observed: number | string; limit: number | string };

export type PhysicsObstacle = { id: string; label: string; position_mm: [number, number, number]; size_mm: [number, number, number] };

export type PhysicsResult = {
  schema_version: 1;
  project_id: string;
  revision: number;
  scenario: PhysicsScenario;
  engine: string;
  engine_version: string;
  input_sha256: string;
  status: 'passed' | 'blocked' | 'failed';
  duration_s: number;
  timestep_s: number;
  frames: PhysicsFrame[];
  waypoints: PhysicsWaypoint[];
  metrics: PhysicsMetrics;
  contacts: PhysicsContact[];
  checks: PhysicsCheck[];
  assumptions: string[];
  limitations: string[];
  model_xml: string;
  obstacles: PhysicsObstacle[];
};

export type SimulationJobStatus = 'queued' | 'running' | 'ready' | 'failed';

export type SimulationJob = {
  id: string;
  project_id: string;
  revision: number;
  scenario: PhysicsScenario;
  status: SimulationJobStatus;
  stage: string;
  completed_steps: number;
  total_steps: number;
  error: string | null;
  result_url: string | null;
  summary: PhysicsMetrics | null;
};

export type PhysicsView = { result: PhysicsResult; time_s: number };

export type ConfigurationUpdate = {
  cooling_enabled?: boolean;
  cooling_target_c?: number;
  selections?: Record<string, string>;
};
