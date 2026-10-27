export type Component = {
  id: string;
  kind: string;
  label: string;
  position: [number, number, number];
  size: [number, number, number];
};

export type Project = {
  id: string;
  revision: number;
  status: 'draft' | 'confirmed';
  summary: {
    stock_concentration: string | null;
    target_concentrations: string | null;
    final_volume: string | null;
    equipment: string | null;
    workspace_width_mm: number | null;
  };
  design: {
    footprint: { width_mm: number; depth_mm: number; height_mm: number };
    components: Component[];
    constraint_status: 'unconstrained' | 'fits' | 'infeasible';
    estimated_cost: { amount: number | null; currency: string };
  };
};

export type ConversationEntry = { id: number; role: 'assistant' | 'user'; text: string };

export type ProjectResponse = { project: Project; assistant_message?: string };
