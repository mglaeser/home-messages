"""Use the validation backend employed by the running Home Assistant core.

Home Assistant 2026.9 uses voluptuous; 2026.10 switches to probatio. Matching
core's backend keeps field markers, selectors and validation errors compatible.
"""

from homeassistant import data_entry_flow

try:
    schema = data_entry_flow.probatio
except AttributeError:
    import voluptuous as schema

__all__ = ["schema"]
