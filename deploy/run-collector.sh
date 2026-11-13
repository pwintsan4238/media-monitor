#!/usr/bin/env bash
# One collector run. Used by cron; extra arguments are passed on (e.g. --dry-run --only shwe).
set -euo pipefail
set -a
. /etc/media-monitor/env
set +a
cd /opt/media-monitor/backend
# flock: if a previous run is still going, skip this one instead of writing duplicate rows.
exec flock -n /tmp/media-monitor.lock /opt/media-monitor/venv/bin/python -m app.sheet_sync "$@"
