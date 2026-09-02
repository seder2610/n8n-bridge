# -*- coding: utf-8 -*-
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

    name = fields.Char(required=True, help="Which n8n workflow / integration this key belongs to.")
    key = fields.Char(required=True, default=lambda self: secrets.token_urlsafe(32), copy=False)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        "res.users",
        required=True,
        help="Inbound writes run as this user — scope its access rights instead of the bridge's.",
    )

    _sql_constraints = [("key_unique", "unique(key)", "This key already exists.")]

    @api.model
    def _check(self, key):
        return bool(key) and self.sudo().search_count([("key", "=", key), ("active", "=", True)]) == 1
