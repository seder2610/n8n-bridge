# -*- coding: utf-8 -*-
"""Illustrative migration script — kept in the repo as a worked example of
the pattern used on real upgrade projects (renaming a field, backfilling
new columns from an old shape, done in raw SQL in pre-migrate so it runs
before the ORM sees the new model definition).

This one migrates ``webhook.subscription`` from the 17.0.1.0.0 shape
(a single hardcoded target model per subscription, boolean ``is_active``)
to 17.0.1.1.0 (``model_name`` selection field, ``active`` — Odoo's
standard convention, matching ``|active is False|`` default filtering).

Run automatically by the Odoo upgrade mechanism; no manual step needed.
"""
import logging

from odoo.tools import column_exists, table_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not table_exists(cr, "webhook_subscription"):
        return

    # 17.0.1.0.0 -> 17.0.1.1.0: is_active (bool) renamed to Odoo's
    # standard `active`, so the framework's built-in active-record
    # filtering applies without a custom domain everywhere.
    if column_exists(cr, "webhook_subscription", "is_active") and not column_exists(
        cr, "webhook_subscription", "active"
    ):
        _logger.info("n8n_bridge: renaming webhook_subscription.is_active -> active")
        cr.execute('ALTER TABLE webhook_subscription RENAME COLUMN "is_active" TO "active"')

    # Same release folded a free-text `target_model` field into the new
    # `model_name` selection — keep existing data instead of losing every
    # subscription on upgrade.
    if column_exists(cr, "webhook_subscription", "target_model") and column_exists(
        cr, "webhook_subscription", "model_name"
    ):
        _logger.info("n8n_bridge: backfilling model_name from legacy target_model")
        cr.execute(
            """
            UPDATE webhook_subscription
               SET model_name = target_model
             WHERE model_name IS NULL
               AND target_model IN ('sale.order', 'purchase.order', 'stock.picking', 'account.move')
            """
        )
