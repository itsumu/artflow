# Contributing to Artflow

Thank you for helping make art production easier to inspect and automate.

## Development setup

Artflow has no third-party runtime dependency. Use Python 3.11+ on macOS or
Linux:

```sh
python3 -S examples/run_demo.py
```

For source commands, prefix them with `PYTHONPATH=src python3 -m artflow`.

## Before opening a pull request

Run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/artflow/web/app.js
git diff --check
```

Changes to the packaged starter must keep `artflow init`, the zero-install demo,
tests, screenshots, and documentation consistent. New production steps must
declare their inputs, outputs, write behavior, approval boundary, and locks.

Keep project-specific paths, asset names, tools, and contracts outside Artflow's
core. Put them in a project's adapter instead.

## Security reports

Please follow [SECURITY.md](SECURITY.md) instead of opening a public issue for a
possible vulnerability.
