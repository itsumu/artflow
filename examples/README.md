# Zero-install pixel sprite demo

From the repository root, run:

```sh
python3 -S examples/run_demo.py
```

If port 4179 is already in use, run
`python3 -S examples/run_demo.py --port 4180` instead.

Open the address printed in the terminal, select **Campfire**, and run
**Build and verify**.
Enter `campfire` when the plan asks for confirmation. The demo turns a small JSON
pixel recipe into a transparent 64×64 RGBA PNG and verifies it.

Only Python 3.11+ and a browser are required. The launcher copies the packaged
starter to the ignored `.artflow-demo/` directory, so running it never modifies
the canonical example under `src/`.

See the [quick start](../docs/getting-started.md) and
[integration guide](../docs/integration-guide.md).
