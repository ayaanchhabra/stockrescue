# StockRescue Business Rules

All thresholds below are **defaults chosen by the team**. They live in configuration and can be changed. They are not industry facts.

## 1. General rules for optional fields

- A **blank** optional field means **unknown**. It is stored as `NULL`, never as `0`.
- Only a typed `0` means "recorded zero".
- Never invent a missing sales number, margin or discount.
- A product with missing sales data is **"not enough data"**. It is never labelled unpopular.
- Importer errors must give the row number, the column, the bad value and a plain-English fix, so the user can correct the row in the preview.

## Blanks when updating an existing product (CSV re-upload)

- New product: a blank optional cell is stored as NULL.
- Existing product: a blank optional cell keeps the current value. Only non-blank cells change the row.
- Required fields can never be blank (row error).
- Exception: `units_sold_30d`, `units_sold_60d`, `units_sold_90d` and `days_in_stock` form one
  time-sensitive snapshot. If a row provides any of them, all four are replaced together and
  blanks among them become NULL. If a row provides none, all four keep their current values.
- A value can't be cleared through CSV in the MVP; edit it manually in the app.

## 2. Sales history fields

Fields: `units_sold_30d`, `units_sold_60d`, `units_sold_90d`.

**Meaning:** units sold in the last 30, 60 and 90 days, counted back from the upload date. The windows are **cumulative**: the 90-day figure includes the 60-day sales, and the 60-day figure includes the 30-day sales.

| Check | Result |
|---|---|
| Not a whole number (decimal, text) | Reject the row |
| Negative number | Reject the row |
| Blank | Store `NULL` (unknown) |
| `units_sold_60d` < `units_sold_30d`, or `units_sold_90d` < `units_sold_60d` | Warn, let the user correct it |

## 3. `days_in_stock`

- A non-negative whole number of days the current stock has been on hand. Blank means unknown.
- Reject negative numbers, decimals and text.
- If `days_in_stock` is shorter than a sales window (for example 20 days against a 30-day window), the product is too new to judge by that window. Do not flag it as slow because of that window.

## 4. Slow-moving inventory

Slow-moving status comes from **transparent, named rules**, not an AI label. The dashboard must show which rules fired and the numbers behind them.

| Rule | Triggers when |
|---|---|
| No recent sales | `units_sold_30d` is recorded as `0` and `days_in_stock` is at least 30 (or unknown) |
| Aged stock | `days_in_stock` is at least 90 |
| Low sales velocity | `units_sold_30d` is above 0 and stock cover is more than 180 days |

Stock cover (days) = `quantity_in_stock` / (`units_sold_30d` / 30).

- A product **needs attention** if at least one rule fires.
- If a product has no sales data and no `days_in_stock`, its status is **"Not enough data to assess"**. Do not classify it.
- Rank flagged products by **inventory cost tied up** (`quantity_in_stock` x `unit_cost`), highest first. This is a sort order, not a rule.
- Every dashboard metric states its calculation and period, for example: "Slow-moving = no recorded sales in 30 days, or in stock for 90+ days".

Default thresholds (configurable): 30 days, 90 days, 180 days of cover.

## 5. `minimum_acceptable_margin` (optional, per product)

- A percentage from 0 up to but **not including** 100. `15` means 15%, not `0.15`.
- It is **gross margin**: (`selling_price` - `unit_cost`) / `selling_price` x 100. It is **not** markup.
- It is the lowest margin any strategy involving this product may produce.
- **Blank = use the store-wide default (15%).** Blank is not 0.
- The decision engine uses the **stricter** (higher) of the product value and the store-wide value.

| Check | Result |
|---|---|
| Below 0, or 100 or more | Reject the row |
| Not a number | Reject the row |
| Product's current margin is already below its own minimum | Warn: this product cannot be discounted at all |

## 6. `maximum_discount_percentage` (optional, per product)

- A percentage from 0 to 100. `20` means 20% off the normal `selling_price`.
- It is the largest discount any strategy may show a customer on this product. For a bundle, the discount is measured against the sum of the items' normal prices.
- **Blank = use the store-wide default (25%).** A typed `0` means "never discount this product".
- The decision engine uses the **stricter** (lower) of the product value and the store-wide value.

| Check | Result |
|---|---|
| Below 0 or above 100 | Reject the row |
| Not a number | Reject the row |

## 7. Required fields (for reference)

`product_id`, `product_name`, `category`, `quantity_in_stock`, `unit_cost`, `selling_price`.

- `quantity_in_stock`: whole number, 0 or more.
- `unit_cost`: number, 0 or more.
- `selling_price`: number, **above 0**.
- Warn when `selling_price` is below `unit_cost` (a loss on every sale).
- Reject duplicate `product_id` values within one upload.

## 8. Naming map

| CSV / database column | Decision-engine field |
|---|---|
| `minimum_acceptable_margin` | `min_margin_pct` |
| `maximum_discount_percentage` | `max_discount_pct` |
| `product_id` (CSV) / `sku` (database) | `product_id` |
| `quantity_in_stock` | `quantity` |

Map these names in **one place** (the code that builds a `ProductRef`), not throughout the codebase.

## 9. What the database does and does not enforce

The database enforces: `quantity_in_stock >= 0`, `unit_cost >= 0`, `selling_price > 0`, unique SKU per retailer.

It does **not** enforce the margin range, the discount range or sales-window consistency. The **CSV importer must validate those**.

## 10. Accounting assumptions

- Gross profit = selling price - unit cost, before rent, labour, packaging and platform fees.
- Direct campaign costs are subtracted only where an experiment calculation says so.
- Revenue is never profit.
