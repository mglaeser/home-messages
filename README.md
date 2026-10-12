# Home Messages

[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mglaeser&repository=home-messages&category=integration)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Send Home Assistant notifications to individual iMessage recipients or existing
iMessage groups, with optional Sipgate SMS fallback for individual recipients.
Call one HA action or a local webhook; keep recipient aliases and credentials in
the integration's configuration.

[Deutsch](README.de.md) · [Changelog](CHANGELOG.md) · [Support](SUPPORT.md)

**Requires a separately installed [iMessage Proxy](https://github.com/mglaeser/imessage-proxy)
on a Mac signed in to Messages.** Home Messages runs inside Home Assistant; it
does not install or manage the Mac service. Home Assistant itself can run on
another machine. Sipgate is optional and disabled by default.

## What it provides

- The `home_messages.send` action and a private, local-only POST webhook.
- Recipient aliases, explicit group bindings, and a preview that sends nothing.
- One **Last delivery** sensor and failure notifications.
- A persisted request ledger to avoid resending a retained request ID.
- Configuration and action descriptions in English and German.

This integration does not read message history, create groups, manage group
membership, or create recipient switches. Automations decide when and to whom
to send. An accepted command does not prove delivery or that someone read it.
The proxy's sender-identifier policy applies to outgoing messages; Home
Messages does not override it.

## Requirements

- Home Assistant **2026.9.1 or newer**.
- A reachable iMessage Proxy compatible with its 1.0 API, installed using its
  [own instructions](https://github.com/mglaeser/imessage-proxy#get-started).
- A proxy API key with `messages:send`; groups also require `messages:read`.
- Intended destinations in the proxy's allowlist.
- For groups: Messages reads enabled and the required macOS permissions granted
  according to the proxy's documentation.
- For optional SMS: a Sipgate account supporting its SMS API, a personal access
  token and an SMS extension ID. SMS may incur charges.

Use a trusted network or a properly configured HTTPS endpoint for the proxy.
HA's address and the proxy's address are different settings; a loopback address
inside an HA container does not reach a service on its host.

## Install

Home Messages can be installed as a **HACS custom repository**. Inclusion in the
default HACS catalog is not yet confirmed.

1. In HACS, open the menu → **Custom repositories**.
2. Add `https://github.com/mglaeser/home-messages`, type **Integration**.
3. Download Home Messages and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → Home Messages**.

For manual installation, copy `custom_components/home_messages` from a
[release](https://github.com/mglaeser/home-messages/releases) to the same path
under your HA configuration directory, then restart and add the integration.
Choose one installation/update method for this directory.

## Configure

The integration supports one configuration entry. Use its **Configure** button
to change settings later. Blank password fields retain saved values; credentials
are never prefilled. Saving the form validates local settings, but does not test
connectivity or send a message.

| Setting | Value |
| --- | --- |
| Proxy URL | Reachable base URL, for example `http://imessage-proxy.local:8765` |
| Proxy API key | Dedicated send key; add read scope for group verification |
| Recipients | One `ALIAS=+internationalnumber` per line |
| Groups | Optional: one `ALIAS-ALIAS=chat_id:ID` per line |
| Sipgate fallback | Off by default; applies only to individual destinations |
| Sipgate credentials | Token ID, token secret, and SMS extension ID, when enabled |

Recipient examples use reserved fictional North American numbers. Replace them
with your own allowlisted recipients before sending:

```text
AA=+12025550101
BB=+12025550102
CC=+12025550103
```

Aliases are case insensitive, start with a letter, and contain letters, digits
or underscores, up to 16 characters. Hyphens separate group members and cannot
be part of an individual alias.

### Individual and group destinations

| `initials` | Result |
| --- | --- |
| `AA,BB` | Two individual messages |
| `AA-BB` | One message to the configured AA/BB group |
| `AA-BB,CC` | One group message and one individual message to CC |
| `AA-BB-CC` | One message to the configured three-recipient group |

`BB-AA` and `AA-BB` identify the same group. Repeated identical destinations are
deduplicated; explicitly selecting a group and one of its members still means
two destinations. Comma order is not a delivery-order guarantee.

Create or find the desired conversation in Messages first. Use the proxy's
chat metadata API to identify its numeric chat ID and confirm its participants.
Then authorize that exact `chat_id:ID` in the proxy and configure, for example:

```text
AA-BB=chat_id:42
AA-BB-CC=chat_id:43
```

The short form `AA-BB=42` also works. These IDs are examples, local to the proxy's
Messages database. Phone-number allowlisting alone does not authorize a group.

Before dispatching any destination in a new request containing groups, Home
Messages reads each chat's metadata and verifies its ID, iMessage service,
group status, and exact set of configured phone numbers. Missing members,
additional members, email-based participants, or unreadable metadata reject
the whole request before sending. This is a check at dispatch time, not an
atomic lock on membership in Messages. Groups never fan out into separate
iMessages or SMS as a fallback.

## Home Assistant actions

Use **Developer tools → Actions** to validate a request without sending:

```yaml
action: home_messages.send
data:
  text: "The washing machine has finished."
  initials: "AA-BB"
  request_id: "washer-cycle-20261012-01"
  dry_run: true
response_variable: delivery
```

Remove `dry_run` or set it to `false` when you intend to send. A preview checks
text, aliases and configured group mappings locally; it does not contact the
proxy, verify live chat membership, or prove allowlist permissions.

`text` must contain 1–4,000 characters and cannot start with `-` or contain
unsupported control characters. `initials` is limited to 256 characters.
Optional `request_id` must be 8–80 characters using letters, digits, `.`, `_`,
`~` or `-`. Use a different ID for every new logical message.

The `home_messages.test_connection` action reads proxy status without sending.
Its Sipgate result only checks whether required configuration fields are set;
it does not authenticate to Sipgate or send a test SMS.

## REST API and Apple Home shortcuts

The standard HA REST service endpoint uses a **Home Assistant token**:

```bash
curl --fail-with-body --request POST \
  --header 'Authorization: Bearer REPLACE_WITH_HA_TOKEN' \
  --header 'Content-Type: application/json' \
  --data '{"text":"Preview only","initials":"AA-BB,CC","dry_run":true}' \
  'http://homeassistant.local:8123/api/services/home_messages/send?return_response'
```

The integration's Configure dialog also displays its private webhook URL. In
Apple Home's **Get Contents of URL**, use that URL with method **POST** and Form
or JSON fields `text` and `initials`. Optional fields are `request_id` and
`dry_run`; no other fields or duplicated form fields are accepted.

```bash
curl --fail-with-body --request POST \
  --header 'Content-Type: application/json' \
  --data '{"text":"Preview only","initials":"AA-BB","dry_run":true}' \
  'http://homeassistant.local:8123/api/webhook/REPLACE_WITH_PRIVATE_WEBHOOK_ID'
```

The webhook is local-only and uses its unguessable URL as a secret. It does not
use the proxy key or an HA Bearer token. Treat the entire URL as a credential.
Home Messages does not configure public ingress or remote access.

For a real webhook send, HTTP **202** means the request is queued, and **200**
means a retained request is already complete. Neither is delivery confirmation.
Reposting the same retained `request_id` and identical request returns its
current result without another send. A conflicting reuse returns **409**.

## Results, fallback and retries

The action returns one result per destination, including `initials`,
`target_type` (`single` or `group`), `target`, `state`, and available transport
details. `complete: true` means processing ended, not that every result succeeded.
Check each result's `state`. The Last delivery sensor summarizes the latest
request as `idle`, `pending`, `accepted`, `failed` or `unknown`.

For individual destinations, enabled Sipgate fallback is attempted once after
a connection failure before submission or a recognized proxy pre-send failure.
Authentication/allowlist rejection and uncertain outcomes do not trigger SMS.
Group sends use only iMessage. Mixed requests are not transactional: a later
transport failure does not undo earlier accepted destinations.

The private HA ledger is persisted and checked before dispatch. It holds at
most 1,000 request records; completed older records are evicted as new requests
arrive. At most 25 incomplete requests are admitted. Interrupted requests are
marked uncertain after restart and are not automatically resumed. The same ID
only deduplicates while its record remains; removing the integration, losing
its storage, or reusing an evicted ID can defeat deduplication. This is not an
exactly-once delivery guarantee. After an uncertain result, investigate before
creating a new request ID.

## Privacy and troubleshooting

Credentials, recipient mappings and group bindings live in HA's private
configuration. The ledger excludes message text, phone numbers and chat IDs,
but retains request IDs, aliases, routing outcomes and a request fingerprint.
The sensor exposes result metadata; HA recorder/history may retain it. HA
automation traces, API clients and the proxy may retain their own request data.
Use non-sensitive request IDs and redact traces before sharing. Integration
diagnostics redact credentials, endpoint URL, webhook ID and destination maps.

If a send fails, check the individual result and failure notification, then
the proxy's status, key scopes, allowlist and macOS permissions. For
`group_chat_verification_failed`, compare current chat participants with the
configured phone numbers. An email identity is not treated as an equivalent
phone number. See [Support](SUPPORT.md) and [Security](SECURITY.md).

## Updates and removal

Back up HA before updating, read the release notes, and update using the same
method used to install. Wait for active sends to finish before reloading or
restarting. Existing installations keep the `home_messages` domain and their
configuration; legacy aliases containing hyphens must be renamed explicitly.

If an unload or reload is attempted during an active request, Home Messages
refuses it and HA marks the entry `failed_unload`. Let the request finish, then
restart HA; another unload/reload cannot recover that state.

To remove, disable callers, wait for sends to finish, delete the Home Messages
entry in **Devices & services**, remove its files using HACS or your manual
installation method, and restart HA. Revoke the dedicated proxy key if it is no
longer needed. This does not uninstall the Mac proxy or delete Messages chats.
Backups and HA traces may still retain older data.

## Community and license

Contributions are welcome; see [Contributing](CONTRIBUTING.md), the
[Code of Conduct](CODE_OF_CONDUCT.md), and [Security policy](SECURITY.md).
Licensed under [Apache-2.0](LICENSE). Copyright 2026 Marian Klee.

Independent community software. Home Assistant, Apple, iMessage, macOS and
Sipgate names identify compatible products and do not imply endorsement.
