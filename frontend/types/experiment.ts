export type ExperimentStatus =
  | "proposed"
  | "approved"
  | "running"
  | "completed"
  | "rejected"
  | "cancelled";

export type Experiment = {
  id: number;
  plan_id: number | null;
  product_pk: number;
  strategy_type: string;
  title: string;
  proposed_action: string;
  bundle_product_pks: number[];
  proposed_price: number;
  estimated_cost: number;
  calculated_margin_pct: number;
  qloo_evidence_ids: number[];
  status: ExperimentStatus;
  start_date: string | null;
  end_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};
