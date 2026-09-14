# -*- coding: utf-8 -*-
from odoo import api, models


class N8nBridgeMixin(models.AbstractModel):
    """Outbound event hooks, written once and mixed into every watched
    model instead of copy-pasting the same ``write()`` override per model.

    Honours the three configured triggers:

    * ``create``       — fired once per batch of newly created records;
    * ``write``        — fired on any update;
    * ``state_change`` — fired only when the field named by the
      subscription's ``state_field`` actually changed value, compared
      per record and per subscription.
    """

    _name = "n8n.bridge.mixin"
    _description = "n8n Bridge — Outbound Event Hooks"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env["webhook.subscription"]._dispatch(records, "create")
        return records

    def write(self, vals):
        Subscription = self.env["webhook.subscription"]
        subscription_ids = Subscription._subscription_ids_for(self._name)
        subscriptions = Subscription.browse(subscription_ids)

        # Snapshot only the fields some subscription actually watches, and
        # only when at least one state_change subscription exists.
        watched = {
            subscription.state_field or "state"
            for subscription in subscriptions
            if subscription.trigger == "state_change"
        } & set(self._fields)
        before = (
            {record.id: {name: record[name] for name in watched} for record in self}
            if watched
            else {}
        )

        res = super().write(vals)

        if any(subscription.trigger == "write" for subscription in subscriptions):
            Subscription._dispatch(self, "write")

        if watched:
            changed_by_record = {
                record.id: {
                    name for name in watched if record[name] != before[record.id][name]
                }
                for record in self
            }
            if any(changed_by_record.values()):
                Subscription._dispatch(self, "state_change", changed_by_record)

        return res


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "n8n.bridge.mixin"]


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "n8n.bridge.mixin"]


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "n8n.bridge.mixin"]


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "n8n.bridge.mixin"]
