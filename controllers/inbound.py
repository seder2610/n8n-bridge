# -*- coding: utf-8 -*-
import logging

from odoo import fields, http
from odoo.http import request

from ..models.api_key import INBOUND_ALLOWED_ACTIONS, INBOUND_ALLOWED_FIELDS

_logger = logging.getLogger(__name__)


class N8nBridgeInboundController(http.Controller):
    """Single entry point for n8n (or any external system) to act back on
    Odoo. Deliberately not a generic RPC gateway: only a pre-declared
    action can be called, only a pre-declared field can be written, and
    every call runs as the specific Odoo user tied to the API key — never
    as an elevated technical account.

    Declared as ``type="http"`` on purpose. Odoo's ``type="json"`` routes
    speak JSON-RPC (``{"jsonrpc", "method", "params"}``) and discard the
    HTTP status code, which makes them a poor fit for a plain-JSON caller
    such as an n8n HTTP Request node.
    """

    @staticmethod
    def _error(message, status, **extra):
        return request.make_json_response({"error": message, **extra}, status=status)

    @http.route(
        "/n8n_bridge/v1/act",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def act(self, **kwargs):
        try:
            payload = request.get_json_data()
        except ValueError:
            return self._error("invalid_json", 400)
        if not isinstance(payload, dict):
            return self._error("invalid_payload", 400)

        api_key = request.httprequest.headers.get("X-Bridge-Key")
        key_record = request.env["bridge.api.key"].sudo()._resolve(api_key)
        if not key_record:
            return self._error("invalid_or_missing_api_key", 401)

        model_name = payload.get("model")
        record_id = payload.get("record_id")
        action = payload.get("action")
        values = payload.get("values") or {}

        if model_name not in INBOUND_ALLOWED_ACTIONS and model_name not in INBOUND_ALLOWED_FIELDS:
            return self._error("model_not_whitelisted", 403, model=model_name)
        if not action and not values:
            return self._error("nothing_to_do", 400)

        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            return self._error("invalid_record_id", 400)

        # Everything from here runs as the key's own user, so normal access
        # rights and record rules apply exactly as they would in the UI.
        env = request.env(user=key_record.user_id.id, su=False)
        record = env[model_name].browse(record_id).exists()
        if not record:
            return self._error("record_not_found", 404, model=model_name, record_id=record_id)

        result = {"model": model_name, "record_id": record.id}

        if action:
            allowed = INBOUND_ALLOWED_ACTIONS.get(model_name, [])
            if action not in allowed:
                return self._error("action_not_whitelisted", 403, allowed=allowed)
            getattr(record, action)()
            result["action_executed"] = action

        if values:
            allowed_fields = INBOUND_ALLOWED_FIELDS.get(model_name, [])
            rejected = [name for name in values if name not in allowed_fields]
            if rejected:
                return self._error(
                    "fields_not_whitelisted", 403, rejected=rejected, allowed=allowed_fields
                )
            record.write(values)
            result["fields_written"] = list(values)

        key_record.sudo().last_used_at = fields.Datetime.now()
        _logger.info(
            "n8n bridge: inbound call by key '%s' on %s#%s (%s)",
            key_record.name, model_name, record.id, result,
        )
        return request.make_json_response(result)
