# -*- coding: utf-8 -*-
import hmac
import secrets

from odoo import api, fields, models

# Narrow, explicit whitelist of what an inbound call is allowed to touch.
# Anything not listed here is refused by the controller — see
# controllers/inbound.py. This is the module's actual security boundary,
# not the API key alone.
INBOUND_ALLOWED_ACTIONS = {
    "sale.order": ["action_confirm"],
    "purchase.order": ["button_confirm"],
    "stock.picking": ["button_validate"],
}
INBOUND_ALLOWED_FIELDS = {
    "sale.order": ["client_order_ref"],
    "purchase.order": ["partner_ref"],
    "stock.picking": ["note"],
}


class BridgeApiKey(models.Model):
    _name = "bridge.api.key"
    _description = "n8n Bridge — Inbound API Key"
    _order = "name"

    name = fields.Char(required=True, help="Which n8n workflow / integration this key belongs to.")
    key = fields.Char(required=True, default=lambda self: secrets.token_urlsafe(32), copy=False)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        help="Inbound writes run as this user — scope its access rights instead of the bridge's.",
    )
    last_used_at = fields.Datetime(readonly=True, help="Last time this key authenticated a call.")

    _sql_constraints = [("key_unique", "unique(key)", "This key already exists.")]

    @api.model
    def _resolve(self, key):
        """Return the active key record matching ``key``, or an empty
        recordset. Compared with ``compare_digest`` rather than looked up
        by SQL equality so the answer does not leak through timing.
        """
        if not key:
            return self.browse()
        for record in self.sudo().search([]):
            if hmac.compare_digest(record.key or "", key):
                return record
        return self.browse()

    def action_regenerate_key(self):
        for record in self:
            record.key = secrets.token_urlsafe(32)
        return True
