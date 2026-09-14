# -*- coding: utf-8 -*-
{
    "name": "n8n Bridge — Outbound & Inbound Automation Webhooks",
    "version": "18.0.1.0.0",
    "category": "Extra Tools/Integration",
    "summary": "Connect Odoo 18 to n8n (or any workflow engine) with configurable "
               "outbound event webhooks and an authenticated inbound endpoint.",
    "description": "Outbound: configurable per-model / per-trigger webhook "
                   "subscriptions, HMAC-signed, queued and retried with backoff. "
                   "Inbound: one authenticated endpoint restricted by an explicit "
                   "action/field whitelist. Odoo 18 port of the 17.0 module.",
    "author": "Sedera Andriamanga",
    "website": "https://github.com/seder2610",
    "license": "LGPL-3",
    "depends": ["base", "sale_management", "purchase", "stock", "account"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/webhook_subscription_views.xml",
        "views/webhook_delivery_views.xml",
        "views/bridge_api_key_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
