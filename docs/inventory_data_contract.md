# StockRescue Inventory Data Contract

**Status:** Draft — pending integration confirmation
**Owner:** Person 4 — Data, QA and Deployment

## 1. Purpose

Define the CSV format for importing bookstore inventory into StockRescue.

The contract is based on the project requirements and the Product model
in `backend/app/models/entities.py`.

This document defines the proposed file format and data-validation rules.
It does not define or implement the inventory API, database import behavior,
or frontend interface.

## 2. CSV Columns

Required columns:

| CSV column | Database field | Type | Validation |
|---|---|---|---|
| `product_id` | `sku` | String | Required; maximum 64 characters |
| `product_name` | `product_name` | String | Required; maximum 300 characters |
| `category` | `category` | String | Required; maximum 100 characters |
| `quantity_in_stock` | `quantity_in_stock` | Integer | Required; must be >= 0 |
| `unit_cost` | `unit_cost` | Number | Required; must be >= 0 |
| `selling_price` | `selling_price` | Number | Required; must be > 0 |

Optional columns:

| CSV column | Database field | Type | Validation |
|---|---|---|---|
| `creator_or_brand` | `creator_or_brand` | String | Optional; maximum 200 characters |
| `product_description` | `product_description` | Text | Optional |
| `genre_or_subcategory` | `genre_or_subcategory` | String | Optional; maximum 100 characters |
| `units_sold_30d` | `units_sold_30d` | Integer | Optional; must be >= 0 when provided |
| `units_sold_60d` | `units_sold_60d` | Integer | Optional; must be >= 0 when provided |
| `units_sold_90d` | `units_sold_90d` | Integer | Optional; must be >= 0 when provided |
| `days_in_stock` | `days_in_stock` | Integer | Optional; must be >= 0 when provided |
| `publication_or_release_date` | `publication_or_release_date` | Date | Optional; proposed format `YYYY-MM-DD` |
| `seasonality` | `seasonality` | String | Optional |
| `minimum_acceptable_margin` | `minimum_acceptable_margin` | Number | Optional; interpretation and range pending confirmation |
| `maximum_discount_percentage` | `maximum_discount_percentage` | Number | Optional; interpretation and range pending confirmation |

## 3. File Format

- Use a comma-separated CSV file with a header row.
- Header names must match the names documented above.
- Keep `product_id` as text. Do not convert it to an integer; identifiers may
  contain letters or leading zeros.
- Numeric fields must contain valid numeric values, without currency symbols
  or thousands separators.
- Dates should use the proposed ISO format `YYYY-MM-DD`.
- Blank optional values represent missing information.
- Blank required values must be reported as validation errors.
- The importer must report invalid rows clearly rather than silently changing
  their values.

## 4. Missing Sales Data

Missing sales history must remain missing.

For example, a blank `units_sold_30d` value must not be converted to `0`.
A recorded zero means that zero sales were reported; a blank means the
sales figure was not provided.

The slow-moving inventory logic must not interpret missing sales data as
proof that a product is unpopular.

## 5. Financial and Quantity Validation

- `quantity_in_stock` must be a non-negative integer.
- Provided sales quantities and `days_in_stock` must be non-negative integers.
- `unit_cost` must be non-negative.
- `selling_price` must be greater than zero.
- Invalid numeric values must be rejected or reported, not silently coerced.
- Monetary calculations should follow the backend's documented rounding
  convention.

The ranges and calculation rules for minimum acceptable margin and maximum
discount percentage remain pending confirmation from the team.

## 6. Identifier and Import Behavior — Pending Confirmation

The CSV `product_id` maps to the database `products.sku` field.

StockRescue's backend APIs use the internal integer `Product.id`, not the
CSV SKU. These identifiers must not be confused.

The following decisions must be confirmed before implementing the importer:

- Whether duplicate SKUs within one CSV are rejected.
- What happens when an imported SKU already exists in the database.
- Whether `retailer_id` is supplied separately or uses the model's default.
- Whether a CSV import is all-or-nothing or permits valid rows when others fail.

Until these decisions are confirmed, this contract does not prescribe
insert, update, or upsert behavior.

## 7. Qloo Matching

Qloo resolution is handled separately from inventory CSV validation.

An uploaded product must not be marked as successfully resolved merely
because it exists in the inventory. Matching status and evidence must come
from the backend's Qloo resolution workflow.

## 8. Integration Dependencies

- **Person 1:** Confirm the inventory endpoint ownership, import behavior,
  and any additional schema or API constraints.
- **Person 2:** Confirm slow-moving thresholds and margin/discount rules.
- **Person 3:** Confirm the frontend's expected CSV fields and import response
  format, and clarify ownership of the Inventory page.

The final sample dataset should follow the agreed format and incorporate
books verified for Qloo when that information becomes available.
