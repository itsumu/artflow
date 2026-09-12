# Independent starter
Run `artflow init my-studio`, then `artflow check --project my-studio/project.json`
and `artflow serve --project my-studio/project.json`.

Two assets share one template. Edit inputs/sun.json or inputs/moon.json, review
the plan, and run the build action. Changing an input invalidates the corresponding
step; changing make_asset.py invalidates executions made with the earlier tool.
Output and local history are ignored by Git.
