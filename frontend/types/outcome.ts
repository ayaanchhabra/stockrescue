export type OutcomeItemIn = {
  product_id: string;
  units_sold: number;
  actual_selling_price: number;
  unit_cost: number;
};

export type OutcomeIn = {
  is_simulated: boolean;
  items: OutcomeItemIn[];
  additional_costs: number;
  target_units_sold: number;
  actual_days: number;
  baseline_units: number | null;
  baseline_days: number | null;
  notes: string | null;
};

export type OutcomeOut = {
  id: number;
  experiment_id: number;
  is_simulated: boolean;
  inputs: Record<string, unknown>;
  calculated: Record<string, unknown>;
  limitations: unknown[];
  notes: string | null;
  recorded_at: string;
};
