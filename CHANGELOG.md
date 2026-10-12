# Changelog

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
