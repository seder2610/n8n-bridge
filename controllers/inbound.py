# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

from ..models.api_key import INBOUND_ALLOWED_ACTIONS, INBOUND_ALLOWED_FIELDS

_logger = logging.getLogger(__name__)


class N8nBridgeInboundController(http.Controller):
    """Single entry point for n8n (or any external system) to act back on
    Odoo. Deliberately not a generic RPC gateway: only a pre-declared
    action can be called, only a pre-declared field can be written, and
    every call runs as the specific Odoo user tied to the API key — never
    as an elevated technical account.

    Plain JSON body in, plain JSON body out, with real HTTP status codes
    (``401`` unauthenticated, ``400`` bad request, ``404`` unknown record,
    ``200`` on success) so a caller such as an n8n *HTTP Request* node can
    branch on the status directly.
    """

    @http.route(
        "/n8n_bridge/v1/act",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def act(self, **kwargs):
        api_key = request.httprequest.headers.get("X-Bridge-Key")
        Key = request.env["bridge.api.key"].sudo()
        if not Key._check(api_key):
            return request.make_json_response({"error": "invalid_or_missing_api_key"}, status=401)

        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return request.make_json_response({"error": "invalid_json"}, status=400)

        model_name = payload.get("model")
        record_id = payload.get("record_id")
        action = payload.get("action")
        values = payload.get("values") or {}

        if model_name not in INBOUND_ALLOWED_ACTIONS and model_name not in INBOUND_ALLOWED_FIELDS:
            return request.make_json_response(
                {"error": "model_not_whitelisted", "model": model_name}, status=400
            )

        key_record = Key.search([("key", "=", api_key)], limit=1)
        env = request.env(user=key_record.user_id.id)
        record = env[model_name].browse(int(record_id)).exists()
        if not record:
            return request.make_json_response({"error": "record_not_found"}, status=404)

        result = {"model": model_name, "record_id": record.id}

        if action:
            allowed = INBOUND_ALLOWED_ACTIONS.get(model_name, [])
            if action not in allowed:
                return request.make_json_response(
                    {"error": "action_not_whitelisted", "allowed": allowed}, status=400
                )
            getattr(record, action)()
            result["action_executed"] = action

        if values:
            allowed_fields = INBOUND_ALLOWED_FIELDS.get(model_name, [])
            rejected = [f for f in values if f not in allowed_fields]
            if rejected:
                return request.make_json_response(
                    {"error": "fields_not_whitelisted", "rejected": rejected, "allowed": allowed_fields},
                    status=400,
                )
            record.write(values)
            result["fields_written"] = list(values.keys())

        _logger.info(
            "n8n bridge: inbound call by key '%s' on %s#%s (%s)",
            key_record.name,
            model_name,
            record.id,
            result,
        )
        return request.make_json_response(result)
