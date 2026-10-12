# Security

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/mglaeser/home-messages/security/advisories/new)
for vulnerabilities in Home Messages. If private reporting is unavailable,
open a minimal issue asking for a private reporting channel. Do not include
exploit details, credentials, phone numbers, webhook URLs or message content
until a private channel is established.

Include the affected version, a minimal reproduction using synthetic data,
the expected security boundary, and the observed impact. Do not test against
systems or recipients you do not control. Report issues in the separate Mac
service using the [iMessage Proxy security policy](https://github.com/mglaeser/imessage-proxy/blob/main/SECURITY.md).

Security fixes target the latest stable release. Older releases may not receive
backports. This volunteer project does not promise a response or resolution
deadline.

## Security model

- The HA REST service uses Home Assistant authentication. The local webhook
  uses its private URL as a bearer secret and is registered as local-only.
- Protect HA configuration, backups, automation traces and the machine running
  the proxy. This integration is not a boundary against an HA administrator or
  a compromised host.
- Use a dedicated proxy key. Individual sends need `messages:send`; group
  verification also needs `messages:read`. An administrator key is unnecessary.
- Group metadata is checked against configured phone numbers before dispatch.
  This neither creates a chat nor makes membership changes atomic with a send.
- The proxy enforces its own destination allowlist. SMS fallback is a separate,
  explicitly enabled path through Sipgate; groups never use that path.
- HTTP protects neither credentials nor contents in transit. Use a trusted
  network or configure HTTPS. This integration does not provide TLS termination.
- Request deduplication is bounded by retained local storage and does not
  guarantee exactly-once delivery. Investigate uncertain outcomes before retrying
  with a new ID.

The integration does not read chat history. Its own ledger excludes text,
phone numbers and chat IDs, but other components—including HA traces, clients,
the proxy and Sipgate—have separate retention and access policies. Review and
redact diagnostic material before sharing it.
