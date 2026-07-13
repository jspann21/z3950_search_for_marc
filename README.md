# Z39.50 MARC Search 2.0

A Windows-first desktop application that searches many Z39.50 library targets, displays MARC
records, and exports valid ISO2709 `.mrc` files. Version 2 is self-contained: the MSI includes
Python, Qt, YAZ, and the native runtime libraries it needs. End users do not install Python,
`yaz-client`, or a Visual C++ redistributable separately.

## What changed in 2.0

- PySide6 model/view UI with incremental results, sorting, keyboard navigation, activity details,
  cancellation, and retained result-set navigation.
- YAZ 5.37.3 embedded through its native asynchronous ZOOM C API and a compiled CFFI adapter.
  There are no subprocesses and no console-text parsing.
- Exact ISO2709 bytes are retained for every fetched record. PyMARC 5.4 handles MARC-8/UTF-8
  parsing and valid serialization.
- Versioned, schema-validated server catalog with signed independent updates, custom-server
  overlays, local disabled IDs, offline fallback, and conservative two-runner health automation.
- Atomic JSON settings under `%LOCALAPPDATA%\Z3950MarcSearch`, including one-time migration from
  the former Qt settings. The obsolete YAZ executable setting is intentionally ignored.

## Search and export behavior

Search by ISBN-10/ISBN-13 or by title and author, choose USA and/or worldwide targets, then select
any successful server to view its first result. Previous and Next navigate the live retained ZOOM
result set. One failed server never aborts the remaining targets.

The export mode is always shown in the record panel:

- **Original export** writes the exact bytes received from the server.
- **Trimmed export** clones the parsed record, removes tags `000–009` and `900+`, and serializes a
  new valid ISO2709 record. Display trimming uses the same policy.

Defaults are 12 concurrent targets, a five-second target timeout, both location groups, Downloads
as the export directory, automatic catalog updates, and trimming enabled.

## Run from source

Development uses Python 3.14 and the committed `uv.lock`:

```powershell
uv python install 3.14
uv sync --locked --extra dev
./scripts/build_yaz.ps1
uv run z3950-search
```

`build_yaz.ps1` downloads the pinned YAZ source archive, verifies its SHA-256 digest, builds the
x64 DLL and test server with Visual Studio Build Tools, and compiles the CFFI extension. The
resulting binaries are build artifacts and are intentionally not committed.

## Verification

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not native"
uv run pytest -m native
uv run python -m z3950_search_for_marc --self-test
```

The native tests start the pinned local `yaz-ztest` target and exercise initialization, concurrent
target isolation, search, present, raw-record retrieval, navigation, and cleanup without relying
on a public server.

## Server catalog

The bundled catalog is [`catalog/servers.v2.json`](catalog/servers.v2.json), validated by
[`catalog/servers.v2.schema.json`](catalog/servers.v2.schema.json). Its 372 migrated endpoints have
stable UUIDs, numeric ports, normalized endpoint uniqueness, status history, charset metadata, and
Library of Congress priority.

At most once every 24 hours—or when the user chooses Check now—the application fetches the
manifest from the configured GitHub Pages HTTPS origin. It validates the final origin, Ed25519
signature, SHA-256 digest, schema compatibility, IDs, ports, and duplicates before atomically
installing the cache. Startup uses the cached last-known-good catalog, then the bundled catalog.
A bad download cannot replace either.

Legacy JSON arrays can be imported from Settings. They are converted to a separate v2 custom
catalog and are never used as live upstream storage. Local disabled IDs are also kept in their own
file. No user queries or failure telemetry are collected.

Catalog maintainers can sign a publication with:

```powershell
uv run python tools/publish_catalog.py `
  --private-key path/to/catalog-private-key.pem
```

The private Ed25519 key must remain outside source control. See
[`catalog/README.md`](catalog/README.md) for health and release policy.

## Windows MSI

```powershell
./scripts/package_windows.ps1
```

This performs a locked sync, rebuilds YAZ, creates a Nuitka standalone directory, runs the
packaged `--self-test`, and wraps it in `dist/Z3950MarcSearch-2.0.0-x64.msi` with WiX. CI repeats
the clean build and publishes the MSI, checksums, standalone inspection artifact, GPL license, and
YAZ notice. Application auto-update is deliberately outside 2.0; server catalog updates are
independent.

The MSI is per-user and does not require administrator rights; it installs under
`%LOCALAPPDATA%\Programs\Z39.50 MARC Search` and adds a Start menu shortcut.

Uninstall removes application-owned `%LOCALAPPDATA%\Z3950MarcSearch` data by default. An
administrator can explicitly retain it with `PRESERVEUSERDATA=1` on the `msiexec /x` command.

## Architecture

- `domain/`: immutable Qt-free requests, sessions, records, settings, results, and failures.
- `infrastructure/`: native ZOOM engine, atomic persistence, catalog verification, and app paths.
- `ui/`, `widgets.py`, and `dialogs.py`: Qt models, views, and accessible controls.
- `search.py`: the dedicated worker that owns all native YAZ handles.
- `catalog_health.py`: scheduled probes and quarantine/recovery policy.
- `native/`, `scripts/`, and `installer/`: reproducible native and MSI delivery.

The preserved passing 1.0 implementation is available on `codex/legacy-python-baseline`; 2.0 is
built on `codex/rebuild-v2`.

## License

GNU GPL v3.0. YAZ is redistributed under its BSD license; see the packaged `YAZ-LICENSE.txt`.
