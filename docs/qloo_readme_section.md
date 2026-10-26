## Qloo integration

StockRescue calls the real Qloo API from the backend only; the API key never reaches the browser.

| Step | Qloo endpoint | What we do with it |
|---|---|---|
| Entity resolution | `GET /search` (`types=urn:entity:book`) | Classify the result as **strong**, **ambiguous** or **none**. Ambiguous matches need a human to choose. No match is shown as a Qloo coverage gap. |
| Cultural insights | `GET /v2/insights` (`filter.type`, `signal.interests.entities`) | Related entities for a confirmed match, stored raw as evidence. |

**Provenance.** Every Qloo response is stored verbatim (`qloo_evidence` table) with the request parameters and
timestamp. Plans and experiments reference these evidence ids, so the UI can show exactly what Qloo returned.

**What we do not claim.** Affinity values are shown only if Qloo returned them. `internal_name_similarity` is our own
string comparison, not a Qloo score. A Qloo association is a hypothesis to test, not a sales prediction.

**Reliability.** 15 s timeout, up to 3 attempts for timeouts / 429 / 5xx, `Retry-After` respected, in-memory
response cache (1 h), clear error codes, and no key in logs.

**Tests.** `pytest` runs isolated tests with mocked Qloo responses (clearly separate from the live integration).
`python qloo_smoke_test.py` and `GET /qloo/status` exercise the real API.

> TODO before submission: confirm field names against real responses and record the date verified.
