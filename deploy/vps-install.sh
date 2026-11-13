#!/usr/bin/env bash
# Install the Media Monitor collector on a Debian/Ubuntu VPS and run it every 3 hours.
# It writes new articles into your Google Sheet; there is no web server and no database.
#
# Before running, put your Google service-account key on the VPS at /etc/media-monitor/key.json
# (see README: "Run the collector on a VPS"). Then:
#
#   sudo bash vps-install.sh <SHEET_ID>
#
set -euo pipefail

SHEET_ID="${1:-}"
REPO="https://github.com/pwintsan4238/media-monitor.git"
APP_USER="mediamonitor"
APP_DIR="/opt/media-monitor"
CONF_DIR="/etc/media-monitor"
LOG="/var/log/media-monitor.log"

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo bash $0 <SHEET_ID>"; exit 1; }
[ -n "$SHEET_ID" ] || { echo "Usage: sudo bash $0 <SHEET_ID>   (the long id in the Google Sheet's URL)"; exit 1; }
[ -f "$CONF_DIR/key.json" ] || { echo "Missing $CONF_DIR/key.json. Copy your service-account key there first."; exit 1; }

echo "==> Installing packages"
apt-get update -y >/dev/null
apt-get install -y python3 python3-venv python3-pip git ca-certificates cron util-linux >/dev/null
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10 or newer is required (Ubuntu 22.04+ / Debian 12+)."; exit 1; }

echo "==> Creating service user and fetching the code"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone "$REPO" "$APP_DIR"; fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> Writing configuration (readable only by the service user)"
cat > "$CONF_DIR/env" <<EOF
SHEET_ID=$SHEET_ID
GOOGLE_SERVICE_ACCOUNT_FILE=$CONF_DIR/key.json
CRAWLER_USER_AGENT=MediaMonitorBot/0.1 (+https://github.com/pwintsan4238/media-monitor)
EOF
chown -R "$APP_USER":"$APP_USER" "$CONF_DIR"
chmod 700 "$CONF_DIR"
chmod 600 "$CONF_DIR/env" "$CONF_DIR/key.json"
touch "$LOG" && chown "$APP_USER":"$APP_USER" "$LOG"
chmod +x "$APP_DIR/deploy/run-collector.sh"

echo "==> Scheduling: every 3 hours at minute 47 (GitHub's own run is at minute 17, so they never overlap)"
cat > /etc/cron.d/media-monitor <<EOF
47 */3 * * * $APP_USER $APP_DIR/deploy/run-collector.sh >> $LOG 2>&1
EOF
chmod 644 /etc/cron.d/media-monitor

echo
echo "Done. Test it now (crawls for real, writes nothing):"
echo "  sudo -u $APP_USER $APP_DIR/deploy/run-collector.sh --dry-run --only shwe"
echo "Real run:  sudo -u $APP_USER $APP_DIR/deploy/run-collector.sh"
echo "Logs:      tail -f $LOG"
