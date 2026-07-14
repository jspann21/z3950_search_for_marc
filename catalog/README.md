# Managed server catalog

`servers.v2.json` is canonical history. It contains active, quarantined, and retired targets;
publication tooling may omit non-active entries from a future active-only delivery while retaining
them here for auditability.

## July 2026 manual refresh

The 2026-07-13 refresh tested every legacy definition twice on Windows with the application's own
YAZ search, present, and MARC parsing path. It retired 175 obsolete, inaccessible, duplicate, or
non-bibliographic definitions from the searchable catalog, updated seven existing definitions in
place, and added 18 new definitions that passed two additional probes. The resulting catalog keeps
390 historical definitions and publishes 215 active targets; all 215 passed a final clean-catalog
probe.

Connection research used the current
[Library of Congress server guidelines](https://www.loc.gov/standards/z3950/lcserver.html), the
[LOC-referenced Z-BRARY directory](https://www.z-brary.com/), the independently maintained
[KohaSupport directory](https://kohasupport.com/resources/z3950/), and current provider pages such
as [Oxford's Z39.50 configuration](https://www.bodleian.ox.ac.uk/collections-and-resources/solo/z39-50).
Directory entries were discovery inputs only: no endpoint was activated unless it passed the local
protocol and MARC probe. The supported LOC bibliographic targets are first in runtime order: LCDB at
priority 0 and NLSBPH at priority 10.

The weekly workflow probes every non-retired endpoint from Windows and Linux. Each probe performs
Z39.50 initialization, a valid Bib-1 search, and MARC validation when hits exist. A valid zero-hit
response is healthy. Failures are recorded by typed category (DNS, connection, initialization,
timeout, diagnostic, malformed response, or record parsing).

Rolling observations and counters are maintained automatically on the
`automation/catalog-health-state` branch. Raw runner output is retained as a short-lived Actions
artifact and is never committed. A pull request is opened only when the policy proposes an actual
catalog status transition; its body includes runner totals, the affected servers, endpoints,
reasons, and latest observation categories. Runs with no transitions appear only in the Actions
job summary.

Status policy:

- Both runners must fail on seven consecutive weekly runs before quarantine.
- Any healthy runner resets the dual-failure count; two successful weekly runs restore quarantine.
- Thirty failed weekly runs create a retirement candidate in the health report. Automation never
  retires or deletes a server permanently.
- Quarantined and retired definitions remain in canonical history.

After reviewing an automated change, update the catalog version/publication time and run
`tools/publish_catalog.py` with the offline Ed25519 private key for local verification. GitHub
Pages deployment is independent of an application release.

For CI publication, store that PEM as the `CATALOG_SIGNING_KEY` repository secret. The Pages job
builds an active-only signed payload from canonical history; the key is never written to the repo.
