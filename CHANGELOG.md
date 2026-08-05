# Changelog

## 2.0.1 — 2026-08-05

### Added

- Optional application-update checks at startup using the latest published GitHub release.
- Manual application-update checks from Settings and the Help menu.
- A notification that links to the GitHub release page when a newer version is available. The
  application does not download or install updates automatically.
- Actionable catalog-health review summaries with runner totals, affected endpoints, transition
  reasons, and observations.

### Changed

- Settings storage now preserves the application-update preference and disabled server IDs.
- The Windows installer remembers a user-selected installation directory for future upgrades.
- Installer validation now verifies that installing over an existing copy retains application
  settings, user data, the saved project location, and the installed executable location.
- Catalog health checks now run weekly, retain rolling counters on a bot-only state branch, and open
  a focused review PR only when a server crosses a quarantine or recovery threshold.
- Catalog health review PRs omit raw probe artifacts and avoid whole-catalog formatting changes.
- Windows installer packaging is gated to relevant changes while release tags always receive a
  freshly built and tested installer.

### Upgrade notes

Install the 2.0.1 MSI over the existing installation. Settings, cached and custom catalogs, disabled
servers, and the configured save/project directory under `%LOCALAPPDATA%\Z3950MarcSearch` are
preserved during the upgrade.

## 2.0.0 — 2026-07-13

- Initial self-contained Windows release with embedded YAZ, signed server-catalog updates, parallel
  Z39.50 search, MARC inspection and export, local settings, and light/dark themes.
