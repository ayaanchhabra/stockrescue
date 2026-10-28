export type QlooStatus = "strong_match" | "ambiguous" | "no_match" | "error";
export type StrategyType = "bundle" | "reposition" | "promotion";
export type EvidenceSource = "qloo" | "retailer_data" | "calculation" | "llm" | "assumption";

export type Evidence = {
  source: EvidenceSource;
  note: string;
  entity_id: string | null;
  entity_name: string | null;
  entity_type: string | null;
  raw_ref: string | null;
};

export type Economics = {
  selling_price: number;
  unit_cost: number;
  profit_per_unit: number;
  margin_pct: number;
  discount_pct: number;
  estimated_experiment_cost: number;
  units_available: number;
  currency: string;
  assumptions_note: string;
};

export type RankReason = {
  feasibility: number;
  evidence: number;
  simplicity: number;
  cost: number;
  weights: Record<string, number>;
  weighted_total: number;
  explanation: string;
};

export type CandidateProduct = {
  product_id: string;
  product_name: string;
  match_kind: "exact" | "fuzzy" | "theme_only" | null;
  role: string;
};

export type Strategy = {
  rank: number;
  type: StrategyType;
  name: string;
  summary: string;
  products: CandidateProduct[];
  economics: Economics;
  evidence: Evidence[];
  assumptions: string[];
  risks: string[];
  operational_effort: string;
  test_plan: string;
  rank_reason: RankReason;
  llm_explanation: string | null;
  outcome_disclaimer: string;
};

export type RejectedOption = {
  type: StrategyType;
  name: string;
  reasons: string[];
};

export type RescuePlan = {
  product_id: string;
  product_name: string;
  generated_at: string;
  qloo_status: QlooStatus;
  qloo_note: string | null;
  strategies: Strategy[];
  rejected: RejectedOption[];
  constraints_snapshot: Record<string, unknown>;
  stages_completed: string[];
  stages_failed: Record<string, string>;
  limitations: string;
};
