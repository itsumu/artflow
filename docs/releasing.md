# Distribution checklist

Version 0.2 is prepared for local wheel installation on macOS/Linux.
The repository has no third-party runtime dependencies.

Build:
```sh
python3 -m pip wheel --no-deps . --wheel-dir dist
```

Before publishing a distribution:
1. Run the independent tests and installed-wheel smoke test.
2. Check both macOS and Linux process/lock behavior in the release environment.
3. Select and add the distribution license and confirm release ownership.
   This refactor does not grant a new public license for existing project code.
4. Configure the chosen remote repository/package registry, then publish the
   exact tested artifact.

No package-registry or repository publication is performed by this change.

The wheel must contain web assets and the starter project. After installing
the wheel in a fresh environment, change to another directory and run:
```sh
artflow init ./studio
artflow check --project ./studio/project.json
artflow run --project ./studio/project.json --asset sun --action build --confirm sun
artflow serve --project ./studio/project.json
```

Adapters and the projects' assets remain outside the distribution.
Adapter schema_version and package version evolve separately. Unsupported
schema versions fail clearly; migrations must be explicit and reviewed.
