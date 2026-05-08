#!/usr/bin/env bash
# Post-clone bootstrap. Idempotent — safe to re-run.
#
# Steps:
#   1. Verify .env exists (point at .env.example otherwise)
#   2. uv sync — root project deps
#   3. uv sync — tools/forced_align (separate uv project)
#   4. uv run playwright install chromium — for audio-route e2e tests
#   5. Probe for ffmpeg system binary (pydub mp3 export); print install
#      hint if missing
#   6. (optional) --pull-cas: prefetch ~7 GB of audio bytes from R2 into
#      the local CAS so the webapp serves shards from disk instead of
#      302-redirecting. Without it, the webapp still works — every audio
#      request just hops through R2 once.
#
# Usage:
#   bash scripts/bootstrap.sh             # standard setup
#   bash scripts/bootstrap.sh --pull-cas  # also prefetch CAS bytes
set -euo pipefail
cd "$(dirname "$0")/.."

PULL_CAS=0
for arg in "$@"; do
    case "$arg" in
        --pull-cas) PULL_CAS=1 ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

step() { printf "\n==> %s\n" "$1"; }

step "[1/6] verify .env"
if [ ! -f .env ]; then
    echo "  .env missing. Copy the template and fill in values:" >&2
    echo "    cp .env.example .env" >&2
    echo "    chmod u+w .env && \$EDITOR .env && chmod u-w .env" >&2
    exit 1
fi
echo "  .env present ($(wc -l < .env) lines)"

step "[2/6] uv sync — root project"
uv sync

step "[3/6] uv sync — tools/forced_align"
if [ -d tools/forced_align ]; then
    (cd tools/forced_align && uv sync)
else
    echo "  tools/forced_align/ missing; skipping"
fi

step "[4/6] playwright install chromium"
uv run playwright install chromium

step "[5/6] bd hooks install + import .beads/issues.jsonl"
# (a) Set git config core.hooksPath = .beads/hooks/ so bd's git
#     integration runs (pre-commit / post-merge / pre-push etc.).
#     Per-clone setting — not committed by git itself; idempotent.
# (b) Import the committed JSONL into the local Dolt database so
#     the issue tree appears in this clone. Auto-import would do
#     this on first read anyway, but doing it explicitly here
#     surfaces any errors loudly.
if command -v bd >/dev/null 2>&1; then
    bd hooks install 2>&1 | head -3 || true
    if [ -f .beads/issues.jsonl ]; then
        bd import 2>&1 | tail -3 || true
    fi
else
    echo "  bd not on PATH; skipping (install via 'go install ...' or your usual route)"
fi

step "[6/6] system deps"
if command -v ffmpeg >/dev/null 2>&1; then
    echo "  ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "  ffmpeg: NOT FOUND on PATH" >&2
    echo "    Linux:  sudo apt install ffmpeg" >&2
    echo "    macOS:  brew install ffmpeg" >&2
    exit 1
fi

if [ "$PULL_CAS" = "1" ]; then
    step "[+] cas_migrate populate --commit (~7 GB from R2)"
    uv run python -m scripts.cas_migrate inventory --out /tmp/cas_inventory.json
    uv run python -m scripts.cas_migrate populate \
        --inventory /tmp/cas_inventory.json --commit
    rm -f /tmp/cas_inventory.json
fi

echo
echo "bootstrap done."
echo "next:"
echo "  uv run uvicorn webapp.app:app --reload --port 8080"
