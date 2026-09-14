# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging

from odoo import api, fields, models, tools

_logger = logging.getLogger(__name__)

# Models this demo module knows how to watch. A real project extends this
# list (or builds a selection from ir.model) rather than hard-coding it,
# but a closed list keeps a public demo module honest about its scope.
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
        help="Name of the field to watch when trigger = 'On state change only'. "
             "Ignored for the other triggers.",
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
        counts = {}
        if self.ids:
            counts = {
                subscription.id: count
                for subscription, count in self.env["webhook.delivery"]._read_group(
                    [("subscription_id", "in", self.ids)],
                    groupby=["subscription_id"],
                    aggregates=["__count"],
                )
            }
        for record in self:
            record.delivery_count = counts.get(record.id, 0)

    # ------------------------------------------------------------------
    # Subscription lookup cache
    #
    # The outbound hooks run inside write() on hot models (account.move in
    # particular). Hitting the database on every write just to learn that
    # nothing is subscribed would be a real cost, so the model -> ids map
    # is cached and invalidated whenever a subscription changes.
    # ------------------------------------------------------------------
    @api.model
    @tools.ormcache("model_name")
    def _subscription_ids_for(self, model_name):
        return tuple(self.sudo().search([("model_name", "=", model_name)]).ids)

    def _clear_subscription_cache(self):
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        subscriptions = super().create(vals_list)
        self._clear_subscription_cache()
        return subscriptions

    def write(self, vals):
        res = super().write(vals)
        self._clear_subscription_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self._clear_subscription_cache()
        return res

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _build_payload(self, record, trigger):
        """Small, predictable payload — id, model, a handful of common
        fields if present, and a server-generated timestamp. A real
        integration typically overrides this per model; this default is
        intentionally conservative about what it exposes.
        """
        self.ensure_one()
        common_fields = ["name", "state", "amount_total", "partner_id", "date_order", "invoice_date"]
        values = {}
        for field_name in common_fields:
            if field_name in record._fields and record[field_name]:
                value = record[field_name]
                values[field_name] = value.display_name if hasattr(value, "display_name") else value
        return {
            "event": trigger,
            "model": self.model_name,
            "record_id": record.id,
            "values": values,
            "timestamp": fields.Datetime.now().isoformat(),
        }

    def _sign(self, payload_bytes):
        self.ensure_one()
        return hmac.new(self.secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    @api.model
    def _dispatch(self, records, trigger, changed_by_record=None):
        """Queue one delivery per (subscription, record) pair matching this
        trigger. Sending happens in ``webhook.delivery`` so a slow endpoint
        never holds up the caller's transaction — this method only ever
        writes local rows, and it writes them in a single batched create.
        """
        if not records:
            return
        subscription_ids = self._subscription_ids_for(records._name)
        if not subscription_ids:
            return
        # Dispatch is system plumbing reacting to a user's action, not
        # something the user is doing: a salesperson confirming an order
        # must not need read access on the webhook configuration (and its
        # secret) for that confirmation to succeed.
        subscriptions = self.sudo().browse(subscription_ids).filtered(
            lambda s: s.trigger == trigger
        )
        if not subscriptions:
            return

        delivery_vals = []
        for subscription in subscriptions:
            targets = records
            if trigger == "state_change":
                watched_field = subscription.state_field or "state"
                changed = changed_by_record or {}
                targets = records.filtered(lambda r: watched_field in changed.get(r.id, ()))
            for record in targets:
                body = json.dumps(subscription._build_payload(record, trigger), default=str).encode()
                delivery_vals.append(
                    {
                        "subscription_id": subscription.id,
                        "res_id": record.id,
                        "payload": body.decode(),
                        "signature": subscription._sign(body),
                        "state": "pending",
                    }
                )

        if delivery_vals:
            self.env["webhook.delivery"].sudo().create(delivery_vals)
            _logger.debug(
                "n8n bridge: queued %s delivery(ies) for %s on trigger '%s'",
                len(delivery_vals), records._name, trigger,
            )

    def action_open_deliveries(self):
        """Stat-button action. Built in Python rather than referencing the
        delivery action's XML id from this file's view, which would force a
        load-order dependency between the two view files.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Deliveries",
            "res_model": "webhook.delivery",
            "view_mode": "list,form",
            "domain": [("subscription_id", "=", self.id)],
            "context": {"default_subscription_id": self.id, "create": False},
        }
