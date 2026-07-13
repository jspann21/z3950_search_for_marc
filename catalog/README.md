# Managed server catalog

`servers.v2.json` is canonical history. It contains active, quarantined, and retired targets;
publication tooling may omit non-active entries from a future active-only delivery while retaining
them here for auditability.

The daily workflow probes every non-retired endpoint from Windows and Linux. Each probe performs
Z39.50 initialization, a valid Bib-1 search, and MARC validation when hits exist. A valid zero-hit
response is healthy. Failures are recorded by typed category (DNS, connection, initialization,
timeout, diagnostic, malformed response, or record parsing).

Status policy:

- Both runners must fail on seven consecutive daily runs before quarantine.
- Any healthy runner resets the dual-failure count; two successful days restore quarantine.
- Thirty failed days create a retirement candidate and pull request. Automation never retires or
  deletes a server permanently.
- Quarantined and retired definitions remain in canonical history.

After reviewing an automated change, update the catalog version/publication time and run
`tools/publish_catalog.py` with the offline Ed25519 private key for local verification. GitHub
Pages deployment is independent of an application release.

For CI publication, store that PEM as the `CATALOG_SIGNING_KEY` repository secret. The Pages job
builds an active-only signed payload from canonical history; the key is never written to the repo.
