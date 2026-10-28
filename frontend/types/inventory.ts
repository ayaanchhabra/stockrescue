export type RowIssue = {
  row_number: number;
  field: string;
  value: string;
  message: string;
  severity: "warning" | "error";
};

export type ImportRow = {
  row_number: number;
  product_id: string;
  action: string;
  errors: RowIssue[];
  warnings: RowIssue[];
};

export type ImportResult = {
  created_count: number;
  updated_count: number;
  skipped_count: number;
  imported_count: number;
  rows: ImportRow[];
};
