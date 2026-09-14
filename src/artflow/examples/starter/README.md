# Pixel sprite starter

This project demonstrates a complete Artflow loop with no third-party runtime
packages:

```text
inputs/*.json → make_asset.py → output/*.png → verification → Artflow history
```

The JSON files describe a 16×16 sprite and palette. `make_asset.py` uses only
Python's standard library to create a transparent 64×64 PNG and then validates
its PNG structure, RGBA format, checksums, and alpha channel.

After `artflow init my-studio`:

```sh
artflow doctor --project my-studio/project.json
artflow check --project my-studio/project.json
artflow serve --project my-studio/project.json
```

Open <http://127.0.0.1:4179>, choose **Campfire**, select **Build PNG**, open the
plan, and enter `campfire` to confirm. Edit `inputs/campfire.json` afterward and
refresh the page to see the previous result become stale.

Files:

- `project.json`: assets, paths, tool entry point, and allowed commands.
- `pipelines.json`: production steps and user-facing actions.
- `make_asset.py`: independent project tool; it does not import Artflow.
- `inputs/`: editable sprite recipes.
- `output/`: generated PNGs; ignored by Git.
- `.artflow-state/`: local run history; ignored by Git.
