# Distribution checklist

Artflow has no third-party runtime dependencies and currently targets
macOS/Linux. Never publish a wheel from a reused `build/` or `dist/` directory:
deleted starter files can survive there and be copied into a later package.

Before publishing a distribution:

1. Require a green [CI workflow](../.github/workflows/ci.yml) on macOS and Linux.
2. Build from a clean clone or clean source archive, not the development tree.
3. Select and add the distribution license and confirm release ownership.
   This refactor does not grant a new public license for existing project code.
4. Run `scripts/verify_wheel.py` and the installed-wheel smoke test below.
5. Record the artifact's SHA-256, then publish that exact tested file.
6. Inspect the complete reachable Git history—not only the current tree—for
   private paths, project assets, secrets, and unrelated product history.
   Prefer starting the public repository from a reviewed clean snapshot when
   the existing history was created inside another project.

> **PyPI name decision required:** the `artflow` distribution name is currently
> owned by another project. Before a PyPI release, either choose a unique
> `[project].name` (the `artflow` command and Python package may keep their
> names) or confirm access with the existing owner. GitHub source releases and
> attached wheels are unaffected. Never upload this repository under the
> current distribution name without resolving that ownership first.

Example clean build:

```sh
RELEASE_ROOT="$(mktemp -d)"
git clone --local . "$RELEASE_ROOT/artflow"
cd "$RELEASE_ROOT/artflow"
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 scripts/verify_wheel.py dist/artflow-*.whl
```

Archive or delete any pre-existing local `dist/artflow-*.whl` before starting.
Only upload the wheel created and verified in the clean clone. No
package-registry publication is performed automatically.

The wheel must contain web assets and the starter project. After installing
the wheel in a fresh environment, change to another directory and run:
```sh
artflow init ./studio
artflow doctor --project ./studio/project.json
artflow check --project ./studio/project.json
artflow run --project ./studio/project.json --asset campfire --action build --confirm campfire
artflow serve --project ./studio/project.json
```

Adapters and the projects' assets remain outside the distribution.
Adapter schema_version and package version evolve separately. Unsupported
schema versions fail clearly; migrations must be explicit and reviewed.
