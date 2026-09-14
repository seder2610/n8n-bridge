# -*- coding: utf-8 -*-
"""Illustrative migration script — kept in the repo as a worked example of
the pattern used on real upgrade projects (renaming a field, backfilling
new columns from an old shape, done in raw SQL in pre-migrate so it runs
before the ORM sees the new model definition).

It covers the path from the 17.0 module to this 18.0 one:

* 17.0.1.0.0 shaped ``webhook.subscription`` with a boolean ``is_active``
  and a free-text ``target_model``;
* 18.0.1.0.0 adds ``webhook.delivery.next_attempt_at``, which drives the
  retry backoff — existing pending rows must be made due immediately
  rather than left NULL-and-ambiguous.

Run automatically by the Odoo upgrade mechanism; no manual step needed.
"""
import logging

from odoo.tools import column_exists, table_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install, nothing to migrate.
        return

    if table_exists(cr, "webhook_subscription"):
        # Legacy boolean renamed to Odoo's standard `active`, so the
        # framework's built-in active-record filtering applies without a
        # custom domain everywhere.
        if column_exists(cr, "webhook_subscription", "is_active") and not column_exists(
            cr, "webhook_subscription", "active"
        ):
            _logger.info("n8n_bridge: renaming webhook_subscription.is_active -> active")
            cr.execute('ALTER TABLE webhook_subscription RENAME COLUMN "is_active" TO "active"')

        # Free-text `target_model` folded into the `model_name` selection —
        # keep existing data instead of losing every subscription on upgrade.
        if column_exists(cr, "webhook_subscription", "target_model") and column_exists(
            cr, "webhook_subscription", "model_name"
        ):
            _logger.info("n8n_bridge: backfilling model_name from legacy target_model")
            cr.execute(
                """
                UPDATE webhook_subscription
                   SET model_name = target_model
                 WHERE model_name IS NULL
                   AND target_model IN ('sale.order', 'purchase.order',
                                        'stock.picking', 'account.move')
                """
            )

    # New in 18.0: the retry cron only picks up deliveries whose
    # next_attempt_at has passed. Pending rows carried over from 17.0 have
    # no value yet, so make them due now instead of relying on the
    # "NULL means due" fallback.
    if table_exists(cr, "webhook_delivery") and column_exists(
        cr, "webhook_delivery", "next_attempt_at"
    ):
        _logger.info("n8n_bridge: scheduling legacy pending deliveries for immediate retry")
        cr.execute(
            """
            UPDATE webhook_delivery
               SET next_attempt_at = NOW() AT TIME ZONE 'UTC'
             WHERE state = 'pending'
               AND next_attempt_at IS NULL
            """
        )
