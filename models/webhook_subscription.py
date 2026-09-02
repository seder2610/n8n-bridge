# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Models this demo module knows how to watch. A real project extends this
# list (or moves it to a selection built from ir.model) rather than hard
# -coding it, but a closed list keeps a public demo module honest about
# its scope.
WATCHED_MODELS = [
    ("sale.order", "Sales Order"),
    ("purchase.order", "Purchase Order"),
    ("stock.picking", "Delivery / Receipt"),
    ("account.move", "Invoice / Bill"),
]

TRIGGER_SELECTION = [
    ("create", "On creation"),
    ("write", "On any update"),
    ("state_change", "On state change only"),
]


class WebhookSubscription(models.Model):
    """One row = one external URL that wants to hear about one model's
    events. Kept deliberately simple: the goal is a readable, auditable
    configuration screen for a non-technical ops person, not a generic
    event bus.
    """

    _name = "webhook.subscription"
    _description = "Outbound Automation Webhook Subscription"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Internal label, e.g. 'n8n — Purchase approvals'.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_name = fields.Selection(WATCHED_MODELS, required=True, string="Watched model")
    trigger = fields.Selection(TRIGGER_SELECTION, required=True, default="state_change")
    state_field = fields.Char(
        default="state",
        help="Name of the field to watch when trigger = 'On state change only'.",
    )

    target_url = fields.Char(
        required=True,
        string="Target URL",
        help="Endpoint that will receive the JSON payload (typically an n8n Webhook node).",
    )
    secret = fields.Char(
        required=True,
        help="Shared secret used to sign the payload (HMAC-SHA256, header X-Bridge-Signature). "
        "Configure the same value on the n8n side to verify authenticity.",
    )
    timeout = fields.Integer(default=8, help="HTTP timeout in seconds before the delivery is queued for retry.")

    delivery_ids = fields.One2many("webhook.delivery", "subscription_id", string="Recent deliveries")
    delivery_count = fields.Integer(compute="_compute_delivery_count")

    @api.depends("delivery_ids")
    def _compute_delivery_count(self):
        for rec in self:
            rec.delivery_count = len(rec.delivery_ids)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _build_payload(self, record):
        """Small, predictable payload — id, model, a handful of common
        fields if present, and a server-generated timestamp. A real
        integration typically overrides this per model; this default is
        intentionally conservative about what it exposes.
        """
        self.ensure_one()
        common_fields = ["name", "state", "amount_total", "partner_id", "date_order", "invoice_date"]
        values = {}
        for f in common_fields:
            if f in record._fields and record[f]:
                v = record[f]
                values[f] = v.display_name if hasattr(v, "display_name") else v
        return {
            "event": self.trigger,
            "model": self.model_name,
            "record_id": record.id,
            "values": values,
            "timestamp": fields.Datetime.now().isoformat(),
        }

    def _sign(self, payload_bytes):
        self.ensure_one()
        return hmac.new(self.secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    def _dispatch(self, record):
        """Queue a delivery for every active subscription matching this
        record's model. Sending happens in ``webhook.delivery`` so a slow
        endpoint never holds up the caller's transaction — this method
        only ever writes a local row.
        """
        subs = self.search([("model_name", "=", record._name), ("active", "=", True)])
        for sub in subs:
            payload = sub._build_payload(record)
            body = json.dumps(payload, default=str).encode()
            self.env["webhook.delivery"].sudo().create(
                {
                    "subscription_id": sub.id,
                    "res_id": record.id,
                    "payload": body.decode(),
                    "signature": sub._sign(body),
                    "state": "pending",
                }
            )
        if subs:
            # Deliveries are sent by a queued job / cron rather than inline —
            # see webhook.delivery.cron_send_pending().
            _logger.debug("n8n bridge: queued %s delivery(ies) for %s#%s", len(subs), record._name, record.id)
