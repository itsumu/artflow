# Artflow

A local workbench for repeatable art production. Projects supply assets, tools,
pipelines and review boundaries through JSON adapters. The core runs commands,
records versions and logs, and displays artifacts without knowing an engine or
an asset type.

Requires Python 3.11+ on macOS or Linux. No runtime Python packages are required.
Windows support is not implemented yet (process groups and file locks are POSIX).

## Try an independent project

Install from this checkout into an environment of your choice:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/artflow init /tmp/my-art-studio
.venv/bin/artflow check --project /tmp/my-art-studio/project.json
.venv/bin/artflow serve --project /tmp/my-art-studio/project.json
```

Open <http://127.0.0.1:4179>. The starter includes two SVG assets and a small
standard-library production tool, so no game project or creative software is
needed. Select an asset, open **制作并验证**, review the plan, and enter its asset
ID to execute. Edit an input to see the old step results become stale.

For an already installed distribution, use `artflow` directly. For development,
`PYTHONPATH=src python3 -m artflow ...` works without installation.
`scripts/run_local.sh /absolute/path/project.json` is a macOS developer convenience:
it restarts the process listening on port 4179. Normal `artflow serve` never
terminates another process.

## Connect a project

Start from the example and replace its command/tool and artifact paths.
Most tools need configuration only; they do not need to import Artflow.

- [Adapter guide](docs/adapter.md): roots, templates, existing JSON contracts,
  executors, outputs and review gates.
- [Architecture](docs/architecture.md): execution model, state, locks and API.
- [Release notes](docs/releasing.md): installation checks, support boundaries and
  distribution steps.

`artflow check --project ...` checks all assets, the DAG, resolved paths,
executor availability, preview references, command allowlists and review
boundaries without running production tools. Missing *future outputs* do not
block onboarding. A selected action's plan checks its actual required inputs.

```sh
artflow plan --project project.json --asset sun --action build
artflow run --project project.json --asset sun --action build --confirm sun
```

CLI writes require an exact asset confirmation; the web additionally binds
confirmation to a plan token. CLI `run` owns the project's service lock; while
the web server owns it, use the web API instead.

## Included capabilities

- Configuration-driven multi-asset navigation, actions and previews.
- One resolved execution plan shared by preview and execution.
- Explicit review boundaries between newly generated intermediate artifacts.
- Background jobs, polling logs, cancellation and nonzero-exit handling.
- SQLite step/run history, input/output hashes and approval records.
- Input, adapter and declared tool changes invalidate dependent step results.
- OS-owned resource locks shared by local projects; one service per project.
- Pictures, audio and video previews; other files remain downloadable.
- Localhost-only HTTP with per-session write tokens.

Adapters are **trusted local code configuration**. Commands run with the user's
permissions. Output declarations validate expected files and coordinate locks;
they are not an OS filesystem sandbox. Only install adapters/tools you trust.

## Development checks

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/artflow/web/app.js
python3 -m pip wheel --no-deps . --wheel-dir dist
```

Tests use temporary independent projects. Project-specific regression checks
belong to their adapters, not this repository.

Version 0.2 uses adapter schema 2. Schema 1 adapters need explicit migration;
there is no silent interpretation of the old project-specific format. Existing
`runs.json` records are imported once into `runs.sqlite3`, retained as historical
records and never relabeled as newly verified runs.
