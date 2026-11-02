#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$APP_DIR/.venv/bin/agentcontract" ]; then
  printf '%s\n' 'Install first from the AgentContract directory:' 'python3 -m venv .venv' '.venv/bin/python -m pip install .'
  exit 2
fi
if [ "$#" -eq 0 ]; then
  exec "$APP_DIR/.venv/bin/agentcontract" serve "$APP_DIR/examples/spring-demo"
fi
exec "$APP_DIR/.venv/bin/agentcontract" serve "$@"
