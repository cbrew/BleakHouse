#!/bin/bash
# Push the qwen-tts-server to pop-os and (re)start it.
#
# Usage:
#   scripts/deploy_qwen_tts_server.sh
#
# Steps:
#   1. Capture the local git HEAD into CODE_REV (so jobs hash against it).
#   2. rsync repo to pop-os (no .git, no .venv, no data).
#   3. uv sync on pop-os.
#   4. sudo install.sh on pop-os (idempotent).
#   5. curl /jobs to confirm.

set -euo pipefail
cd "$(dirname "$0")/.."

# Default to LAN IP — `pop-os.local` mDNS resolution fails from sandboxed
# subprocesses (Claude Code, etc). Override with POP_HOST if your DHCP gave
# the box a different IP.
POP_HOST="${POP_HOST:-cbrew@192.168.4.34}"
POP_DIR="${POP_DIR:-/home/cbrew/bleakhouse-qwen-tts}"

# Sanity: fail fast if the host isn't reachable.
HOST_ONLY="${POP_HOST#*@}"
if ! nc -z -G 5 "$HOST_ONLY" 22 2>/dev/null; then
    echo "FAIL: cannot reach $HOST_ONLY:22 — check that pop-os is awake on the LAN" >&2
    exit 1
fi

REV=$(git rev-parse HEAD)
echo "==> capturing local rev: $REV"
echo -n "$REV" > CODE_REV

echo "==> rsync to $POP_HOST:$POP_DIR"
rsync -a --delete \
      --exclude=.venv --exclude=.git --exclude='data/runs' \
      --exclude='data/tts_cache' --exclude='reports' --exclude='.dvc' \
      --exclude='.pytest_cache' --exclude='__pycache__' \
      --exclude='node_modules' --exclude='paper' --exclude='poster' \
      --exclude='slides' \
      ./ "$POP_HOST:$POP_DIR/"

echo "==> uv sync on pop-os"
# Non-interactive ssh skips ~/.bashrc, so ~/.local/bin (uv) isn't on PATH.
ssh "$POP_HOST" "cd $POP_DIR && PATH=\$HOME/.local/bin:\$PATH uv sync"

echo "==> install (sudo)"
# Prefer interactive TTY; fall back to SUDO_PASSWORD via stdin for non-TTY runs.
if [ -t 0 ] && [ -t 1 ]; then
    ssh -t "$POP_HOST" "sudo CODE_REV='$REV' bash $POP_DIR/experiments/qwen_tts_server/install.sh"
elif [ -n "${SUDO_PASSWORD:-}" ]; then
    printf '%s\n' "$SUDO_PASSWORD" | \
        ssh "$POP_HOST" "sudo -S -p '' env CODE_REV='$REV' bash $POP_DIR/experiments/qwen_tts_server/install.sh"
else
    echo "FAIL: no TTY and no SUDO_PASSWORD env var" >&2
    exit 1
fi

# Token is owned by root:cbrew, mode 0640 — readable by user cbrew, no sudo needed.
echo "==> pull token to ~/.config/qwen-tts/token"
mkdir -p "$HOME/.config/qwen-tts"
ssh "$POP_HOST" "cat /etc/qwen-tts-server/token" > "$HOME/.config/qwen-tts/token"
chmod 600 "$HOME/.config/qwen-tts/token"

echo "==> smoke check /jobs"
TOKEN=$(cat "$HOME/.config/qwen-tts/token")
curl -fsS -m 10 -H "Authorization: Bearer $TOKEN" "http://$HOST_ONLY:8765/jobs" | head -c 200
echo

rm -f CODE_REV
echo "DEPLOY OK"
