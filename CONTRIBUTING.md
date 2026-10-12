# Contributing

Thank you for helping improve Home Messages. Start with an issue for a bug or
proposal, and keep each pull request focused on one problem. See
[Support](SUPPORT.md) for setup questions and [Security](SECURITY.md) for private
vulnerability reports. Participation follows our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development

The integration is in `custom_components/home_messages`. Tests use synthetic
recipients and simulated transports. Never add API keys, webhook IDs, actual
phone numbers, private hostnames, message contents, HA backups or live ledgers
to this repository.

Use the Python version declared in CI and isolated virtual environments. Run
the pure routing and transport tests with:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest -q \
  tests/test_home_messages_delivery.py \
  tests/test_home_messages_transport.py \
  tests/test_home_messages_group_config.py
```

HA lifecycle/configuration tests use their own pinned dependencies:

```bash
python3 -m venv .venv-ha
.venv-ha/bin/python -m pip install -r requirements_test_ha.txt
.venv-ha/bin/python -m pytest -q tests/ha
```

Follow the CI workflow for additional checks. HACS and Hassfest validate
integration metadata separately.
CI must not send real iMessages or SMS, access a live Messages database, or need
private credentials. Network behavior belongs behind an injectable transport.

## Changes that need particular care

- Keep the `home_messages` domain and existing config entry identity stable.
- Preserve old request fingerprints and durable-ledger replay behavior when
  changing routing. Test upgrades as well as fresh configuration.
- Resolve and validate the complete destination plan before sending. Only an
  absent binding for the exact alias set expands a hyphenated selection to the
  normal individual destinations, with the same deduplication and fingerprints
  as comma syntax. Test mixed selections and effective preview results.
- Existing group bindings must remain strict: invalid bindings are errors, and
  configured groups require membership verification before any dispatch. Never
  fan out a configured group after metadata/proxy/send errors or an uncertain
  outcome; these are not reasons to choose individual routing.
- SMS fallback is allowed only for individual destinations after an explicitly
  recognized pre-submission failure. Unknown outcomes must not trigger a retry.
- Keep English and German configuration/action descriptions consistent.
- Retain diagnostics redaction and avoid putting secrets or message text in
  logs, entities, exception messages or persisted request records.
- Do not claim an API, compatibility level, release status or test result that
  has not been verified.

When changing user-facing behavior, update both READMEs and the changelog.
Include meaningful regression tests for failure paths and explain any
compatibility impact. Existing tests are not a substitute for checking the HA
configuration flow and lifecycle when those change.

## Pull requests and releases

Describe the problem, the resulting behavior and the checks you ran. Disclose
known limitations; do not include private logs. Maintainers review and merge
changes and publish releases after CI passes. A version bump must agree with
the integration manifest and release notes. HACS catalog submission requires
successful validation with no disabled checks and a release created afterwards.

Contributions are accepted under the [Apache License 2.0](LICENSE). You must
have the right to contribute your changes. Retain applicable attribution when
including third-party material. Assistance from code-generation tools does not
replace understanding, testing and taking responsibility for a contribution.
