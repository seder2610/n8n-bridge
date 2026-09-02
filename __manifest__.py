# -*- coding: utf-8 -*-
{
    "name": "n8n Bridge — Outbound & Inbound Automation Webhooks",
    "version": "17.0.1.1.0",
    "category": "Extra Tools/Integration",
    "summary": "Connect Odoo to n8n (or any workflow engine) with configurable "
                "outbound event webhooks and an authenticated inbound endpoint.",
    "description": """
n8n Bridge
==========

A small, generic integration module built to demonstrate a pattern used
repeatedly across production Odoo projects: exposing business events
(sale confirmed, purchase validated, delivery done, invoice posted) to an
external automation engine such as n8n, and letting that engine write
back into Odoo through a single, access-controlled entry point — instead
of one bespoke connector per workflow.

Outbound
--------
* ``webhook.subscription`` — configure, per model and per trigger
  (create / write / state change), which external URL receives a JSON
  payload, with a shared secret used to sign the request (HMAC-SHA256 in
  the ``X-Bridge-Signature`` header) so the receiving n8n workflow can
  verify authenticity.
* Hooked, as an example, onto ``sale.order``, ``purchase.order``,
  ``stock.picking`` and ``account.move`` — enough surface to cover a
  typical achats / ventes / stocks / facturation flow without touching
  every model in the database.
* Delivery is queued and retried (simple backoff), so a slow or briefly
  unavailable n8n instance does not block the Odoo transaction that
  triggered it.

Inbound
-------
* One controller, one API key model. n8n (or another external system)
  calls back with a JSON body naming a target model, record and a small
  whitelisted set of fields/actions — never arbitrary code execution,
  never arbitrary field writes.

This module intentionally ships with a narrow surface and no
client-specific logic: it is a clean-room illustration of the
integration pattern, meant to be extended per project, not a
plug-and-play product.

License: LGPL-3
""",
    "author": "Sedera Andriamanga",
    "website": "https://github.com/seder2610",
    "license": "LGPL-3",
    "depends": ["base", "sale_management", "purchase", "stock", "account"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        # webhook_delivery_views.xml first: it defines the root menu, the
        # deliveries action and the cron that webhook_subscription_views.xml
        # then references (stat button, submenu).
        "views/webhook_delivery_views.xml",
        "views/webhook_subscription_views.xml",
    ],
    "installable": True,
    "application": False,
}
