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

POP_HOST="${POP_HOST:-cbrew@pop-os.local}"
POP_DIR="${POP_DIR:-/home/cbrew/bleakhouse-qwen-tts}"

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
ssh "$POP_HOST" "cd $POP_DIR && uv sync"

echo "==> install (sudo)"
ssh -t "$POP_HOST" "sudo CODE_REV='$REV' bash $POP_DIR/experiments/qwen_tts_server/install.sh"

# Token is owned by root:cbrew, mode 0640 — readable by user cbrew, no sudo needed.
echo "==> pull token to ~/.config/qwen-tts/token"
mkdir -p "$HOME/.config/qwen-tts"
ssh "$POP_HOST" "cat /etc/qwen-tts-server/token" > "$HOME/.config/qwen-tts/token"
chmod 600 "$HOME/.config/qwen-tts/token"

echo "==> smoke check /jobs"
TOKEN=$(cat "$HOME/.config/qwen-tts/token")
curl -fsS -H "Authorization: Bearer $TOKEN" "http://pop-os.local:8765/jobs" | head -c 200
echo

rm -f CODE_REV
echo "DEPLOY OK"
