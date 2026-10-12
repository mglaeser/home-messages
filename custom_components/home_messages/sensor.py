"""Delivery outcome without exposing credentials or message contents in states."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from . import SIGNAL
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeliverySensor(entry)])


class DeliverySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "last_delivery"
    _attr_icon = "mdi:message-check-outline"
    _attr_should_poll = False

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = entry.entry_id + "_last_delivery"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Messages", manufacturer="Home Messages")

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL, self.async_write_ha_state))

    @property
    def native_value(self):
        last = self.entry.runtime_data.last
        if not last:
            return "idle"
        if last.get("phase") == "preflight" and last.get("error"):
            return "failed"
        if not last.get("complete"):
            return "pending"
        states = {r["state"] for r in last["results"]}
        if states == {"accepted"}:
            return "accepted"
        return "unknown" if "unknown" in states else "failed"

    @property
    def extra_state_attributes(self):
        return self.entry.runtime_data.last
