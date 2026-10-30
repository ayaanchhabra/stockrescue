export type FlaggedProduct = {
  product_pk: number; // internal id, use this for /rescue/{pk}
  sku: string;
  product_name: string;
  category: string;
  quantity_in_stock: number;
  unit_cost: number;
  inventory_cost_tied_up: number;
  status: string;
  rules_triggered: string[];
  explanations: string[];
  stock_cover_days: number | null;
};

export type Dashboard = {
  total_products: number;
  total_inventory_units: number;
  potential_retail_value: number;
  needs_attention_count: number;
  not_enough_data_count: number;
  total_inventory_cost_tied_up: number;
  flagged_inventory_cost_tied_up: number;
  rule_counts: Record<string, number>;
  thresholds: Record<string, number>;
  rule_descriptions: Record<string, string>;
  metric_descriptions: Record<string, string>;
  products_needing_attention: FlaggedProduct[];
};
