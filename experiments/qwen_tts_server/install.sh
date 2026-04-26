#!/bin/bash
# Install the Qwen TTS service on pop-os. Run with sudo on pop-os; assumes the
# repo has already been rsynced to /home/cbrew/bleakhouse-qwen-tts/ and a venv
# is set up with `uv sync`. Idempotent: safe to re-run after each code push.
#
# Usage:
#   sudo bash install.sh
#
# Optional env:
#   QWEN_TTS_TOKEN  - use this exact token (otherwise generated randomly)
#   REPO_DIR        - default /home/cbrew/bleakhouse-qwen-tts
#   STATE_DIR       - default /var/lib/qwen-tts-server
#   ETC_DIR         - default /etc/qwen-tts-server
#   USER_NAME       - default cbrew
#   SERVICE         - default qwen-tts-server

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/cbrew/bleakhouse-qwen-tts}"
STATE_DIR="${STATE_DIR:-/var/lib/qwen-tts-server}"
ETC_DIR="${ETC_DIR:-/etc/qwen-tts-server}"
USER_NAME="${USER_NAME:-cbrew}"
SERVICE="${SERVICE:-qwen-tts-server}"

[ -d "$REPO_DIR" ] || { echo "FAIL: $REPO_DIR not found" >&2; exit 1; }

install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR"
install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR/jobs"
install -d -m 0750 -o root         -g "$USER_NAME" "$ETC_DIR"

# Token: keep an existing one if present; else use $QWEN_TTS_TOKEN; else random.
if [ ! -s "$ETC_DIR/token" ]; then
    if [ -n "${QWEN_TTS_TOKEN:-}" ]; then
        printf '%s' "$QWEN_TTS_TOKEN" > "$ETC_DIR/token"
    else
        head -c 48 /dev/urandom | base64 | tr -d '\n=+/' > "$ETC_DIR/token"
    fi
    chmod 0640 "$ETC_DIR/token"
    chown root:"$USER_NAME" "$ETC_DIR/token"
    echo "Generated new token at $ETC_DIR/token"
fi

# Pin the renderer code rev so cached jobs invalidate when the code changes.
sudo -u "$USER_NAME" bash -c "cd '$REPO_DIR' && git rev-parse HEAD" > "$STATE_DIR/code_rev"
chown "$USER_NAME":"$USER_NAME" "$STATE_DIR/code_rev"

install -m 0644 "$REPO_DIR/experiments/qwen_tts_server/qwen-tts-server.service" \
        "/etc/systemd/system/${SERVICE}.service"

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# Wait for the service to either come up or fail loudly.
for _ in $(seq 1 20); do
    if systemctl is-active --quiet "$SERVICE"; then
        echo "OK: $SERVICE is active. Token at $ETC_DIR/token"
        exit 0
    fi
    if systemctl is-failed --quiet "$SERVICE"; then
        systemctl status "$SERVICE" --no-pager
        exit 1
    fi
    sleep 1
done
systemctl status "$SERVICE" --no-pager
exit 1
