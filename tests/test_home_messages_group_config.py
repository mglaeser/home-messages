"""Offline validation of group bindings and upgrades from individual routing."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "custom_components/home_messages"
spec = importlib.util.spec_from_file_location("group_config_const", ROOT / "const.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

RECIPIENTS = {
    "BB": "+12025550101",
    "CC": "+12025550102",
    "AA": "+12025550103",
}
BASE = {
    "proxy_url": "http://localhost:8765",
    "proxy_api_key": "test-proxy-secret",
    "sipgate_enabled": True,
    "sipgate_token_id": "test-id",
    "sipgate_token_secret": "test-sipgate-secret",
    "sipgate_sms_id": "s0",
    "recipients": RECIPIENTS,
}


def test_existing_configuration_has_no_implicit_groups():
    original = deepcopy(BASE)
    normalized = c.normalize_settings(BASE)
    assert normalized["groups"] == {}
    assert normalized["recipients"] == RECIPIENTS
    assert BASE == original


def test_group_bindings_canonicalize_and_round_trip():
    groups = c.parse_groups(
        "  cc - bb =chat_id:42\n\nAA-CC-BB=43\nCC-AA=chat_id:44", RECIPIENTS
    )
    assert groups == {"AA-BB-CC": 43, "AA-CC": 44, "BB-CC": 42}
    assert c.parse_groups(c.format_groups(groups), RECIPIENTS) == groups
    assert c.parse_groups({"CC-BB": 42}, RECIPIENTS) == {"BB-CC": 42}


def test_options_preserve_secrets_webhook_and_groups_until_explicitly_changed():
    current = c.normalize_settings({**BASE, "groups": "BB-CC=42"})
    current["webhook_id"] = "private-webhook"
    updated = c.normalize_settings(
        {"proxy_api_key": "", "sipgate_token_id": "", "sipgate_token_secret": ""},
        current,
    )
    assert updated["proxy_api_key"] == BASE["proxy_api_key"]
    assert updated["sipgate_token_id"] == BASE["sipgate_token_id"]
    assert updated["sipgate_token_secret"] == BASE["sipgate_token_secret"]
    assert updated["groups"] == {"BB-CC": 42}
    assert "webhook_id" not in updated
    assert current["webhook_id"] == "private-webhook"
    assert c.normalize_settings({"groups": ""}, current)["groups"] == {}


@pytest.mark.parametrize(
    "value,error",
    [
        ("BB=42", "invalid_groups"),
        ("BB--CC=42", "invalid_groups"),
        ("BB,CC=42", "invalid_groups"),
        ("BB-CC=0", "invalid_groups"),
        ("BB-CC=-2", "invalid_groups"),
        ("BB-CC=4.2", "invalid_groups"),
        ("BB-CC=true", "invalid_groups"),
        ("BB-CC=chat_guid:42", "invalid_groups"),
        ("BB-CC=chat_id:9223372036854775808", "invalid_groups"),
        ("BB-CC=" + "9" * 5000, "invalid_groups"),
        ({"BB-CC": True}, "invalid_groups"),
        ({"BB-CC": "42"}, "invalid_groups"),
        ({"BB-CC": 42.0}, "invalid_groups"),
        (False, "invalid_groups"),
        (["BB-CC=42"], "invalid_groups"),
        ("BB-ZZ=42", "unknown_group_alias"),
        ("BB-BB=42", "duplicate_group_recipient"),
        ("BB-CC=42\ncc-bb=43", "duplicate_group"),
        ({"BB-CC": 42, "CC-BB": 43}, "duplicate_group"),
        ("BB-CC=42\nBB-AA=42", "duplicate_group_chat_id"),
    ],
)
def test_invalid_group_binding_blocks_configuration(value, error):
    with pytest.raises(c.SettingsValidationError) as exc:
        c.normalize_settings({**BASE, "groups": value})
    assert exc.value.errors == {"groups": error}
    assert not any(number in str(exc.value) for number in RECIPIENTS.values())


def test_aliases_for_same_number_cannot_form_a_group():
    recipients = {**RECIPIENTS, "CC": RECIPIENTS["BB"]}
    with pytest.raises(c.SettingsValidationError) as exc:
        c.normalize_settings({**BASE, "recipients": recipients, "groups": "BB-CC=42"})
    assert exc.value.errors == {"groups": "duplicate_group_recipient"}


def test_removing_a_recipient_requires_removing_its_group_binding():
    current = c.normalize_settings({**BASE, "groups": "BB-CC=42"})
    with pytest.raises(c.SettingsValidationError) as exc:
        c.normalize_settings({"recipients": {"BB": RECIPIENTS["BB"]}}, current)
    assert exc.value.errors == {"groups": "unknown_group_alias"}


def test_legacy_hyphen_alias_is_explicitly_rejected():
    with pytest.raises(c.SettingsValidationError) as exc:
        c.normalize_settings({**BASE, "recipients": {"BB-CC": RECIPIENTS["BB"]}})
    assert exc.value.errors == {"recipients": "alias_hyphen_reserved"}
