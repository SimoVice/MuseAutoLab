export type GeometryPrimitive = {
  id: string;
  kind: 'box' | 'cylinder' | 'frustum' | 'tube' | 'plate';
  position: [number, number, number];
  size: [number, number, number];
  appearance: string;
  axis?: 'x' | 'y' | 'z';
  rotation_y_deg?: number;
  radius_top_mm?: number;
  radius_bottom_mm?: number;
  inner_radius_mm?: number;
  holes?: { x_mm: number; z_mm: number; radius_mm: number }[];
};

export type ComponentGeometry = {
  schema_version: '1';
  primitives: GeometryPrimitive[];
};

export type Component = {
  id: string;
  kind: string;
  label: string;
  position: [number, number, number];
  size: [number, number, number];
  geometry?: ComponentGeometry;
  reference_geometry?: Record<string, unknown>;
  foundation_asset_id?: string;
};

export type DesignReference = {
  id: string; title: string; kind: string; publisher: string; url: string;
  revision: string; license: string; license_url: string | null; checked_on: string;
  body_size_app_mm?: [number, number, number]; facts: string[]; use: string; limits: string;
};
export type SourceBasis = {
  schema_version: string; checked_on: string; architecture: string; references: DesignReference[];
  bindings: { component_id: string; primitive_id?: string; basis: string; reference_id: string | null; detail: string }[];
};

export type InspectionFrame = {
  time_s: number;
  components: Component[];
  joint_angles_deg: { shoulder: number; elbow: number };
  camera_mm: [number, number, number];
  target_mm: [number, number, number];
};

export type InspectionExtension = {
  schema_version: '1';
  proposal: { schema_version: '1'; link_lengths_mm: [number, number]; mast_height_mm: number; rationale: string; assumptions: string[] };
  attachment: { parent_component_id: string; anchor_mm: [number, number, number]; concept_only: boolean; fasteners: string; loads: string };
  component_ids: string[];
  components: Component[];
  pose_frames: InspectionFrame[];
  bounds: { min_mm: [number, number, number]; max_mm: [number, number, number] };
  assembly_bounds: { min_mm: [number, number, number]; max_mm: [number, number, number] };
  provenance?: Record<string, unknown>;
  checks: { id: string; passed: boolean; detail: string }[];
  limitations: string[];
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
  checked_on: string | null;
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
  lineage_id?: string;
  restored_from?: { project_id: string; revision: number; saved_at: string };
  revision: number;
  labware_brief?: LabwareBrief | null;
  labware_rack?: LabwareRack | null;
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
    foundation?: { id: string; bed_drop_mm: number; bbox_mm: [number, number, number] };
    assembly_bounds?: { min_mm: [number, number, number]; max_mm: [number, number, number] };
    platform?: { id: string; label: string; geometry_scope: string };
  };
  plan?: PreparationPlan | null;
  engineering_design?: EngineeringDesign | null;
  inspection_extension?: InspectionExtension | null;
  design_basis?: SourceBasis;
  rebuild_notice?: string;
  engineering?: { schema_version: string; selected_platform_id: string | null;
    selection_source: string | null; requirements: Record<string, string | null>;
    options: { platform_id: string; reason: string; tradeoffs: string[] }[] };
  engineering_guidance?: { status: string; platform_id?: string; message: string;
    steps: { title: string; url: string; detail: string }[] };
};

export type RackSpec = {
  body_diameter_max_mm: number; rim_diameter_min_mm: number; cap_diameter_max_mm: number;
  below_rim_height_mm: number; count: number; columns: number;
  pitch_mm?: number; radial_clearance_mm?: number; max_width_mm?: number; max_depth_mm?: number; max_height_mm?: number;
};
export type RackFieldSource = { literal: string; value: number; recorded_at_revision: number };
export type LabwareBrief = {
  schema_version: number; kind: 'rim_supported_tube_rack'; target_component_id: string;
  spec: Partial<RackSpec>; sources: Record<string, RackFieldSource>; missing_fields: string[];
  status: 'needs_dimensions' | 'ready';
};
export type LabwareRack = {
  schema_version: number; kind: 'rim_supported_tube_rack'; target_component_id: string;
  spec: RackSpec; assumptions: { radial_clearance_mm: number; bore_diametral_tolerance_plus_minus_mm: number;
    minimum_rim_bearing_mm: number; top_thickness_mm: number; end_wall_mm: number;
    bottom_clearance_mm: number; process: string; tube_envelope: string; unverified: string[] };
  size_mm: [number, number, number]; geometry: ComponentGeometry;
  derived: { rows: number; columns: number; count: number; pitch_mm: number; bore_diameter_mm: number;
    bore_max_assumed_mm: number; rim_land_min_assumed_mm: number; tip_clearance_mm: number;
    top_thickness_mm: number; end_wall_mm: number; closed_cap_envelope_size_mm?: [number, number] };
  metrics: { body_radial_clearance_min_assumed_mm: number; rim_land_min_assumed_mm: number;
    closed_cap_gap_mm: number; hole_web_min_assumed_mm: number };
  checks: DesignCheck[];
  provenance: { basis: string; sources: Record<string, RackFieldSource>; compiler: string;
    source_project_revision: number; previous_size_mm?: [number, number, number] };
};

export type ConversationEntry = { id: number; role: 'assistant' | 'user'; text: string; references?: DesignReference[] };

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

export type DesignCheck = { id: string; label: string; passed: boolean; detail: string };

export type DesignUsage = { model?: string; input_tokens?: number; output_tokens?: number };

export type DesignAttempt = {
  number: number;
  proposal: Record<string, unknown> | null;
  checks: DesignCheck[];
  usage: DesignUsage | null;
  error?: string;
};

export type DesignRun = {
  id: string;
  source_revision: number;
  status: 'accepted' | 'rejected' | 'failed';
  model: string;
  instruction: string;
  attempts: DesignAttempt[];
  message: string;
};

export type LayoutPlacement = { component_id: string; x_mm: number; z_mm: number };

export type LayoutProposal = {
  schema_version: '1';
  deck_width_mm: number;
  deck_depth_mm: number;
  bed_drop_mm?: number;
  slot_assignments?: { component_id: string; slot_id: string }[];
  placements: LayoutPlacement[];
  rationale: string;
  assumptions: string[];
};

export type EngineeringDesign = {
  schema_version: '1';
  proposal: LayoutProposal;
  provenance: Record<string, unknown>;
};

export type ProjectResponse = { project: Project; assistant_message?: string; recommendations?: { reference: DesignReference; reason: string }[] };

export type DesignResponse = { project: Project; design_run: DesignRun; assistant_message: string };

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
  scope?: 'liquid_preparation_only';
  inspection_extension_excluded?: boolean;
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

export type ProcurementRow = {
  group_id: string; component_ids: string[]; selected_id: string; label: string;
  sku: string | null; quantity: number; pack_size: number | null; pack_count: number | null;
  unit_price: number | null; line_total: number | null; currency: 'USD'; pack_price?: number | null;
  last_known_line_total?: number | null; compatibility_note?: string; is_expired?: boolean;
  is_candidate?: boolean; parent_group_id?: string; source_bom_url?: string; source_bom_row?: string;
  source_project_revision?: string; variant_id?: string; variant_title?: string;
  status: 'priced' | 'unavailable' | 'missing' | 'quote_needed' | 'unsupported';
  freshness: 'fresh' | 'stale' | 'unverified'; availability: string;
  price_source_url: string | null; availability_source_url: string | null;
  fetched_at: string | null; last_known_price: number | null; last_known_fetched_at: string | null; issue: string | null;
};

export type ProcurementReport = {
  report_id: string; project_id: string; project_revision: number; market: 'US'; currency: 'USD';
  fetched_at: string; expires_at: string; rows: ProcurementRow[];
  coverage: { row_count: number; fresh_priced_count: number; stale_priced_count: number; unpriced_count: number };
  known_partial_subtotal: number; stale_last_known_subtotal: number; exclusions: string[];
};

export type ProcurementResponse = {
  report: ProcurementReport | null; state: 'not_refreshed' | 'stale_revision' | 'current';
};

export type InstructionSource = { id: string; title: string; url: string; checked_on: string; scope: string; revision?: string };
export type InstructionPart = {
  component_id: string; label: string; quantity: number; position_mm: [number, number, number]; size_mm: [number, number, number];
  slot_id: string | null; geometry_basis: string; reference_id: string | null;
  selected_variants: { group_id: string; variant_id: string; label: string; quantity: number; source_url: string | null }[];
};
export type InstructionStep = {
  id: string; title: string; status: 'ready' | 'reference_only' | 'needs_design'; component_ids: string[];
  parts: InstructionPart[]; instructions: string[]; prerequisites: string[]; checks: string[];
  required_tools: { label: string; source_id: string }[]; required_materials: { label: string; source_id: string }[];
  sources: InstructionSource[]; engineering_tasks: { id: string; action: string; acceptance_criteria: string | string[] }[];
};
export type InstructionGuide = {
  schema_version: number; project_id: string; project_revision: number; revision: number;
  platform: string; status: 'review_ready' | 'needs_design'; procurement_report_id: string | null;
  parts: InstructionPart[]; steps: InstructionStep[]; sources: InstructionSource[];
  summary: { ready_steps: number; reference_steps: number; needs_design_steps: number; total_steps: number };
  coordinate_system: string;
};
