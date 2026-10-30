export type RetailerSettings = {
  currency: "INR";
  constraints: {
    min_margin_pct: number;
    max_discount_pct: number;
    max_campaign_budget: number;
    restricted_product_ids: string[];
  };
  strategy: {
    test_units: number;
    test_days: number;
    bundle_discount_pct: number;
    promo_discount_pct: number;
    min_promo_discount_pct: number;
    max_bundle_attempts: number;
    max_display_titles: number;
    bundle_campaign_cost: number;
    reposition_campaign_cost: number;
    promotion_campaign_cost: number;
  };
  ranking: {
    weights: { feasibility: number; evidence: number; simplicity: number; cost: number };
    discount_last: boolean;
    headroom_full_pts: number;
    stock_cover_full_multiple: number;
    ambiguous_evidence_cap: number;
    max_results: number;
    close_score_gap: number;
  };
  slow_moving: {
    no_recent_sales_min_stock_days: number;
    aged_stock_days: number;
    low_sales_cover_days: number;
  };
};
