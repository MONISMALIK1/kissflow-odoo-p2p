# AI Procure-to-Pay bridge — Kissflow × Odoo

A working prototype that connects a **Kissflow** purchase-request workflow to an
**Odoo** ERP, with a **Claude** AI layer in the middle that reads each request,
matches it against the Odoo catalog, flags anomalies, and decides whether to
auto-create the purchase order or route it for human review.

> Runs **out of the box with zero credentials** (mock Odoo + Kissflow, offline AI),
> so you can `python scripts/demo.py` and see the whole flow immediately. Flip each
> dependency to live one at a time via `.env`.

---

## Why these two tools together

- **Kissflow** is a no-code workflow layer — forms, approvals, where *people* live.
  Great front end, weak as a system of record.
- **Odoo** is a full ERP — the *system of record* for vendors, products, purchase
  orders, and accounting. Solid API, clunky for ad-hoc human workflows.

The real-world pattern is **Kissflow = human workflow, Odoo = data backbone, with
middleware stitching them together.** This project adds a Claude layer in that
middle so the integration isn't just plumbing — it extracts, matches, and reasons.

## Architecture

```
 Kissflow form + approval
          │  (webhook: approved purchase request)
          ▼
 ┌─────────────────────────────────────────────┐
 │  FastAPI middleware  (app/main.py)           │
 │   1. read catalog from Odoo                   │
 │   2. AI layer → P2PAssessment  (app/ai_layer) │  ← Claude, structured outputs
 │   3. act on recommendation     (app/pipeline) │
 │   4. sync status back to Kissflow             │
 └─────────────────────────────────────────────┘
     │                                   │
     ▼ create draft PO                   ▼ status + note
   Odoo (system of record)            Kissflow (requester sees it)
```

The AI layer returns a typed verdict (`app/models.py::P2PAssessment`):
normalized line items, fuzzy matches to Odoo product/vendor IDs, a suggested
expense category, flagged anomalies (`duplicate`, `price_variance`,
`over_budget`, `missing_info`, `unknown_vendor`), and a recommendation
(`auto_approve` / `needs_review` / `reject`).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Runs offline (no API key, no Odoo, no Kissflow):
AI_MODE=offline python scripts/demo.py

# Real AI layer (needs an Anthropic API key in .env), still mock Odoo/Kissflow:
AI_MODE=live python scripts/demo.py
```

Run it as a service:

```bash
uvicorn app.main:app --reload
curl -s localhost:8000/health
curl -s -X POST localhost:8000/webhooks/kissflow/purchase-request \
  -H 'content-type: application/json' \
  -d @sample_data/single_request.json   # any one object from requests.json
```

## What the sample requests demonstrate

| Request | Shows |
|---|---|
| `PR-2026-0481` | Clean request within limit → all lines matched → **auto_approve** → Odoo PO created |
| `PR-2026-0482` | MacBook priced above catalog → **price_variance** anomaly + over limit → **needs_review** |
| `PR-2026-0483` | Free-text blob + unknown vendor → the live AI layer extracts line items; offline mode flags it as unparseable (the gap is the point) |

## Modes (.env)

| Var | Values | Effect |
|---|---|---|
| `AI_MODE` | `live` / `offline` | Claude vs. a deterministic heuristic (no key) |
| `ODOO_MODE` | `mock` / `live` | seed JSON vs. real Odoo XML-RPC |
| `KISSFLOW_MODE` | `mock` / `live` | log to stdout vs. POST status to Kissflow |
| `ANTHROPIC_MODEL` | model id | defaults to `claude-opus-4-8` |
| `AUTO_APPROVE_LIMIT` | number | requests at/under this total may auto-approve |
| `PRICE_VARIANCE_FACTOR` | number | line price > catalog × this → flagged |

## Going live

1. **Odoo** — set `ODOO_MODE=live` + `ODOO_URL/DB/USERNAME/PASSWORD`. The client
   uses standard XML-RPC (`res.partner`, `product.product`, `purchase.order`).
   Use an Odoo API key as the password.
2. **Kissflow** — set `KISSFLOW_MODE=live` + access keys, and point a Kissflow
   workflow's "on approved" webhook at `/webhooks/kissflow/purchase-request`.
3. **AI** — set `AI_MODE=live` + `ANTHROPIC_API_KEY`. The catalog is sent with
   prompt caching, so repeat runs only pay ~0.1× for the catalog tokens.

## Layout

```
app/
  config.py         settings + per-dependency modes
  models.py         Pydantic shapes (also the AI structured-output schema)
  ai_layer.py       Claude assessment (live) + heuristic (offline)
  odoo_client.py    catalog read + PO create (mock / XML-RPC)
  kissflow_client.py status sync back (mock / REST)
  pipeline.py       orchestration
  main.py           FastAPI webhook
sample_data/        odoo_seed.json, requests.json
scripts/demo.py     end-to-end runner
```

## Notes & next steps

- **Duplicate detection** currently relies on the AI layer reasoning over a single
  request; a production version would pass recent PO history so it can catch true
  duplicates.
- **Human-in-the-loop**: `needs_review` items just sync a status today — a natural
  extension is to push them to a Kissflow review board and resume on decision.
- This is a portfolio prototype, not production code (no auth on the webhook, no
  retries/queue). Those are the obvious hardening steps.
