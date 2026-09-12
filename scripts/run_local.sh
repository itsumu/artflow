#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
if (( $# < 1 )); then
  print -u2 'Usage: scripts/run_local.sh /path/to/project.json'
  exit 2
fi
PROJECT_CONFIG="$1"
HOST="127.0.0.1"
PORT="4179"

listener_pids() {
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

if ! command -v lsof >/dev/null 2>&1; then
  print -u2 "Cannot check port $PORT because lsof is unavailable."
  exit 1
fi

PIDS=(${(f)"$(listener_pids)"})
if (( ${#PIDS} > 0 )); then
  print "Port $PORT is occupied by listener PID(s): ${PIDS[*]}. Stopping them..."
  kill -- "${PIDS[@]}" 2>/dev/null || true

  for _ in {1..20}; do
    [[ -z "$(listener_pids)" ]] && break
    sleep 0.1
  done

  PIDS=(${(f)"$(listener_pids)"})
  if (( ${#PIDS} > 0 )); then
    print "Listener PID(s) ${PIDS[*]} did not stop after SIGTERM; sending SIGKILL..."
    kill -KILL -- "${PIDS[@]}" 2>/dev/null || true

    for _ in {1..10}; do
      [[ -z "$(listener_pids)" ]] && break
      sleep 0.1
    done
  fi

  if [[ -n "$(listener_pids)" ]]; then
    print -u2 "Port $PORT is still occupied; Artflow was not started."
    exit 1
  fi
fi

PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m artflow --project "$PROJECT_CONFIG" --host "$HOST" --port "$PORT"
