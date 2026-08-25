# Artflow

Artflow is a local, auditable art-production workbench. Its first adapter reads
the UnamedTactics Fire Tower pipeline without duplicating asset contracts or
calling arbitrary shell commands.

## artctl machine interface

The workbench invokes only the project adapter's allow-listed `artctl` commands,
with a configured Godot project root and a structured response:

```sh
cd /Users/andrew/GodotProjects/UnamedTactics/art_source
tools/artctl --project-root ../UnamedTactics --json capabilities
tools/artctl --project-root ../UnamedTactics --json diagnose
tools/artctl --project-root ../UnamedTactics --json verify buildings
tools/artctl --project-root ../UnamedTactics --json verify building-export fire_tower
```

`artctl-json-v1` reports the command, exit status, timestamps, checks and
contract-derived asset facts (including actual source/runtime file hashes). It
does not duplicate contracts. Existing `tools/artctl ...` terminal commands
remain supported.

## Run the Fire Tower workbench

```sh
scripts/run_local.sh
```

Open the printed local address. The first release is deliberately safe:

- shows live contract, source, preview and runtime artifacts;
- exposes approved raw -> hard Alpha -> Aseprite candidate -> formal source as three separately confirmed actions, each locked to the reviewed input SHA;
- runs full `artctl --json verify buildings` on demand; confirmed export uses the runtime-optional `verify building-export fire_tower` preflight before `artctl --json export building fire_tower`;
- offers dry-run planning without writes; candidate actions cannot overwrite the runtime PNG, and runtime export remains its own confirmation gate;
- provides a non-mutating environment diagnostic for `artctl`, Python, optional PyYAML, Aseprite, Godot, contract readability, repository locations and contract-derived runtime output directories; it checks permissions without writing a probe file and does not launch Aseprite or Godot;
- validates the version-controlled pipeline DAG before dry-run or export: input sources, dependency cycles, command allow-lists, `artctl` capabilities, write-path conflicts, approval gates and resource locks;
- runs `artctl --json verify visuals` on demand; a confirmed export always follows with strict Godot visual verification;
- acquires the version-controlled `asset:{asset_id}`, `aseprite_batch`, and `godot_import` resource locks as real cross-process locks before an export; interrupted/failed/stale runs offer a read-only retry preflight, then require the same typed confirmation before any write;
- keeps a local run ledger with step logs, duration, exit codes, and input/output hashes, and marks a previously verified run stale if those files change.

Project-specific commands and paths live in `art_source/.artflow/`; Artflow
core remains reusable for another project's adapter. Local run records are
stored once at the workspace-level `.artflow-runs/<project_id>/` directory,
never in a source contract, the Artflow repository, or a runtime asset
directory.
