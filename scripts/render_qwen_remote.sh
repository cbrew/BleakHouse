#!/bin/bash
# Render a Qwen TTS episode via the qwen-tts-server REST API on pop-os.
#
# This script used to hold an ssh session open for the full ~2h render and
# broke on every wifi flap. It now delegates to the Python HTTP client in
# scripts/render_qwen_via_http.py — discrete polled requests, server owns
# the job state.
#
# Usage:
#   scripts/render_qwen_remote.sh <run_id> [--ref-source <path>]
#
# Env (optional):
#   QWEN_TTS_BASE_URL  default http://pop-os.local:8765
#   QWEN_TTS_TOKEN     direct token (otherwise read from ~/.config/qwen-tts/token)

set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/render_qwen_via_http.py "$@"
