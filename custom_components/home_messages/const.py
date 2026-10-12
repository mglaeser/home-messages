"""Constants and pure configuration validation for Home Messages."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
from urllib.parse import urlsplit

DOMAIN = "home_messages"
NAME = "Home Messages"

CONF_PROXY_URL = "proxy_url"
CONF_PROXY_API_KEY = "proxy_api_key"
CONF_SIPGATE_ENABLED = "sipgate_enabled"
CONF_SIPGATE_TOKEN_ID = "sipgate_token_id"
CONF_SIPGATE_TOKEN_SECRET = "sipgate_token_secret"
CONF_SIPGATE_SMS_ID = "sipgate_sms_id"
CONF_RECIPIENTS = "recipients"
CONF_GROUPS = "groups"
CONF_WEBHOOK_ID = "webhook_id"

SERVICE_SEND = "send"
SERVICE_TEST_CONNECTION = "test_connection"

DEFAULT_PROXY_URL = ""
DEFAULT_SIPGATE_ENABLED = False
DEFAULT_RECIPIENTS = ""
DEFAULT_GROUPS = ""

SECRET_KEYS = (
    CONF_PROXY_API_KEY,
    CONF_SIPGATE_TOKEN_ID,
    CONF_SIPGATE_TOKEN_SECRET,
)
SETTING_KEYS = (
    CONF_PROXY_URL,
    *SECRET_KEYS,
    CONF_SIPGATE_ENABLED,
    CONF_SIPGATE_SMS_ID,
    CONF_RECIPIENTS,
    CONF_GROUPS,
)

_ALIAS = re.compile(r"[A-Z][A-Z0-9_]{0,15}")
_E164 = re.compile(r"\+[1-9][0-9]{6,14}")


class SettingsValidationError(ValueError):
    """Validation errors keyed by field, without any submitted values."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("Invalid Home Messages configuration")


def parse_recipients(value: str | Mapping[str, str]) -> dict[str, str]:
    """Normalize an alias=E.164 text block or mapping; reject duplicate aliases.

    Empty lines are ignored. Aliases are case insensitive. No invalid line is
    silently discarded. ValueError contains an error code, never a phone number.
    """
    if isinstance(value, str):
        pairs: list[tuple[str, str]] = []
        for line in value.splitlines():
            if not line.strip():
                continue
            if line.count("=") != 1:
                raise ValueError("invalid_recipients")
            alias, number = line.split("=", 1)
            pairs.append((alias, number))
    elif isinstance(value, Mapping):
        pairs = list(value.items())
    else:
        raise ValueError("invalid_recipients")

    recipients: dict[str, str] = {}
    for alias, number in pairs:
        if not isinstance(alias, str) or not isinstance(number, str):
            raise ValueError("invalid_recipients")
        alias, number = alias.strip().upper(), number.strip()
        if "-" in alias:
            raise ValueError("alias_hyphen_reserved")
        if not _ALIAS.fullmatch(alias) or not _E164.fullmatch(number):
            raise ValueError("invalid_recipients")
        if alias in recipients:
            raise ValueError("duplicate_alias")
        recipients[alias] = number
    if not recipients:
        raise ValueError("empty_recipients")
    return recipients


def format_recipients(value: str | Mapping[str, str]) -> str:
    """Format stored recipients for the native multiline UI field."""
    if isinstance(value, str):
        return value
    return "\n".join(f"{alias}={number}" for alias, number in value.items())


def parse_groups(
    value: str | Mapping[str, int], recipients: Mapping[str, str]
) -> dict[str, int]:
    """Map canonical alias sets to existing, explicitly authorized chat IDs.

    A group needs at least two distinct aliases and phone numbers. Canonical
    order prevents reversed spellings from concealing duplicate mappings.
    This only validates configuration; it neither creates nor authorizes chats.
    """
    if isinstance(value, str):
        pairs: list[tuple[str, Any]] = []
        for line in value.splitlines():
            if not line.strip():
                continue
            if line.count("=") != 1:
                raise ValueError("invalid_groups")
            group, raw_id = line.split("=", 1)
            raw_id = raw_id.strip()
            if raw_id.startswith("chat_id:"):
                raw_id = raw_id[len("chat_id:"):]
            if len(raw_id) > 19 or not re.fullmatch(r"[0-9]+", raw_id):
                raise ValueError("invalid_groups")
            pairs.append((group, int(raw_id)))
    elif isinstance(value, Mapping):
        pairs = list(value.items())
    else:
        raise ValueError("invalid_groups")

    groups: dict[str, int] = {}
    for group, chat_id in pairs:
        if not isinstance(group, str) or type(chat_id) is not int:
            raise ValueError("invalid_groups")
        aliases = [alias.strip().upper() for alias in group.split("-")]
        if (
            len(aliases) < 2
            or any(not _ALIAS.fullmatch(alias) for alias in aliases)
            or not 1 <= chat_id <= 9223372036854775807
        ):
            raise ValueError("invalid_groups")
        if len(set(aliases)) != len(aliases):
            raise ValueError("duplicate_group_recipient")
        if any(alias not in recipients for alias in aliases):
            raise ValueError("unknown_group_alias")
        if len({recipients[alias] for alias in aliases}) != len(aliases):
            raise ValueError("duplicate_group_recipient")
        canonical = "-".join(sorted(aliases))
        if canonical in groups:
            raise ValueError("duplicate_group")
        if chat_id in groups.values():
            raise ValueError("duplicate_group_chat_id")
        groups[canonical] = chat_id
    return dict(sorted(groups.items()))


def format_groups(value: str | Mapping[str, int]) -> str:
    """Format stored group bindings for the multiline configuration field."""
    if isinstance(value, str):
        return value
    return "\n".join(f"{group}=chat_id:{chat_id}" for group, chat_id in sorted(value.items()))


def normalize_settings(
    user_input: Mapping[str, Any], current: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Validate UI input and preserve saved secrets when inputs are blank.

    Returns only editable settings; webhook_id is deliberately excluded so that
    changing recipients or credentials cannot replace the webhook URL.
    """
    current = current or {}
    values = {key: user_input.get(key, current.get(key)) for key in SETTING_KEYS}
    errors: dict[str, str] = {}

    raw_url = values.get(CONF_PROXY_URL, "")
    url = raw_url.strip().rstrip("/") if isinstance(raw_url, str) else ""
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
        # Accessing port validates malformed and out-of-range port values.
        parsed.port
    except ValueError:
        valid_url = False
    if not valid_url:
        errors[CONF_PROXY_URL] = "invalid_url"
    values[CONF_PROXY_URL] = url

    for key in SECRET_KEYS:
        incoming = user_input.get(key)
        if incoming is None or (isinstance(incoming, str) and not incoming.strip()):
            values[key] = current.get(key, "")
        elif isinstance(incoming, str):
            values[key] = incoming.strip()
        else:
            values[key] = ""
            errors[key] = "invalid_value"
    if not values[CONF_PROXY_API_KEY]:
        errors[CONF_PROXY_API_KEY] = "required_secret"

    enabled = values.get(CONF_SIPGATE_ENABLED)
    if not isinstance(enabled, bool):
        errors[CONF_SIPGATE_ENABLED] = "invalid_value"
    raw_sms_id = values.get(CONF_SIPGATE_SMS_ID)
    values[CONF_SIPGATE_SMS_ID] = raw_sms_id.strip() if isinstance(raw_sms_id, str) else ""
    if enabled:
        for key in (CONF_SIPGATE_TOKEN_ID, CONF_SIPGATE_TOKEN_SECRET, CONF_SIPGATE_SMS_ID):
            if not values[key]:
                errors[key] = "sipgate_required"

    try:
        values[CONF_RECIPIENTS] = parse_recipients(values.get(CONF_RECIPIENTS))
    except ValueError as err:
        errors[CONF_RECIPIENTS] = str(err)

    if CONF_RECIPIENTS not in errors:
        try:
            values[CONF_GROUPS] = parse_groups(
                DEFAULT_GROUPS if values.get(CONF_GROUPS) is None else values[CONF_GROUPS],
                values[CONF_RECIPIENTS],
            )
        except ValueError as err:
            errors[CONF_GROUPS] = str(err)

    if errors:
        raise SettingsValidationError(errors)
    return values
