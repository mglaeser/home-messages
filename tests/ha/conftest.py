"""Real Home Assistant fixtures; all message transports are mocked."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_messages.const import DOMAIN
from custom_components.home_messages.delivery import Transport

CONFIG = {
    "proxy_url": "http://proxy.example:8765",
    "proxy_api_key": "test-proxy-key",
    "sipgate_enabled": False,
    "sipgate_token_id": "",
    "sipgate_token_secret": "",
    "sipgate_sms_id": "",
    "recipients": {"AA": "+12025550101", "BB": "+12025550102"},
    "groups": {"AA-BB": 42},
    "webhook_id": "test-private-webhook-id",
}


@pytest.fixture(autouse=True)
def enable_local_components(enable_custom_integrations):
    """Let the HA loader discover this repository's custom component."""
    yield


@pytest.fixture
def hass_config_dir(tmp_path):
    """Keep the real atomic ledger under a disposable test directory."""
    return str(tmp_path)


@pytest.fixture
def hass_storage():
    """Use real Store I/O instead of the plugin's in-memory storage patch.

Home Messages verifies committed ledger bytes before dispatch. An in-memory
Store mock would bypass the behavior these lifecycle tests need to exercise.
    """
    return {}


@pytest.fixture(autouse=True)
def transports():
    """Unexpected message attempts fail locally, never reach a network."""
    names = ("imessage", "imessage_group", "sms", "group_metadata", "check")
    mocks = {name: AsyncMock(side_effect=AssertionError("Unexpected transport call")) for name in names}
    patches = [patch.object(Transport, name, mock) for name, mock in mocks.items()]
    for item in patches:
        item.start()
    yield mocks
    for item in reversed(patches):
        item.stop()


@pytest.fixture
def entry(hass):
    """A realistic config entry with a stable private webhook capability."""
    result = MockConfigEntry(domain=DOMAIN, title="Home Messages", unique_id=DOMAIN, data=deepcopy(CONFIG))
    result.add_to_hass(hass)
    return result
