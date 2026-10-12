"""Diagnostics excluding credentials, webhook URLs, recipients, and chat IDs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_GROUPS,
    CONF_PROXY_URL,
    CONF_RECIPIENTS,
    CONF_SIPGATE_SMS_ID,
    CONF_WEBHOOK_ID,
    SECRET_KEYS,
)

_REDACT = {
    CONF_GROUPS, CONF_PROXY_URL, CONF_RECIPIENTS, CONF_SIPGATE_SMS_ID,
    CONF_WEBHOOK_ID, *SECRET_KEYS,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return configuration only; never include message or delivery history."""
    return {
        "version": entry.version,
        "data": async_redact_data(dict(entry.data), _REDACT),
        "options": async_redact_data(dict(entry.options), _REDACT),
    }
