"""Exercise real HA config and options flows without sending messages."""

from homeassistant.config_entries import SOURCE_USER

from custom_components.home_messages.const import DOMAIN

INPUT = {
    "proxy_url": "http://proxy.example:8765",
    "proxy_api_key": "test-key",
    "recipients": "AA=+12025550101\nBB=+12025550102",
    "groups": "BB-AA=chat_id:42",
    "sipgate_enabled": False,
}


async def test_setup_validates_then_creates_entry_without_contacting_proxy(hass, transports):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**INPUT, "proxy_url": ""})
    assert result["errors"] == {"proxy_url": "invalid_url"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"]["groups"] == {"AA-BB": 42}
    assert len(result["data"]["webhook_id"]) >= 40
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_options_preserve_secret_webhook_and_existing_group(hass, entry, transports):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **INPUT,
            "proxy_url": "https://proxy.example",
            "proxy_api_key": "",
            "sipgate_token_id": "",
            "sipgate_token_secret": "",
        },
    )
    assert result["type"] == "create_entry"
    assert entry.options["proxy_api_key"] == entry.data["proxy_api_key"]
    assert entry.options["proxy_url"] == "https://proxy.example"
    assert entry.options["groups"] == {"AA-BB": 42}
    assert "webhook_id" not in entry.options
    assert entry.data["webhook_id"] == "test-private-webhook-id"
    for mock in transports.values():
        mock.assert_not_awaited()


async def test_duplicate_setup_aborts(hass, entry):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "abort"
    assert result["reason"] in {"already_configured", "single_instance_allowed"}
