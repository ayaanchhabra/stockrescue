# stockrescue
StockRescue is an AI agent for independent retailers that identifies slow-moving inventory, uses Qloo's cultural intelligence to discover potentially relevant cross-category associations, proposes feasible merchandising experiments, calculates their economics, and helps the retailer measure what actually works.

## Security and active-stock commitments

Before exposing the API, configure retailer bearer-token hashes and the exact frontend CORS origin. See [`docs/security_and_stock_commitments.md`](docs/security_and_stock_commitments.md) for token generation/revocation, tenant scoping, Qloo matching/provenance, active experiment stock commitments, and the required PostgreSQL migration. Record task-level commands and results in [`WORK_LOG.md`](WORK_LOG.md). Do not put the raw retailer token in frontend browser code; use a server-side proxy/session.
