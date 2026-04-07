# Z39.50 Search For MARC

Desktop application for querying Z39.50 servers, viewing MARC records, and exporting `.mrc` files.

## What Changed

- Migrated the GUI stack from `PyQt5` to `PyQt6`
- Converted the project to a modern `src/` package with `pyproject.toml`
- Added persistent settings for YAZ path, server catalog path, concurrency, timeout, save directory, and record trimming
- Hardened `yaz-client` execution and query sanitization
- Added automated tests, linting, typing, and CI
- Bundled the server catalog and app icon inside the package

## Requirements

- Python `3.11+`
- `yaz-client` installed and available on `PATH`, or configured through the in-app Settings dialog

YAZ is available from Index Data:

- https://www.indexdata.com/resources/software/yaz/

## Install And Run

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
python main.py
```

You can also run the package directly:

```bash
python -m z3950_search_for_marc
```

## Settings

The Settings dialog persists:

- YAZ executable path
- Server catalog path
- Max concurrent queries
- Server timeout in seconds
- Default save directory
- Whether tags `000-009` and `900+` are trimmed from parsed records

If no server catalog path is set, the app uses the bundled `servers.json`.

## Development

Run the local quality checks:

```bash
python -m ruff check .
python -m mypy src tests
python -m pytest
```

## Packaging

Build a Windows desktop executable with PyInstaller:

```bash
python -m PyInstaller main.spec
```

## Test Strategy

- Unit tests cover config validation, MARC parsing, YAZ command safety, and output decoding
- `pytest-qt` covers settings persistence and basic window initialization
- Live Z39.50 verification remains a manual smoke test because it depends on external servers and a local YAZ install
