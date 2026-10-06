#!/bin/bash
# Weekly entry point for launchd. Loads secrets from the Keychain and runs the tracker.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
# shellcheck disable=SC1091
source env.sh
exec /usr/bin/python3 -u -m rank_tracker run "$@" >> "logs/$(date +%Y-%m-%d).log" 2>&1
