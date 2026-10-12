"""Pre-dispatch failures are visible without sending or reserving request IDs."""

from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from homeassistant.components import webhook
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.util.aiohttp import MockRequest

from custom_components.home_messages.const import DOMAIN


def request(data):
    body = json.dumps(data).encode()
    result = MockRequest(body, "home_messages/tests", method="POST", remote="127.0.0.1",
                         headers={"Content-Type": "application/json"})
    result.content_type = "application/json"
    result.content_length = len(body)
    return result


async def setup_entry(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def sensor_state(hass, entry):
    sensor_id = entity_registry.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, entry.entry_id + "_last_delivery"
    )
    return hass.states.get(sensor_id)


async def reject(hass, entry, data, interface, *, status=400, match=None):
    if interface == "service":
        with pytest.raises(HomeAssistantError, match=match):
            await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    else:
        response = await webhook.async_handle_webhook(hass, entry.data["webhook_id"], request(data))
        assert response.status == status
    await hass.async_block_till_done()


@pytest.mark.parametrize("interface", ["service", "webhook"])
async def test_missing_group_is_visible_and_does_not_consume_request_id(hass, entry, transports, interface):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {}})
    await setup_entry(hass, entry)
    data = {"text": "Private body must stay private", "initials": "BB-AA",
            "request_id": "private-request-id-not-for-status"}

    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        await reject(hass, entry, data, interface, match="no valid configured chat ID")
    state = sensor_state(hass, entry)
    assert state.state == "failed"
    assert state.attributes["complete"] is True
    assert state.attributes["phase"] == "preflight"
    assert state.attributes["error"]["code"] == "group_not_configured"
    assert state.attributes["results"] == [{
        "initials": ["AA", "BB"], "target_type": "group", "target": "AA-BB",
        "state": "rejected", "reason": "group_not_configured",
    }]
    assert not all(result["state"] == "accepted" for result in state.attributes["results"])
    notice = notification.call_args.args[1]
    assert "Configure AA-BB=chat_id:ID" in notice
    assert notification.call_args.kwargs["notification_id"] == DOMAIN + "_delivery"
    exposed = json.dumps(dict(state.attributes)) + notice
    for secret in (data["text"], data["request_id"], entry.data["proxy_api_key"],
                   entry.data["webhook_id"], *entry.data["recipients"].values()):
        assert secret not in exposed
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()

    # Fixing configuration admits the same logical request, since rejection
    # did not create an idempotency record. This transport is mocked, never live.
    hass.config_entries.async_update_entry(entry, options={"groups": {"AA-BB": 42}})
    transports["group_metadata"].side_effect = None
    transports["group_metadata"].return_value = {
        "id": 42, "service": "iMessage", "is_group": True,
        "participants": list(entry.data["recipients"].values()),
    }
    transports["imessage_group"].side_effect = None
    transports["imessage_group"].return_value = {"state": "accepted", "transport": "imessage"}
    accepted = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert accepted["results"][0]["state"] == "accepted"
    assert accepted["request_id"] == data["request_id"]
    assert sensor_state(hass, entry).state == "accepted"
    transports["imessage_group"].assert_awaited_once()
    transports["imessage"].assert_not_awaited()
    transports["sms"].assert_not_awaited()


@pytest.mark.parametrize("interface", ["service", "webhook"])
@pytest.mark.parametrize("preview", [True, False])
async def test_invalid_preview_has_no_status_or_notification_side_effects(hass, entry, transports, interface, preview):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {}})
    await setup_entry(hass, entry)
    data = {"text": "Private body", "initials": "AA-BB", "dry_run": preview}
    before = deepcopy(entry.runtime_data.last)
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        await reject(hass, entry, data, interface)
    if preview:
        assert entry.runtime_data.last == before
        assert sensor_state(hass, entry).state == "idle"
        notification.assert_not_called()
    else:
        assert sensor_state(hass, entry).state == "failed"
        notification.assert_called_once()
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("interface", ["service", "webhook"])
@pytest.mark.parametrize("invalid", [
    {"initials": "untrusted@example.invalid"},
    {"request_id": "untrusted request ID with spaces"},
])
async def test_generic_rejection_never_echoes_invalid_inputs(hass, entry, transports, interface, invalid):
    await setup_entry(hass, entry)
    data = {"text": "Private body", "initials": "AA", "request_id": "safe-test-request", **invalid}
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        await reject(hass, entry, data, interface)
    state = sensor_state(hass, entry)
    assert state.state == "failed"
    assert state.attributes["error"]["code"] == "request_validation_failed"
    assert state.attributes["results"][0]["state"] == "rejected"
    assert "target_type" not in state.attributes["results"][0]
    exposed = json.dumps(dict(state.attributes)) + notification.call_args.args[1]
    assert data["text"] not in exposed
    for raw in invalid.values():
        assert raw not in exposed
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("interface", ["service", "webhook"])
async def test_conflicting_request_reports_rejection_without_changing_original(hass, entry, transports, interface):
    transports["imessage"].side_effect = None
    transports["imessage"].return_value = {"state": "accepted", "transport": "imessage"}
    await setup_entry(hass, entry)
    data = {"text": "Original private body", "initials": "AA", "request_id": "stable-conflict-test"}
    original = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    records = deepcopy(entry.runtime_data.manager.records)
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        await reject(hass, entry, {**data, "text": "Changed private body"}, interface,
                     status=409, match="different content")
    assert sensor_state(hass, entry).state == "failed"
    assert entry.runtime_data.last["error"]["code"] == "request_id_conflict"
    notification.assert_called_once()
    assert entry.runtime_data.manager.records == records
    replay = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    assert replay == original
    transports["imessage"].assert_awaited_once()
    transports["group_metadata"].assert_not_awaited()
    transports["sms"].assert_not_awaited()
