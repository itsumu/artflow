# Security policy

## Report a vulnerability privately

Please use the repository's
[private vulnerability reporting](https://github.com/itsumu/artflow/security/advisories/new).
Do not include exploit details, private asset paths, or secrets in a public issue.

## Supported scope

Security fixes target the current `main` branch until the project publishes its
first stable release and version-support policy.

Artflow is a localhost-only, single-user workbench. Keep these boundaries in
mind:

- Do not expose the HTTP service through a proxy, tunnel, shared host, or public
  network.
- Treat every adapter and configured executable as trusted local code. Artflow
  validates commands and approvals, but it is not an operating-system sandbox.
- Commands, logs, file paths, and hashes are stored in the project's configured
  `.artflow-state` directory. Do not print secrets from production tools.
- Only inherit environment variables a tool actually needs. Never commit secrets
  in `project.json`, `pipelines.json`, or tool arguments.
- `scripts/run_local.sh` is a developer-only restart helper. It intentionally
  stops any process listening on port 4179 and is not part of the public quick
  start.

The service restricts Host headers to localhost, uses a random per-process token
for writes, executes argument arrays without a shell, checks exact command
allowlists, and binds approvals to current configuration and file hashes.
