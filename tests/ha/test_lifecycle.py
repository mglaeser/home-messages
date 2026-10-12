"""Verify services, webhook restrictions, durable replay and unload in HA."""

import json
from pathlib import Path

import pytest
from homeassistant.components import webhook
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.util.aiohttp import MockRequest

from custom_components.home_messages.const import DOMAIN
from custom_components.home_messages.delivery import prepare


def request(data, *, method="POST", remote="127.0.0.1"):
    """Use HA's own request helper without opening a listening socket."""
    body = json.dumps(data).encode()
    result = MockRequest(body, "home_messages/tests", method=method, remote=remote,
                         headers={"Content-Type": "application/json"})
    result.content_type = "application/json"
    result.content_length = len(body)
    return result


async def setup_entry(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_service_and_webhook_have_identical_local_dry_run(hass, entry, transports):
    await setup_entry(hass, entry)
    data = {"text": "Preview", "initials": "BB-AA", "dry_run": True}
    service = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    response = await webhook.async_handle_webhook(hass, entry.data["webhook_id"], request(data))
    assert response.status == 200
    assert json.loads(response.text) == service
    assert service["results"][0]["target"] == "AA-BB"
    assert service["results"][0]["target_type"] == "group"
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_webhook_only_allows_local_post(hass, entry, transports):
    await setup_entry(hass, entry)
    data = {"text": "Must not send", "initials": "AA"}
    bad_method = await webhook.async_handle_webhook(hass, entry.data["webhook_id"], request(data, method="GET"))
    assert bad_method.status == 405
    remote = await webhook.async_handle_webhook(hass, entry.data["webhook_id"], request(data, remote="8.8.8.8"))
    assert remote.status == 200  # HA intentionally does not disclose webhook presence.
    assert not entry.runtime_data.manager.records
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_completed_send_persists_without_contents_and_replays_after_reload(hass, entry, transports):
    transports["imessage"].side_effect = None
    transports["imessage"].return_value = {"state": "accepted", "transport": "imessage"}
    await setup_entry(hass, entry)
    data = {"text": "Private message body", "initials": "AA", "request_id": "stable-test-request"}
    first = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert first["complete"] and first["results"][0]["state"] == "accepted"
    sensor_id = entity_registry.async_get(hass).async_get_entity_id("sensor", DOMAIN, entry.entry_id + "_last_delivery")
    assert hass.states.get(sensor_id).state == "accepted"
    ledger = Path(hass.config.path(".storage", f"{DOMAIN}.{entry.entry_id}.requests")).read_text()
    assert "Private message body" not in ledger and "+12025550101" not in ledger
    assert await hass.config_entries.async_unload(entry.entry_id)
    await setup_entry(hass, entry)
    replay = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    assert replay == first
    transports["imessage"].assert_awaited_once()
    transports["group_metadata"].assert_not_awaited()
    transports["sms"].assert_not_awaited()


async def test_pending_request_recovers_unknown_without_resubmission(hass, entry, transports):
    await setup_entry(hass, entry)
    data = {"text": "Interrupted", "initials": "AA-BB", "request_id": "interrupted-request"}
    plan = prepare(entry.runtime_data.settings, data["text"], data["initials"])
    await entry.runtime_data.manager.reserve(plan, data["request_id"])
    assert await hass.config_entries.async_unload(entry.entry_id)
    await setup_entry(hass, entry)
    result = await hass.services.async_call(DOMAIN, "send", data, blocking=True, return_response=True)
    assert result["complete"]
    assert result["results"][0]["state"] == "unknown"
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_active_request_blocks_unload_and_idle_unload_unregisters_webhook(hass, entry):
    await setup_entry(hass, entry)
    entry.runtime_data.active = 1
    assert not await hass.config_entries.async_unload(entry.entry_id)
    entry.runtime_data.active = 0
    assert await hass.config_entries.async_unload(entry.entry_id)
    response = await webhook.async_handle_webhook(
        hass, entry.data["webhook_id"], request({"text": "Preview", "initials": "AA", "dry_run": True})
    )
    assert response.status == 200 and not response.text
    with pytest.raises(HomeAssistantError, match="not configured"):
        await hass.services.async_call(DOMAIN, "send", {"text": "Preview", "initials": "AA", "dry_run": True},
                                       blocking=True, return_response=True)
