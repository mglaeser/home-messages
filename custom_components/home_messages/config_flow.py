"""UI setup and configuration for Home Messages."""

from __future__ import annotations

from collections.abc import Mapping
import secrets
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from ._schema import schema as vol
from .const import (
    CONF_GROUPS,
    CONF_PROXY_API_KEY,
    CONF_PROXY_URL,
    CONF_RECIPIENTS,
    CONF_SIPGATE_ENABLED,
    CONF_SIPGATE_SMS_ID,
    CONF_SIPGATE_TOKEN_ID,
    CONF_SIPGATE_TOKEN_SECRET,
    CONF_WEBHOOK_ID,
    DEFAULT_PROXY_URL,
    DEFAULT_GROUPS,
    DEFAULT_RECIPIENTS,
    DEFAULT_SIPGATE_ENABLED,
    DOMAIN,
    NAME,
    SettingsValidationError,
    format_groups,
    format_recipients,
    normalize_settings,
)


def settings_schema(values: Mapping[str, Any] | None = None) -> vol.Schema:
    """Build the form without placing saved or submitted secrets into it."""
    values = values or {}
    password = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    return vol.Schema(
        {
            vol.Required(
                CONF_PROXY_URL,
                default=values.get(CONF_PROXY_URL, DEFAULT_PROXY_URL),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Optional(CONF_PROXY_API_KEY): password,
            vol.Required(
                CONF_RECIPIENTS,
                default=format_recipients(values.get(CONF_RECIPIENTS, DEFAULT_RECIPIENTS)),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_GROUPS,
                default=format_groups(values.get(CONF_GROUPS, DEFAULT_GROUPS)),
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_SIPGATE_ENABLED,
                default=values.get(CONF_SIPGATE_ENABLED, DEFAULT_SIPGATE_ENABLED),
            ): BooleanSelector(),
            vol.Optional(CONF_SIPGATE_TOKEN_ID): password,
            vol.Optional(CONF_SIPGATE_TOKEN_SECRET): password,
            vol.Optional(
                CONF_SIPGATE_SMS_ID, default=values.get(CONF_SIPGATE_SMS_ID, "")
            ): TextSelector(),
        }
    )


class HomeMessagesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single Home Messages config entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Expose all editable settings via the integration's Configure button."""
        return HomeMessagesOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect configuration without sending a message."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = normalize_settings(user_input)
            except SettingsValidationError as err:
                errors = err.errors
            else:
                data[CONF_WEBHOOK_ID] = secrets.token_urlsafe(32)
                return self.async_create_entry(title=NAME, data=data)

        return self.async_show_form(
            step_id="user", data_schema=settings_schema(user_input), errors=errors
        )


class HomeMessagesOptionsFlow(OptionsFlow):
    """Update settings, preserving blank secrets and the existing webhook ID."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit configuration using native password and multiline fields."""
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                options = normalize_settings(user_input, current)
            except SettingsValidationError as err:
                errors = err.errors
            else:
                return self.async_create_entry(title="", data=options)

        displayed = {**current, **(user_input or {})}
        webhook_path = f"/api/webhook/{self.config_entry.data[CONF_WEBHOOK_ID]}"
        try:
            local_url = get_url(
                self.hass, allow_external=False, allow_cloud=False, prefer_external=False
            )
        except NoURLAvailableError:
            webhook_url = webhook_path
        else:
            webhook_url = f"{local_url.rstrip('/')}{webhook_path}"
        return self.async_show_form(
            step_id="init",
            data_schema=settings_schema(displayed),
            errors=errors,
            description_placeholders={"webhook_url": webhook_url},
        )
