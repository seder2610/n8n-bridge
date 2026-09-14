# n8n Bridge — Odoo 18 ⇄ n8n automation webhooks

Odoo 18 port of the 17.0 `n8n_bridge` module: exposing ERP business events
(order confirmed, delivery done, invoice posted...) to an external automation
engine such as **n8n**, and letting that engine act back on Odoo through a
single, access-controlled entry point — instead of one bespoke connector per
workflow.

This is a **clean-room demo**. It contains no client code and no client data;
it exists to show how the pieces fit together.

| | |
|---|---|
| Version | `18.0.1.0.0` |
| Depends on | `base`, `sale_management`, `purchase`, `stock`, `account` |
| Python | `requests` |
| License | LGPL-3 |

---

## Why this shape

Most "let's connect Odoo to n8n" integrations start the same way: a webhook URL
is pasted into one automated action, then another, then a third, until nobody
remembers which model triggers which Zap. This module keeps that surface in one
place instead.

### Outbound

`webhook.subscription` is a configuration screen, not code. Pick a model
(`sale.order`, `purchase.order`, `stock.picking`, `account.move`), a trigger
(create / write / state change), a target URL and a shared secret. Every
matching event is queued as a `webhook.delivery`, signed with HMAC-SHA256
(`X-Bridge-Signature`) so the receiving n8n workflow can verify it.

Delivery runs from a 5-minute cron, **not inline in the request** — a slow or
down n8n instance never blocks the sale/purchase/stock transaction that
triggered it, and failed deliveries stay visible and retryable in the Odoo UI
instead of only in a log file. Retries use an exponential backoff
(5 min → 15 min → 1 h → 3 h, then `failed` after 5 attempts).

### Inbound

One controller (`POST /n8n_bridge/v1/act`), one API key model. A call must
present a valid key, name a whitelisted model, and either call a whitelisted
method or write a whitelisted field — nothing else. The real security boundary
is that whitelist (`INBOUND_ALLOWED_ACTIONS` / `INBOUND_ALLOWED_FIELDS` in
`models/api_key.py`), not the key alone, and the call runs as the specific Odoo
user tied to that key so access rights still apply normally.

---

## Structure

```
n8n_bridge/
├── models/
│   ├── webhook_subscription.py   outbound config, payload, HMAC signing, dispatch
│   ├── webhook_delivery.py       queued delivery, backoff retry, cron
│   ├── bridge_mixin.py           the hooks, written once and mixed into 4 models
│   └── api_key.py                inbound auth + the action/field whitelist
├── controllers/inbound.py        the one inbound endpoint
├── data/ir_cron.xml              the 5-minute delivery cron
├── views/                        subscription, delivery, API key screens + menu
├── security/                     access rights, one admin group
└── migrations/18.0.1.0.0/        worked example of a pre-migrate script
```

---

## Install

```bash
# from odoo_18_test/
docker compose exec web odoo -d <db> -i n8n_bridge --stop-after-init
```

The menu **n8n Bridge** appears for Settings users (Subscriptions /
Deliveries / Inbound API Keys).

---

## Example flow

1. A `purchase.order` moves to `state = 'purchase'` (confirmed).
2. `bridge_mixin.py` notices the watched field changed and calls
   `webhook.subscription._dispatch(records, 'state_change')`.
3. A `webhook.delivery` row is created with a signed JSON payload:
   ```json
   {
     "event": "state_change",
     "model": "sale.order",
     "record_id": 60,
     "values": {"name": "S00060", "state": "sale", "amount_total": 750.0,
                "partner_id": "Acme Corporation"},
     "timestamp": "2026-09-14T12:37:22"
   }
   ```
4. The cron sends it to the configured n8n Webhook node within 5 minutes, with
   headers `X-Bridge-Signature`, `X-Bridge-Event`, `X-Bridge-Model`.
5. If n8n needs to write something back, it calls `POST /n8n_bridge/v1/act`
   with its API key.

### Verifying the signature on the n8n side

```js
const crypto = require('crypto');
const expected = crypto.createHmac('sha256', SECRET)
                       .update(rawBody)
                       .digest('hex');
// compare with the X-Bridge-Signature header
```

### Calling back into Odoo

```bash
curl -X POST https://odoo.example.com/n8n_bridge/v1/act \
  -H 'Content-Type: application/json' \
  -H 'X-Bridge-Key: <key from the Inbound API Keys screen>' \
  -d '{"model":"sale.order","record_id":60,"values":{"client_order_ref":"REF-FROM-N8N"}}'
```

Responses are plain JSON with a meaningful HTTP status:

| Status | Body |
|--------|------|
| `200` | `{"model": "sale.order", "record_id": 60, "fields_written": ["client_order_ref"]}` |
| `400` | `{"error": "invalid_json"}` / `{"error": "nothing_to_do"}` / `{"error": "invalid_record_id"}` |
| `401` | `{"error": "invalid_or_missing_api_key"}` |
| `403` | `{"error": "fields_not_whitelisted", "rejected": [...], "allowed": [...]}` |
| `404` | `{"error": "record_not_found", ...}` |

---

## What changed versus the 17.0 module

The port is not a syntax refresh: several of the 17.0 behaviours did not
actually work. Each item below was reproduced and then verified fixed against
a running Odoo 18 instance.

**Install / runtime blockers**

- **Outbound dispatch raised `AccessError` for ordinary users.** Subscriptions
  were read as the acting user, but their ACL is restricted to the bridge admin
  group — so a salesperson confirming a quotation got *"You are not allowed to
  access Outbound Automation Webhook Subscription"* and the confirmation
  failed. Dispatch is now `sudo()`: it is system plumbing reacting to a user's
  action, not something the user is doing.
- **Nobody held the admin group, not even `admin`.** `group_n8n_bridge_manager`
  declared `implied_ids = [group_system]`, which grants *system* to bridge
  admins — not the reverse. The group was therefore empty and the menus
  invisible to everyone. `base.group_system` now implies the bridge group.
- **The subscription form referenced `%(action_webhook_delivery)d`**, an XML id
  defined in a view file loaded *after* it — an unresolvable reference at
  install time. The stat button is now an `action_open_deliveries()` Python
  action, removing the cross-file load-order dependency entirely.

**Dead configuration**

- **The `trigger` field did nothing except for state changes.** There was no
  `create()` hook, and `write()` only fired when `state` changed, so
  subscriptions configured as *On creation* or *On any update* never fired.
  Worse, `_dispatch` did not filter by trigger, so a state change notified
  *create* subscriptions too. All three triggers now behave as labelled.
- **The `state_field` field was ignored**; `state` was hardcoded. Each
  subscription's own `state_field` is now compared, per record.

**Protocol**

- **The inbound route was `type="json"`**, which in Odoo speaks JSON-RPC
  (`{"jsonrpc", "method", "params"}`) — an n8n HTTP Request node posting plain
  JSON could not call it. It also discarded the returned HTTP status, so the
  `return {...}, 401` for a bad key actually answered `200`. The route is now
  `type="http"` with `request.get_json_data()` and
  `request.make_json_response(..., status=...)`.

**Performance**

- **`_dispatch` ran one `search` per record and one `create` per delivery.**
  It now resolves subscriptions once per write through an `ormcache` (with the
  registry signalling that keeps other workers in sync) and writes all
  deliveries in a single batched `create`. Creating 20 orders costs ~6.7× the
  queries of creating 1, not 20×.

**Maintainability / gaps**

- The four identical `write()` overrides became one `n8n.bridge.mixin`
  `AbstractModel`, mixed into the four watched models.
- `bridge.api.key` had ACLs but **no view and no menu** — keys could not be
  created from the UI. Added, with a *Regenerate key* button and a
  `last_used_at` stamp.
- The README promised "retry with backoff" but the code retried every cron run
  with no delay. Real backoff added (`next_attempt_at`), plus a *Retry now*
  button on failed deliveries.
- API keys are compared with `hmac.compare_digest` rather than looked up by SQL
  equality.
- `<field name="active">True</field>` in the cron record (a string, not a
  boolean) is now `eval="True"`.

---

## Known scope limits

- `WATCHED_MODELS` is a closed list of four models. A real project would build
  the selection from `ir.model` or extend the list; keeping it closed keeps a
  public demo honest about what it was tested against.
- The default payload exposes a fixed handful of common fields. Override
  `_build_payload` per model for anything real.
- Deliveries are sent sequentially by the cron, one HTTP request each. That is
  inherent to talking to a remote endpoint; the batch size caps how many run
  per cron beat.
- There is no inbound replay protection (nonce / timestamp window) on the
  outbound signature. Add one if the receiver is exposed publicly.
