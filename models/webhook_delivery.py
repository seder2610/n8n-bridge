# -*- coding: utf-8 -*-
import logging

import requests
from requests.exceptions import RequestException

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


class WebhookDelivery(models.Model):
    """One row per attempted (or pending) delivery. Kept as a first-class
    record rather than a fire-and-forget HTTP call so that a failed
    delivery is visible, retryable and auditable from the Odoo UI instead
    of only living in a log file.
    """

    _name = "webhook.delivery"
    _description = "Outbound Webhook Delivery"
    _order = "create_date desc"

    subscription_id = fields.Many2one("webhook.subscription", required=True, ondelete="cascade")
    res_id = fields.Integer(string="Record ID")
    payload = fields.Text(readonly=True)
    signature = fields.Char(readonly=True)

    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending",
        required=True,
    )
    attempts = fields.Integer(default=0)
    last_error = fields.Text(readonly=True)
    sent_at = fields.Datetime(readonly=True)

    def _send(self):
        """Attempt one delivery. Returns True on success. Never raises —
        a broken external endpoint must not break Odoo's cron.
        """
        self.ensure_one()
        sub = self.subscription_id
        headers = {
            "Content-Type": "application/json",
            "X-Bridge-Signature": self.signature,
            "X-Bridge-Event": sub.trigger,
        }
        try:
            resp = requests.post(
                sub.target_url,
                data=self.payload.encode(),
                headers=headers,
                timeout=sub.timeout or 8,
            )
            resp.raise_for_status()
        except RequestException as exc:
            self.write(
                {
                    "attempts": self.attempts + 1,
                    "last_error": str(exc),
                    "state": "failed" if self.attempts + 1 >= MAX_ATTEMPTS else "pending",
                }
            )
            _logger.warning("n8n bridge: delivery %s failed (attempt %s): %s", self.id, self.attempts + 1, exc)
            return False

        self.write({"state": "sent", "sent_at": fields.Datetime.now()})
        return True

    @api.model
    def cron_send_pending(self, batch_size=50):
        """Called by a scheduled action every few minutes. Kept out of the
        request/response cycle on purpose — see the design note in
        webhook_subscription.py.
        """
        pending = self.search([("state", "=", "pending")], limit=batch_size, order="create_date asc")
        sent = sum(1 for d in pending if d._send())
        if pending:
            _logger.info("n8n bridge: cron processed %s/%s pending deliveries", sent, len(pending))
