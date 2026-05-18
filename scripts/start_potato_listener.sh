#!/usr/bin/env bash
# Launch Potato against the BleakHouse Tier L pairwise config.
#
# Potato enforces a "config file must live inside CWD" security check
# (config_module.py:validate_path_security), so this script cd's into
# the config dir before launching. Browser endpoint: http://localhost:9001
# Stop with Ctrl-C.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="$REPO_ROOT/data/eval/stage2_tier_l_prose/potato"
POTATO_BIN="$REPO_ROOT/tools/potato_listener/.venv/bin/potato"
PORT="${POTATO_PORT:-9001}"

if [[ ! -x "$POTATO_BIN" ]]; then
  echo "Potato not installed. Run: cd $REPO_ROOT/tools/potato_listener && uv sync" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_DIR/pairs.jsonl" ]]; then
  echo "Missing pairs.jsonl. Run: uv run python scripts/render_eval_pairings_potato.py" >&2
  exit 1
fi
cd "$CONFIG_DIR"
exec "$POTATO_BIN" start config.yaml -p "$PORT"
