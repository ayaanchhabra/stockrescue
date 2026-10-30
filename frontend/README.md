# StockRescue frontend

## Local development

```bash
npm ci
# Add frontend/.env.local: NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`. Use **API access** to paste a retailer bearer token issued out-of-band by the backend administrator. The demo stores the token in the current tab's `sessionStorage` and attaches it to protected API requests. Clear it when finished. Use HTTPS outside localhost. This is a hackathon-demo token flow, not a production identity/session system.

## Retailer settings

The Settings page calls authenticated `GET /settings` and `PUT /settings`. It exposes the current MVP's minimum margin, maximum discount, campaign budget, restricted SKUs, test units/days and direct campaign cost assumptions. Other ranking and slow-moving configuration values are preserved when saving.

## Checks

```bash
npm run typecheck
npm run lint
npm run build
```

API keys and retailer bearer tokens must not be committed or embedded in public `NEXT_PUBLIC_*` environment variables.
