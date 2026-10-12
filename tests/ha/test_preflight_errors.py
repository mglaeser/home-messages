"""Pre-dispatch failures are visible without sending or reserving request IDs."""

from copy import deepcopy
import json
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from homeassistant.components import webhook
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.util.aiohttp import MockRequest

from custom_components.home_messages.const import DOMAIN


def request(data, *, form=False):
    content_type = "application/x-www-form-urlencoded" if form else "application/json"
    body = (urlencode(data) if form else json.dumps(data)).encode()
    result = MockRequest(body, "home_messages/tests", method="POST", remote="127.0.0.1",
                         headers={"Content-Type": content_type})
    result.content_type = content_type
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
async def test_invalid_group_binding_is_visible_and_does_not_consume_request_id(hass, entry, transports, interface):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {"AA-BB": 0}})
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
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {"AA-BB": None}})
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


@pytest.mark.parametrize("form", [False, True])
async def test_webhook_preview_with_unexpected_field_keeps_status_unchanged(hass, entry, transports, form):
    await setup_entry(hass, entry)
    data = {"text": "Private body", "initials": "AA", "extra": "untrusted extra value",
            "dry_run": "true" if form else True}
    before = deepcopy(entry.runtime_data.last)
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        response = await webhook.async_handle_webhook(
            hass, entry.data["webhook_id"], request(data, form=form)
        )
        await hass.async_block_till_done()
    assert response.status == 400
    assert entry.runtime_data.last == before
    assert sensor_state(hass, entry).state == "idle"
    notification.assert_not_called()
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_form_preview_with_duplicate_other_fields_keeps_status_unchanged(hass, entry, transports):
    await setup_entry(hass, entry)
    data = [("text", "Private body"), ("text", "Duplicate private body"),
            ("initials", "AA"), ("dry_run", "true")]
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        response = await webhook.async_handle_webhook(
            hass, entry.data["webhook_id"], request(data, form=True)
        )
        await hass.async_block_till_done()
    assert response.status == 400
    assert sensor_state(hass, entry).state == "idle"
    assert not entry.runtime_data.last
    notification.assert_not_called()
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_malformed_webhook_json_reports_only_a_safe_error(hass, entry, transports):
    await setup_entry(hass, entry)
    body = b'{"text": "Private malformed body",'
    malformed = MockRequest(body, "home_messages/tests", method="POST", remote="127.0.0.1",
                            headers={"Content-Type": "application/json"})
    malformed.content_type = "application/json"
    malformed.content_length = len(body)
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        response = await webhook.async_handle_webhook(hass, entry.data["webhook_id"], malformed)
        await hass.async_block_till_done()
    assert response.status == 400
    state = sensor_state(hass, entry)
    assert state.state == "failed"
    assert state.attributes["error"]["message"] == "invalid JSON payload; no message sent"
    exposed = json.dumps(dict(state.attributes)) + notification.call_args.args[1] + response.text
    assert "Private malformed body" not in exposed
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("interface", ["service", "webhook_json", "webhook_form"])
@pytest.mark.parametrize("binding_source", ["data", "options"])
async def test_unmapped_group_preview_is_individual_and_side_effect_free(
    hass, entry, transports, interface, binding_source
):
    if binding_source == "options":
        # Empty options override the existing group binding in entry data.
        hass.config_entries.async_update_entry(entry, options={"groups": {}})
    else:
        hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {}})
    await setup_entry(hass, entry)
    data = {"text": "Private preview", "initials": "BB-AA,AA",
            "request_id": "unmapped-preview-123",
            "dry_run": "true" if interface == "webhook_form" else True}
    before = deepcopy(entry.runtime_data.last)
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        if interface == "service":
            result = await hass.services.async_call(
                DOMAIN, "send", data, blocking=True, return_response=True
            )
        else:
            response = await webhook.async_handle_webhook(
                hass, entry.data["webhook_id"],
                request(data, form=interface == "webhook_form"),
            )
            assert response.status == 200
            result = json.loads(response.text)
        await hass.async_block_till_done()
    assert result == {
        "dry_run": True,
        "recipients": [["AA"], ["BB"]],
        "results": [
            {"initials": ["AA"], "target_type": "single", "target": "AA", "state": "dry_run"},
            {"initials": ["BB"], "target_type": "single", "target": "BB", "state": "dry_run"},
        ],
    }
    assert entry.runtime_data.last == before and sensor_state(hass, entry).state == "idle"
    assert not entry.runtime_data.manager.records
    notification.assert_not_called()
    for mock in transports.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("interface", ["service", "webhook_json", "webhook_form"])
async def test_unmapped_group_send_is_visible_and_comma_replay_does_not_repeat(
    hass, entry, transports, interface
):
    hass.config_entries.async_update_entry(entry, data={**entry.data, "groups": {}})
    transports["imessage"].side_effect = None
    transports["imessage"].return_value = {"state": "accepted", "transport": "imessage"}
    await setup_entry(hass, entry)
    data = {"text": "Private identical text", "initials": "BB-AA,AA",
            "request_id": "unmapped-send-123"}
    with patch("homeassistant.components.persistent_notification.async_create") as notification:
        if interface == "service":
            result = await hass.services.async_call(
                DOMAIN, "send", data, blocking=True, return_response=True
            )
        else:
            response = await webhook.async_handle_webhook(
                hass, entry.data["webhook_id"],
                request(data, form=interface == "webhook_form"),
            )
            assert response.status in (200, 202)
            queued = json.loads(response.text)
            assert queued["request_id"] == data["request_id"]
            assert queued["complete"] is (response.status == 200)
        await hass.async_block_till_done()
        if interface != "service":
            result = deepcopy(entry.runtime_data.last)
        replay = await hass.services.async_call(
            DOMAIN, "send", {**data, "initials": "AA,BB"}, blocking=True, return_response=True
        )
        await hass.async_block_till_done()
    assert replay == result
    assert result["complete"] and result["request_id"] == data["request_id"]
    assert [(r["target_type"], r["target"], r["state"]) for r in result["results"]] == [
        ("single", "AA", "accepted"), ("single", "BB", "accepted"),
    ]
    assert sensor_state(hass, entry).state == "accepted"
    calls = transports["imessage"].await_args_list
    assert [(call.args[1], call.args[2]) for call in calls] == [
        ("+12025550101", data["text"]), ("+12025550102", data["text"]),
    ]
    assert calls[0].args[3] != calls[1].args[3]
    assert len(entry.runtime_data.manager.records) == 1
    notification.assert_not_called()
    for name in ("imessage_group", "group_metadata", "sms", "check"):
        transports[name].assert_not_awaited()
    exposed = json.dumps(result)
    for secret in (data["text"], entry.data["proxy_api_key"], entry.data["webhook_id"],
                   *entry.data["recipients"].values()):
        assert secret not in exposed
