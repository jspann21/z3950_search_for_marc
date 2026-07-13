# Z39.50 MARC Search

A Windows-first desktop application for searching many Z39.50 library servers, reviewing
MARC records, and exporting individual records as binary `.mrc` files.

The application supports ISBN and title/author searches, incremental results, USA and worldwide
server filters, on-demand record navigation, cancelable concurrent queries, persistent settings,
custom server catalogs, and optional MARC field trimming.

## Requirements

- Windows 10 or later for the packaged application
- Python 3.12 or later when running from source
- [Index Data YAZ](https://www.indexdata.com/resources/software/yaz/) with `yaz-client`

YAZ is an external prerequisite. It is not embedded in the application executable. After
installing YAZ, either add its `bin` directory to `PATH` or select `yaz-client.exe` in the
application's Settings dialog.

## Install and run from source

```powershell
git clone https://github.com/jspann21/z3950_search_for_marc.git
cd z3950_search_for_marc
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python main.py
```

The following entry points are equivalent:

```powershell
python main.py
python -m z3950_search_for_marc
z3950-search
```

## Searching

1. Choose **ISBN** or **Title + author** in the left panel.
2. Enter a valid ISBN-10/ISBN-13, or both a title and an author.
3. Select the United States, Worldwide, or both location filters.
4. Select **Search servers**.
5. Choose a successful server in the results table to inspect its first MARC record.
6. Use **Previous** and **Next** to fetch and navigate that server's result set.
7. Select **Export .mrc…** to save the displayed record.

Results appear as servers finish; one unavailable server does not interrupt the rest of the
search. The progress summary distinguishes successful, empty, failed, timed-out, and canceled
queries. The Activity panel contains timestamped diagnostic details.

Live Z39.50 endpoints are maintained by other organizations. A timeout or connection failure
usually indicates that a particular target is unavailable or has changed, not that the desktop
application failed.

## Settings

Settings persist under the existing `z3950_search_for_marc` organization and application keys,
so preferences from version 0.2 are reused automatically.

| Setting | Default | Purpose |
| --- | --- | --- |
| YAZ executable | `yaz-client` | Command name or full path to `yaz-client.exe` |
| Server catalog | Bundled catalog | Optional custom JSON server list |
| Concurrent queries | 12 | Maximum active server processes, bounded from 1 to 32 |
| Server timeout | 5 seconds | Per-server and per-record request timeout |
| Save directory | Downloads | Initial directory for `.mrc` exports |
| Record trimming | Enabled | Removes tags `000–009` and `900+` from displayed/exported records |

Settings validates the YAZ executable, catalog, and export directory before saving. Invalid
changes remain in the dialog for correction and do not replace the current working settings.

## Server catalogs

The packaged application contains a catalog of 372 servers. A custom catalog uses the same JSON
array format as earlier releases:

```json
[
  {
    "name": "Library of Congress",
    "host": "z3950.loc.gov",
    "port": 7090,
    "database": "VOYAGER",
    "location": "USA"
  },
  {
    "name": "Example Library",
    "host": "catalog.example.org",
    "port": "210",
    "database": "books",
    "location": "Worldwide"
  }
]
```

`port` may be a JSON number or numeric string. `location` must be `USA` or `Worldwide`.
Library of Congress entries are queried first.

## Troubleshooting

### YAZ client required

Open Settings and select the complete path to `yaz-client.exe`. The application checks the saved
path, `PATH`, and common Windows YAZ installation locations.

### Most servers time out

Try one location group, reduce concurrent queries on a constrained connection, or increase the
server timeout. Individual public catalogs frequently go offline or change their connection
details.

### International text looks incorrect

The application recognizes UTF-8 and common legacy YAZ console encodings including CP850 and
CP1252. Include the original Activity output and server endpoint when reporting a remaining
encoding problem.

### A custom catalog will not load

Confirm that the file contains a JSON array and every entry has non-empty `name`, `host`,
`database`, `port`, and `location` values. The Settings dialog reports the first invalid entry.

## Development

Install the editable package and quality tools:

```powershell
python -m pip install -e ".[dev]"
python -m ruff format --check .
python -m ruff check .
python -m mypy src tests
python -m pytest
```

The offline test suite uses controlled backends and subprocesses; it does not require YAZ or
internet access. It covers query construction, catalog and settings compatibility, MARC parsing
and decoding, subprocess timeout/cancellation, bounded search orchestration, stale-session
isolation, complete Qt search/navigation/export workflows, and application startup.

The main layers are:

- `models.py`: domain types, settings, sessions, results, and record cache state
- `backend.py`: `SearchBackend`, executable discovery, and cancellable YAZ processes
- `search.py`: bounded Qt task orchestration and stale-session isolation
- `widgets.py` and `dialogs.py`: focused UI components
- `app.py`: application composition and user workflow coordination

## Build the Windows executable

```powershell
python -m pip install -e ".[dev,package]"
python -m PyInstaller --clean --noconfirm main.spec
& .\dist\z3950_search_for_marc-1.0.0.exe --smoke-test
```

The executable includes the application icon and bundled server catalog. GitHub Actions runs the
quality suite across supported Python versions and desktop operating systems, then builds,
smoke-tests, and uploads the versioned Windows artifact.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
