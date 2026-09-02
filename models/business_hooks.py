# -*- coding: utf-8 -*-
from odoo import models


class SaleOrderHook(models.Model):
    _inherit = "sale.order"

    def write(self, vals):
        prev_states = {rec.id: rec.state for rec in self} if "state" in vals else {}
        res = super().write(vals)
        if "state" in vals:
            for rec in self:
                if prev_states.get(rec.id) != rec.state:
                    self.env["webhook.subscription"]._dispatch(rec)
        return res


class PurchaseOrderHook(models.Model):
    _inherit = "purchase.order"

    def write(self, vals):
        prev_states = {rec.id: rec.state for rec in self} if "state" in vals else {}
        res = super().write(vals)
        if "state" in vals:
            for rec in self:
                if prev_states.get(rec.id) != rec.state:
                    self.env["webhook.subscription"]._dispatch(rec)
        return res


class StockPickingHook(models.Model):
    _inherit = "stock.picking"

    def write(self, vals):
        prev_states = {rec.id: rec.state for rec in self} if "state" in vals else {}
        res = super().write(vals)
        if "state" in vals:
            for rec in self:
                if prev_states.get(rec.id) != rec.state:
                    self.env["webhook.subscription"]._dispatch(rec)
        return res


class AccountMoveHook(models.Model):
    _inherit = "account.move"

    def write(self, vals):
        prev_states = {rec.id: rec.state for rec in self} if "state" in vals else {}
        res = super().write(vals)
        if "state" in vals:
            for rec in self:
                if prev_states.get(rec.id) != rec.state:
                    self.env["webhook.subscription"]._dispatch(rec)
        return res
