# n8n Bridge — Odoo ⇄ n8n automation webhooks

A small, generic Odoo module built to show one integration pattern used
repeatedly across production projects: exposing ERP business events
(order confirmed, delivery done, invoice posted...) to an external
automation engine such as **n8n**, and letting that engine act back on
Odoo through a single, access-controlled entry point — instead of one
bespoke connector per workflow.

This is a **clean-room demo**, written from scratch for this repository.
It contains no client code and no client data; it exists to show how the
pieces fit together, not to be installed as-is on a production database.

## Why this shape

Most "let's connect Odoo to n8n" integrations start the same way: a
webhook URL is pasted into one automated action, then another, then a
third, until nobody remembers which model triggers which Zap. This
module tries to keep that surface in one place instead:

- **Outbound** — `webhook.subscription` is a configuration screen, not
  code. Pick a model (`sale.order`, `purchase.order`, `stock.picking`,
  `account.move`), a trigger (create / write / state change), a target
  URL and a shared secret. Every matching event is queued as a
  `webhook.delivery` and signed with HMAC-SHA256 (`X-Bridge-Signature`)
  so the receiving n8n workflow can verify it. Delivery runs from a
  5-minute cron, not inline in the request — a slow or down n8n instance
  never blocks the sale/purchase/stock transaction that triggered it,
  and failed deliveries stay visible and retryable in the Odoo UI
  instead of only in a log file.

- **Inbound** — one controller (`POST /n8n_bridge/v1/act`), one API key
  model. A call must present a valid key, name a whitelisted model, and
  either call a whitelisted method or write a whitelisted field —
  nothing else. The real security boundary is that whitelist
  (`INBOUND_ALLOWED_ACTIONS` / `INBOUND_ALLOWED_FIELDS` in
  `models/api_key.py`), not the key alone, and the call runs as the
  specific Odoo user tied to that key so access rights still apply
  normally. The endpoint takes a plain JSON body (not JSON-RPC) and
  answers with real HTTP status codes: `401` without a valid key, `400`
  for a non-whitelisted model / action / field or a malformed body,
  `404` for an unknown record, `200` on success.

## Structure

```
n8n_bridge/
├── models/
│   ├── webhook_subscription.py   outbound config + payload building + HMAC signing
│   ├── webhook_delivery.py       queued delivery, retry with backoff, cron
│   ├── business_hooks.py         hooks onto sale/purchase/stock/account.move
│   └── api_key.py                inbound auth + the action/field whitelist
├── controllers/inbound.py        the one inbound endpoint
├── views/                        subscription + delivery screens, menu
├── security/                     access rights, one admin group
└── migrations/17.0.1.1.0/        worked example of a pre-migrate script
```

## Example flow

1. A `purchase.order` moves to `state = 'purchase'` (confirmed).
2. `business_hooks.py` notices the state changed and calls
   `webhook.subscription._dispatch(record)`.
3. A `webhook.delivery` row is created with a signed JSON payload
   (`{"event": "state_change", "model": "purchase.order", "record_id": 42,
   "values": {...}}`).
4. The cron sends it to the configured n8n Webhook node within 5 minutes;
   n8n can then do anything downstream — post to Slack, create a task,
   call an LLM to draft a supplier follow-up.
5. If n8n needs to write something back (e.g. a supplier reference
   number after the fact), it calls `POST /n8n_bridge/v1/act` with its
   API key — restricted to the fields listed for that model in
   `INBOUND_ALLOWED_FIELDS`.

## Compatibility

Written and tested against the Odoo 17.0 API (`invisible="..."` view
attribute syntax, `<tree>` list views, `type="http"` JSON controller).
Installs cleanly on `odoo:17` (`-i n8n_bridge --stop-after-init`, no
traceback). The dispatch/delivery/whitelist pattern itself is
version-agnostic and has been carried, with minor API adjustments,
across 12 → 19 upgrade projects.

## License

LGPL-3, matching Odoo's own community addons.
