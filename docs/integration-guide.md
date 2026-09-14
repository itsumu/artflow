# Connect Artflow to a game project

Artflow wraps commands you already have. It does not replace your exporter,
image editor, engine importer, or validation scripts.

```text
source files ──▶ your CLI tool ──▶ runtime artifacts
      │                │                   │
      └──── project.json + pipelines.json ─┘
                         │
                         ▼
              Artflow plan, preview, history
```

The smallest useful integration has two JSON files and one existing command-line
tool.

## 1. Create an adapter folder

Keep project-specific Artflow files inside the game repository:

```text
my-game/
├── .artflow/
│   ├── project.json
│   └── pipelines.json
├── art/source/hero.json
├── game/assets/hero.png
└── tools/export_sprite.py
```

You can copy the starter or generate it after installing Artflow:

```sh
artflow init ./my-game/.artflow
```

When working directly from an Artflow checkout, use:

```sh
PYTHONPATH=/path/to/artflow/src python3 -S -m artflow init ./my-game/.artflow
```

Use the same `PYTHONPATH=/path/to/artflow/src python3 -S -m artflow` prefix for
the later commands until Artflow is installed.

## 2. Declare paths, artifacts, and your tool

Start with a minimal `.artflow/project.json`:

```json
{
  "schema_version": 2,
  "project_id": "my_game",
  "label": "My Game",
  "roots": {"game": ".."},
  "storage": "../.artflow-state",
  "pipelines": "pipelines.json",
  "executors": {
    "sprite_exporter": {
      "argv": ["{python}", "{root.game}/tools/export_sprite.py"],
      "cwd": "{root.game}",
      "allowed_commands": [
        ["build", "{artifact.source}", "{artifact.runtime}"]
      ],
      "version_files": ["{root.game}/tools/export_sprite.py"],
      "response": {"format": "exit_code"}
    }
  },
  "templates": {
    "sprite": {
      "kind": "Sprite",
      "pipeline": "sprite",
      "artifacts": {
        "source": {"label": "Source", "kind": "json", "root": "game", "path": "art/source/{asset_id}.json"},
        "runtime": {"label": "Runtime PNG", "kind": "image", "root": "game", "path": "game/assets/{asset_id}.png"}
      },
      "preview": ["runtime"]
    }
  },
  "assets": {
    "hero": {"template": "sprite", "label": "Hero"}
  }
}
```

Important details:

- `argv` launches your tool without a shell.
- `allowed_commands` is an exact allowlist; the browser cannot invent commands.
- `{artifact.source}` and `{artifact.runtime}` resolve to absolute paths.
- `version_files` makes earlier results stale when the tool changes.
- A missing future output is allowed. A missing required input blocks the plan.

Your tool remains independent:

```sh
python3 tools/export_sprite.py build art/source/hero.json game/assets/hero.png
```

It only needs to return exit code `0` on success and create the declared output.
It never imports Artflow.

## 3. Define one production action

Use this minimal `.artflow/pipelines.json`:

```json
{
  "schema_version": 2,
  "pipelines": {
    "sprite": {
      "label": "Sprite Production",
      "steps": [
        {
          "id": "build",
          "label": "Build runtime PNG",
          "kind": "command",
          "executor": "sprite_exporter",
          "command": ["build", "{artifact.source}", "{artifact.runtime}"],
          "inputs": ["source"],
          "outputs": ["runtime"],
          "writes": true,
          "requires_approval": true,
          "approval_artifacts": ["source"],
          "timeout_seconds": 120,
          "retry_policy": "manual",
          "locks": ["asset:{project_id}:{asset_id}"]
        }
      ],
      "actions": {
        "build": {
          "label": "Build runtime PNG",
          "steps": ["build"],
          "publish_artifacts": ["source", "runtime"]
        }
      }
    }
  }
}
```

Every write step declares what it reads, what it writes, which reviewed input
authorizes it, and which resources it locks.

## 4. Check before running

```sh
artflow doctor --project ./my-game/.artflow/project.json
artflow check --project ./my-game/.artflow/project.json
artflow plan --project ./my-game/.artflow/project.json --asset hero --action build
```

`doctor` explains common setup failures in a few lines. Continue only when
`check` reports `"ok": true` and the plan lists the expected command and paths.

## 5. Open the workbench

```sh
artflow serve --project ./my-game/.artflow/project.json
```

Open <http://127.0.0.1:4179>, select the asset, review its plan, and enter the
asset ID to approve the write.

## Add complexity only when needed

- Add another asset by adding one `assets` entry and its source file.
- Add a validation step when your project has a real validation command.
- Split actions when a newly generated image needs human review before the next
  write.
- Use JSON results only when your tool already has a machine-readable report.
- Add shared locks for exclusive applications, engine imports, or shared output
  directories.

See the [adapter reference](adapter.md) for templates, JSON Pointer, JSON
responses, dependency graphs, locks, retries, and publication semantics.
