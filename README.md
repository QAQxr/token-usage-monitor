# Token Usage Monitor

A small, read-only Codex usage monitor with a TokenWatch-style dashboard.

The MVP reads Codex rollout JSONL records from the local Codex data directory. It keeps raw event parsing separate from metric aggregation and exposes both a CLI snapshot and a local HTTP dashboard. It does not modify Codex, write to session logs, or require third-party packages.

## Quick start

Show one snapshot from the newest Codex session:

```bash
python3 -m tokenwatch --once
```

Run the compact terminal monitor:

```bash
python3 -m tokenwatch
```

Run the local dashboard on loopback only:

```bash
python3 -m tokenwatch --serve --port 8765
```

Then open `http://127.0.0.1:8765/` in a browser. The server is opt-in and is not started automatically.

Run the optional PySide6 desktop window:

```bash
python3 -m pip install -e '.[gui]'
python3 -m tokenwatch --gui
```

The desktop window is read-only, always on top, draggable from its header, independently closable, and refreshes the newest rollout file on a timer. PySide6 is intentionally optional, so the existing CLI and HTTP dashboard remain standard-library-only.

## Development

The project uses only the Python standard library in the MVP:

```bash
python3 -m unittest discover -s tests -v
```

The GUI refresh/state layer is tested without requiring a Qt installation. A real desktop launch requires the optional `gui` extra above.

## Data and limitations

See [docs/data-sources.md](docs/data-sources.md), [docs/design.md](docs/design.md), and [docs/limitations.md](docs/limitations.md).
