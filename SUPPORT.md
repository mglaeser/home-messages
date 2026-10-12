# Support

Read the [README](README.md) or [German guide](README.de.md) first. For a
reproducible Home Messages bug or a feature request, use
[the issue forms](https://github.com/mglaeser/home-messages/issues/new/choose).
For security vulnerabilities, follow [SECURITY.md](SECURITY.md).

Include your Home Assistant and Home Messages versions, the result state and
reason, whether the target is individual or a group, and a minimal example with
fictional aliases and text. Say whether the failure also occurs when using the
proxy directly, if you already know. A real test message is not required for a
bug report.

Before sharing, remove API tokens, webhook URLs/IDs, recipient numbers, chat
IDs, private hostnames and message contents. Integration diagnostics are
redacted, but HA automation traces and third-party logs may not be.

## Common checks

| Symptom | Check |
| --- | --- |
| Integration absent after installation | Directory is `custom_components/home_messages`; restart HA |
| Proxy unreachable | Base URL is reachable from HA; container loopback is not the host |
| Individual send rejected | Proxy send scope, destination allowlist and macOS permission |
| `group_chat_verification_failed` | Read scope, enabled reads, current chat ID, iMessage group status and exact phone-number participants |
| Group preview works but send fails | Preview is local only; verify the real chat and explicit `chat_id:ID` allowlist entry |
| SMS not used | Fallback is enabled, target is individual, and failure is a recognized pre-submission failure |
| `unknown` result | Inspect the proxy before trying a new request ID; automatic retry could duplicate a message |
| Reused ID reports a conflict | One ID belongs to one exact logical request and destination mapping |

The proxy is an independent dependency: its installation, macOS permissions,
Messages database and API are documented in
[iMessage Proxy](https://github.com/mglaeser/imessage-proxy). Sipgate account and
billing questions belong with Sipgate. Maintainers provide best-effort support
without a service-level guarantee.
