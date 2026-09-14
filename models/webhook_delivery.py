# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

import requests
from requests.exceptions import RequestException

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
DEFAULT_TIMEOUT = 8
# Minutes to wait before retry number 1, 2, 3, 4. The 5th failure is final.
RETRY_DELAYS_MINUTES = [5, 15, 60, 180]


class WebhookDelivery(models.Model):
    """One row per attempted (or pending) delivery. Kept as a first-class
    record rather than a fire-and-forget HTTP call so that a failed
    delivery is visible, retryable and auditable from the Odoo UI instead
    of only living in a log file.
    """

    _name = "webhook.delivery"
    _description = "Outbound Webhook Delivery"
    _order = "create_date desc, id desc"

    subscription_id = fields.Many2one(
        "webhook.subscription", required=True, ondelete="cascade", index=True,
    )
    model_name = fields.Selection(
        related="subscription_id.model_name", store=True, string="Watched model",
    )
    res_id = fields.Integer(string="Record ID")
    payload = fields.Text(readonly=True)
    signature = fields.Char(readonly=True)

    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending",
        required=True,
        index=True,
    )
    attempts = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)
    sent_at = fields.Datetime(readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now,
        index=True,
        readonly=True,
        help="The retry cron ignores this delivery until that moment (exponential backoff).",
    )

    def _send(self):
        """Attempt one delivery. Returns True on success. Never raises —
        a broken external endpoint must not break Odoo's cron.
        """
        self.ensure_one()
        subscription = self.subscription_id
        headers = {
            "Content-Type": "application/json",
            "X-Bridge-Signature": self.signature or "",
            "X-Bridge-Event": subscription.trigger or "",
            "X-Bridge-Model": subscription.model_name or "",
        }
        try:
            response = requests.post(
                subscription.target_url,
                data=(self.payload or "").encode(),
                headers=headers,
                timeout=subscription.timeout or DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
        except RequestException as exc:
            attempts = self.attempts + 1
            exhausted = attempts >= MAX_ATTEMPTS
            delay = RETRY_DELAYS_MINUTES[min(attempts, len(RETRY_DELAYS_MINUTES)) - 1]
            self.write(
                {
                    "attempts": attempts,
                    "last_error": str(exc)[:2000],
                    "state": "failed" if exhausted else "pending",
                    "next_attempt_at": False if exhausted
                    else fields.Datetime.now() + timedelta(minutes=delay),
                }
            )
            _logger.warning(
                "n8n bridge: delivery %s failed (attempt %s/%s): %s",
                self.id, attempts, MAX_ATTEMPTS, exc,
            )
            return False

        self.write(
            {
                "state": "sent",
                "attempts": self.attempts + 1,
                "sent_at": fields.Datetime.now(),
                "next_attempt_at": False,
                "last_error": False,
            }
        )
        return True

    @api.model
    def cron_send_pending(self, batch_size=50):
        """Called by a scheduled action every few minutes. Kept out of the
        request/response cycle on purpose — see the design note in
        webhook_subscription.py.
        """
        now = fields.Datetime.now()
        pending = self.search(
            [
                ("state", "=", "pending"),
                "|", ("next_attempt_at", "=", False), ("next_attempt_at", "<=", now),
            ],
            limit=batch_size,
            order="next_attempt_at asc, id asc",
        )
        if not pending:
            return 0
        sent = sum(1 for delivery in pending if delivery._send())
        _logger.info("n8n bridge: cron processed %s/%s due deliveries", sent, len(pending))
        return sent

    def action_retry(self):
        """Re-queue a failed delivery immediately, from the UI."""
        self.write(
            {
                "state": "pending",
                "attempts": 0,
                "last_error": False,
                "next_attempt_at": fields.Datetime.now(),
            }
        )
        return True
