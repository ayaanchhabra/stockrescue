# StockRescue Inventory Data Contract

**Status:** Draft — business rules incorporated; integration details pending
**Owner:** Person 4 — Data, QA and Deployment

## 1. Purpose

Define the CSV format and validation behavior for importing bookstore
inventory into StockRescue.

The contract follows the Product model in
`backend/app/models/entities.py` and the business rules in
`docs/business_rules.md` on `origin/main`.

## 2. CSV Columns

### Required columns

| CSV column | Database field | Type | Validation |
|---|---|---|---|
| `product_id` | `sku` | String | Required; maximum 64 characters |
| `product_name` | `product_name` | String | Required; maximum 300 characters |
| `category` | `category` | String | Required; maximum 100 characters |
| `quantity_in_stock` | `quantity_in_stock` | Integer | Whole number >= 0 |
| `unit_cost` | `unit_cost` | Number | >= 0 |
| `selling_price` | `selling_price` | Number | > 0 |

### Optional columns

| CSV column | Database field | Type | Validation |
|---|---|---|---|
| `creator_or_brand` | `creator_or_brand` | String | Maximum 200 characters |
| `product_description` | `product_description` | Text | Optional |
| `genre_or_subcategory` | `genre_or_subcategory` | String | Maximum 100 characters |
| `units_sold_30d` | `units_sold_30d` | Integer | Whole number >= 0 |
| `units_sold_60d` | `units_sold_60d` | Integer | Whole number >= 0 |
| `units_sold_90d` | `units_sold_90d` | Integer | Whole number >= 0 |
| `days_in_stock` | `days_in_stock` | Integer | Whole number >= 0 |
| `publication_or_release_date` | `publication_or_release_date` | Date | Proposed format `YYYY-MM-DD` |
| `seasonality` | `seasonality` | String | Optional |
| `minimum_acceptable_margin` | `minimum_acceptable_margin` | Number | 0 <= value < 100 |
| `maximum_discount_percentage` | `maximum_discount_percentage` | Number | 0 <= value <= 100 |

## 3. CSV Format and Upload Limits

- Accept CSV files with a header row.
- Header names must match the documented field names.
- Keep `product_id` as text; it may contain letters or leading zeros.
- Numeric fields must not contain currency symbols or thousands separators.
- Dates use `YYYY-MM-DD`.
- Maximum file size: 2 MB.
- Maximum upload size by row count: 2,000 rows.
- Missing required columns, an unsupported file type, or exceeding either
  limit must reject the entire upload.

## 4. Identifiers and Import Behavior

- CSV `product_id` maps to the database `products.sku` field.
- Backend APIs use internal integer `Product.id`, not the CSV SKU.
- The database enforces uniqueness of `(retailer_id, sku)`.
- Use the retailer identifier constant `demo` for the MVP; do not require
  an API parameter for it.
- If an SKU already exists for the same retailer, update that existing
  Product row. Do not delete and recreate it, because experiments and
  Qloo mappings reference `Product.id`.
- If the same `product_id` appears more than once in a CSV, report the
  duplicate row numbers. The first occurrence may be processed; later
  duplicate occurrences must be skipped and reported as errors.
- Preview must not write to the database. It must identify each row as
  new, will update, invalid, or otherwise requiring attention.
- Import writes valid rows and skips invalid rows in one database
  transaction. A failure during the transaction must not leave a
  partially imported file.
- Row-level errors must not prevent valid rows from being imported.
- File-level errors reject the entire upload.

### Optional blanks during updates — team rules resolved

For new products:
- Blank optional cells are stored as `NULL`.

For existing products:
- Blank optional cells ordinarily preserve the current value.
- Non-blank optional cells update the corresponding field.
- The existing Product row must be updated in place so its internal
  `Product.id`, Qloo mapping, and experiment references remain stable.

Sales-history snapshot exception:
- The snapshot comprises `units_sold_30d`, `units_sold_60d`,
  `units_sold_90d`, and `days_in_stock`.
- If a row supplies any non-blank value in this group, replace all four
  fields together. Blank cells within this group become `NULL`.
- If none of the four fields is supplied, retain all four existing values.
- This is the explicit exception to the general rule that values cannot
  be cleared through CSV. Other values must be cleared manually in the app.

Required fields can never be blank. The frontend's final preview/import
response format remains pending confirmation from Person 3.

## 5. Validation and Error Reporting

For each invalid or skipped row, report:

- CSV row number
- Field name
- Invalid value
- Plain-English reason and suggested correction

Blank required fields, invalid numeric values, negative quantities,
negative costs, non-positive selling prices, invalid dates, and invalid
sales or financial values must be reported.

### Sales history

`units_sold_30d`, `units_sold_60d`, and `units_sold_90d` are cumulative
sales totals over the respective periods, counted back from the upload date.

- Blank values mean unknown, not zero.
- Decimals, text, and negative sales quantities are errors.
- If `units_sold_60d` is less than `units_sold_30d`, warn but allow the row.
- If `units_sold_90d` is less than `units_sold_60d`, warn but allow the row.

### Days in stock

- Represents the non-negative whole number of days current stock has been
  on hand.
- Blank means unknown.
- Reject negative values, decimals, and text.
- Do not judge a product against a sales window longer than its known
  time in stock.

### Financial fields

`minimum_acceptable_margin`:
- Represents gross margin percentage, not markup.
- Current margin = `(selling_price - unit_cost) / selling_price * 100`.
- Valid range: 0 inclusive to 100 exclusive.
- Blank uses the decision engine's store-wide default of 15%.
- The decision engine uses the stricter (higher) of the product minimum
  and store-wide minimum.
- If current margin is already below the product's own minimum, warn
  that the product cannot be discounted.

`maximum_discount_percentage`:
- Represents the maximum discount against normal selling price.
- For bundles, calculate the discount against the sum of normal item prices.
- Valid range: 0 through 100 inclusive.
- Blank uses the decision engine's store-wide default of 25%.
- A typed zero means the product must not be discounted.
- The decision engine uses the stricter (lower) of the product maximum
  and store-wide maximum.

Also warn if `selling_price` is below `unit_cost`, because this indicates
a loss on each sale before other costs.

## 6. Slow-Moving Inventory Rules

The dashboard must use transparent, named rules and show the values
behind any triggered rule.

| Rule | Condition |
|---|---|
| No recent sales | `units_sold_30d` is 0 and `days_in_stock` is at least 30 or unknown |
| Aged stock | `days_in_stock` is at least 90 |
| Low sales velocity | `units_sold_30d` > 0 and stock cover exceeds 180 days |

Stock cover in days:

`quantity_in_stock / (units_sold_30d / 30)`

- A product needs attention if at least one rule fires.
- If sales data and `days_in_stock` are both missing, label it
  `Not enough data to assess`. Do not classify it as unpopular.
- Do not judge stock using a sales window longer than the known time in stock.
- Rank flagged products by inventory cost tied up, highest first:

  `quantity_in_stock * unit_cost`

Default configurable thresholds are 30 days, 90 days, and 180 days of cover.
These are team-chosen defaults, not industry facts.

Dashboard metrics must state their calculation and period.

## 7. Decision-Engine Field Mapping

Map CSV/database names to decision-engine names in one place, where a
`ProductRef` is constructed.

| CSV / database field | Decision-engine field |
|---|---|
| `minimum_acceptable_margin` | `min_margin_pct` |
| `maximum_discount_percentage` | `max_discount_pct` |
| `product_id` / `sku` | `product_id` |
| `quantity_in_stock` | `quantity` |

Do not duplicate these conversions throughout the codebase.

## 8. Accounting Assumptions

- Gross profit = selling price - unit cost.
- Gross profit is before rent, labour, packaging, and platform fees.
- Subtract direct campaign costs only where the experiment calculation
  specifies them.
- Revenue must not be treated as profit.

## 9. Integration Dependencies

- Person 1 owns the core backend and confirmed that Person 4 owns the
  inventory API and dashboard metrics.
- Person 2 owns the business rules documented above.
- Person 3's confirmation of frontend ownership, expected fields, and
  preview/import response formats is pending.
- The final sample dataset must contain realistic bookstore inventory.
  Qloo-verified titles remain pending Person 1's API-key verification.

The exact endpoint paths and response schemas must be aligned with the
frontend before the shared interface is considered final.
