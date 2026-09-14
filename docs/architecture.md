# Artflow 0.2 architecture

The package contains no engine, project, asset ID or project CLI knowledge.
A manifest supplies roots, JSON contract mappings, asset templates, executor
definitions and action boundaries. There is no dynamic adapter-code import.

- adapter.py resolves schema 2 into assets, artifacts and executor specifications.
- pipeline.py checks the resolved DAG, allowlists, review boundaries and paths.
- project.py creates the same immutable plan for preview and worker execution.
- executor.py runs argv without a shell and normalizes exit-code/JSON results.
- ledger.py records runs in SQLite and uses OS locks, never stale-file deletion.
- server.py exposes asset/action/run routes; web/ renders returned definitions.

## Execution lifecycle

A plan includes the resolved steps, commands, input/output hashes, adapter/tool
identity and lock set. The client approves that token. A worker acquires locks
and verifies the token again before any command starts. Each step records its
inputs, outputs, logs, duration, result and definition identity. Inputs are
checked again before consumption and after the tool completes.

HTTP submission returns 202 with run_id. The page polls in-progress runs;
completed and interrupted records survive service restarts. Cancelling or
closing the service signals workers and terminates their process groups.
The service lifetime lock is acquired before recovery, so a second instance
cannot invalidate active work. CLI run uses the same lifetime lock.

SQLite imports the old JSON ledger once and retains the JSON source.
Legacy records are shown as history without inventing approvals/fingerprints.

Step freshness compares declared input/output hashes and definition/tool
identity, then propagates upstream failure/staleness. Published-version
freshness compares its explicit published artifacts and definition identity.
Changing any shared manifest/tool definition conservatively invalidates prior
results, even if only one asset was intended to change.

## Local API

GET /api/health — service version and active project identity
GET /api/project — asset discovery and session token
GET /api/check — read-only adapter checks
GET /api/assets/{asset_id} — metadata, artifacts, pipeline, states, history
POST /api/assets/{asset_id}/actions/{action_id}/plan — prepare a plan
POST /api/assets/{asset_id}/actions/{action_id}/run — token and confirmation; 202
GET /api/runs/{run_id} — persisted status, steps and logs
POST /api/runs/{run_id}/cancel — signal worker cancellation
GET /artifact/{asset_id}/{artifact_id} — configured artifact only

POST requests require X-Artflow-Token, obtained from /api/project on the local
origin. Hostnames are restricted to localhost/127.0.0.1; no CORS access.
This is a local single-user service, not a network deployment API.

## Scope

The first executor implementation supports local command-line programs.
The Executor protocol leaves a seam for later remote/Agent executors, but no
Agent integration, automatic approval, remote farm or plugin marketplace is
included. Images/audio/video are previewable; 3D/source formats use download.
Windows needs an alternative lock/process implementation before support can
be claimed. Command pipes are continuously drained into bounded memory; long
stdout/stderr is shown as a 64 KB tail per stream. JSON reports are limited to
8 MiB and retained as structured reports.
