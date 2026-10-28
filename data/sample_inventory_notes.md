# Sample bookstore inventory — data notes

## Purpose
This is synthetic demo data for StockRescue QA and demonstrations. Quantities,
costs, selling prices, sales history and days-in-stock values are invented for
testing; they are not real retailer records, sales forecasts or recommendations.
Price values are assumed to be INR, with no currency symbol stored in the CSV.

## Qloo verification status from the team guide dated 2026-10-27
The guide explicitly reports strong title matches for:
- The God of Small Things
- Norwegian Wood
- Kafka on the Shore
- The Alchemist
- Sapiens
- 1984
- The White Tiger
- Midnight's Children
- The Kite Runner
- Atomic Habits

The Great Gatsby is the intentionally ambiguous human-choice demo row.
Pride and Prejudice is excluded because the team's guide reported poor related-book insights.

Other books in the dataset were selected from the related-title clusters in the
team guide. Their individual Qloo resolve results and insight quality have NOT
all been verified. Do not claim otherwise.

## Scenarios represented
- Slow-moving / aged stock with related titles available
- Related titles that are out of stock, constraining bundles
- Missing sales snapshots: blank values mean unknown, not zero
- Margin constraints: Enlightenment Now and Behave have explicit product-level
  minimum margins and discount caps for testing
- Ambiguous title requiring human review

## Outstanding verification
A genuine Qloo `none` result has not yet been confirmed. Do not label any row
as a verified no-match until Person 1's Qloo workflow confirms it.


## CSV validation and margin warnings

The sample CSV validation run reported **40 product rows, zero validation
errors, and two margin warnings**. The warnings are intentional examples
of products whose current gross margin is below the product-level minimum:

- **Enlightenment Now (BK018):** unit cost 300, selling price 329, minimum
  acceptable margin 20%. Gross margin is approximately 8.81%.
- **Behave (BK019):** unit cost 490, selling price 599, minimum acceptable
  margin 30%. Gross margin is approximately 18.20%.

Gross margin is calculated as
`(selling_price - unit_cost) / selling_price * 100`.
These warnings are expected QA cases, not CSV parsing errors. Prices are
assumed to be INR, as noted above.
