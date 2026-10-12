# Changelog

## 1.2.0

- Send selected group members individually when their alias combination has no
  configured chat ID. Hyphen syntax then uses the same routing, phone-number
  deduplication and request replay behavior as comma-separated recipients.
- Apply the existing individual iMessage and optional Sipgate fallback rules to
  these destinations. Configured groups retain their membership checks and never
  fan out after a verification failure or an uncertain send.
- Show the effective individual destinations in previews and delivery results;
  keep malformed configured chat IDs and invalid recipients as validation errors.

## 1.1.2

- Show rejected pre-dispatch requests in the Last delivery sensor and a persistent
  HA notification, including an actionable missing-group configuration error.
- Keep previews free of status changes and notifications. Local rejections do not
  reserve a request ID, alter retained outcomes, or trigger any transport.

## 1.1.1 — Initial public release

- Publish Home Messages as a standalone Home Assistant custom integration with
  HACS metadata, local brand assets, English/German documentation and community
  contribution guidance.
- Provide the `home_messages.send` action and local POST webhook with individual
  destinations separated by commas and existing groups selected with hyphens.
- Configure explicit alias-to-phone and group-to-chat mappings through HA.
  Verify exact group participants before dispatch; group sends never fall back
  to individual messages or SMS.
- Preserve optional Sipgate fallback for recognized pre-submission failures on
  individual destinations, durable request deduplication, last-delivery status,
  failure notifications and redacted diagnostics.
- Retain the `home_messages` domain for existing installations. Earlier versions
  were maintained as part of a private deployment; existing configuration and
  retained individual-request fingerprints remain compatible. Individual
  aliases containing hyphens require an explicit rename because the character
  now separates group members.

The initial public release number follows existing deployment versions; it
does not imply earlier public releases in this repository.
