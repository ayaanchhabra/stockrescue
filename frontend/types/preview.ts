import type { RowIssue } from "@/types/inventory";

export type PreviewRow = {
  row_number: number;
  product_id: string;
  action: string;
  values: Record<string, string | number | null>;
  errors: RowIssue[];
  warnings: RowIssue[];
};

export type PreviewResult = {
  filename: string;
  total_rows: number;
  new_count: number;
  update_count: number;
  invalid_count: number;
  warning_count: number;
  rows: PreviewRow[];
};
