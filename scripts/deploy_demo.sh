#!/bin/bash
# Build, locally verify, and deploy the Fly demo container.
#
# Existed because the prior workflow (documented in the fly-deployment
# bd memory) only listed stage → build → deploy. A broken deploy on
# 2026-04-23 (ModuleNotFoundError at startup, stale .dockerignore)
# shipped silently because the built container was never run before
# `fly deploy`. This script fills that gap.
#
# Steps:
#   1. stage_demo.sh demo_data
#   2. podman build -t bleakhouse-demo -f Containerfile .
#   3. podman run + curl /tracker + /tracker/data (fail-loud on any error
#      in container logs)
#   4. sync_audio_via_http.py — push DVC audio blobs (Gemini + Qwen)
#      to the fly volume(s) via HTTPS POST. Idempotent.
#   5. fly deploy --local-only
#   6. curl the public URL's /tracker; fail-loud on non-200
#
# Any failure aborts. No step is optional.
#
# Usage:
#   bash scripts/deploy_demo.sh            # full run
#   bash scripts/deploy_demo.sh --dry-run  # stop after local verification

set -euo pipefail

APP="${FLY_APP:-bleakhouse-demo}"
PUBLIC_URL="${PUBLIC_URL:-https://${APP}.fly.dev}"
LOCAL_PORT="${LOCAL_PORT:-18080}"
IMAGE_TAG="${IMAGE_TAG:-bleakhouse-demo}"
CONTAINER_NAME="${CONTAINER_NAME:-bh-deploy-verify}"
DRY_RUN=0
ALLOW_STALE=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --allow-stale) ALLOW_STALE=1 ;;
        -h|--help)
            sed -n '2,28p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

echo "==> [0/7] DVC provenance check"
if uv run --no-sync dvc status 2>/dev/null | grep -q "up to date"; then
    echo "    dvc status clean"
else
    if [ "$ALLOW_STALE" = 1 ]; then
        echo "    WARNING: DVC reports stale runs but --allow-stale was passed; continuing." >&2
    else
        echo "    DVC reports stale runs. Summary:" >&2
        uv run --no-sync python -m scripts.dvc_stale_report >&2 || true
        echo "" >&2
        echo "    Refusing to deploy a stale provenance graph." >&2
        echo "    Options:" >&2
        echo "      - regenerate the affected artefacts, then \`uv run dvc commit\`" >&2
        echo "      - re-run with --allow-stale if you're knowingly shipping a stale state" >&2
        exit 1
    fi
fi

echo "==> [0/7] Refreshing experiments.db (scan-if-stale)"
uv run python -c "from enrichment.expdb.refresh import ensure_db_current; ensure_db_current()"

echo "==> [1/7] Staging demo data"
bash scripts/stage_demo.sh demo_data

echo "==> [2/7] Building container image ($IMAGE_TAG)"
podman build -t "$IMAGE_TAG" -f Containerfile .

echo "==> [3/7] Running container locally on port $LOCAL_PORT and probing"
podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
podman run -d --name "$CONTAINER_NAME" -p "${LOCAL_PORT}:8080" "$IMAGE_TAG" >/dev/null

cleanup() {
    podman stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    podman rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

probe() {  # probe URL -> prints "200" on 200, actual code or "000" on failure
    curl --max-time 5 -s -o /dev/null -w "%{http_code}" "$1" 2>/dev/null || echo "000"
}

# Wait up to ~30s for /tracker to respond 200.
code=""
for _ in $(seq 1 15); do
    code=$(probe "http://127.0.0.1:${LOCAL_PORT}/tracker")
    [ "$code" = "200" ] && break
    sleep 2
done
if [ "$code" != "200" ]; then
    echo "FAIL: /tracker returned $code after 30s" >&2
    echo "--- container logs ---" >&2
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
fi

# Fail on Python tracebacks or ModuleNotFoundError in the startup logs.
if podman logs "$CONTAINER_NAME" 2>&1 | grep -qE "Traceback|ModuleNotFoundError|ImportError"; then
    echo "FAIL: container logs contain a traceback" >&2
    podman logs "$CONTAINER_NAME" >&2
    exit 1
fi

# /tracker/data needs a moment to warm its RunIndex cache. Retry up to ~15s.
json=""
for _ in $(seq 1 8); do
    json=$(curl --max-time 10 -s "http://127.0.0.1:${LOCAL_PORT}/tracker/data" 2>/dev/null || true)
    [ -n "$json" ] && break
    sleep 2
done
if [ -z "$json" ]; then
    echo "FAIL: /tracker/data returned empty body after 16s" >&2
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
fi
if ! echo "$json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
gens = [g['id'] for g in d.get('generators', [])]
assert 'anthropic_sonnet_4_6' in gens, f'missing default generator in {gens}'
totals = d.get('totals_by_generator') or {}
assert totals, 'totals_by_generator missing'
for g, t in totals.items():
    assert t['total'] > 0, f'{g}: total=0'
print(f'OK: {len(gens)} generators, {sum(t[\"done\"] for t in totals.values())} total done cells')
" 2>&1; then
    echo "FAIL: /tracker/data did not validate" >&2
    exit 1
fi

echo "==> Local container healthy."
if [ "$DRY_RUN" = 1 ]; then
    echo "--dry-run set; stopping before fly deploy."
    exit 0
fi

# Explicitly stop the local container now so its port is freed and
# nothing implies the verification is the same thing as production.
cleanup
trap - EXIT

echo "==> [4/7] Sync DVC audio cache to fly volume(s) via HTTPS"
# ADMIN_UPLOAD_TOKEN must match the fly secret. Stored locally at
# ~/.bh-fly-admin-token by the deploy operator.
if [ -z "${ADMIN_UPLOAD_TOKEN:-}" ] && [ -f "$HOME/.bh-fly-admin-token" ]; then
    ADMIN_UPLOAD_TOKEN=$(cat "$HOME/.bh-fly-admin-token")
    export ADMIN_UPLOAD_TOKEN
fi
[ -n "${ADMIN_UPLOAD_TOKEN:-}" ] \
    || { echo "FAIL: ADMIN_UPLOAD_TOKEN not set and ~/.bh-fly-admin-token not found" >&2; exit 1; }
uv run python -m scripts.sync_audio_via_http

echo "==> [5/7] fly deploy --local-only (app: $APP)"
fly deploy --local-only --app "$APP"

echo "==> [6/7] Post-deploy smoke test: $PUBLIC_URL/tracker"
# Machines may take a few seconds to accept traffic.
for i in $(seq 1 15); do
    code=$(curl --max-time 15 -s -o /dev/null -w "%{http_code}" "${PUBLIC_URL}/tracker" || echo 000)
    [ "$code" = "200" ] && break
    sleep 3
done
if [ "$code" != "200" ]; then
    echo "FAIL: live $PUBLIC_URL/tracker returned $code" >&2
    echo "--- fly logs (last 40) ---" >&2
    fly logs --app "$APP" --no-tail 2>&1 | tail -40 >&2 || true
    exit 1
fi

echo "==> [7/7] Audio smoke test"
# Pick the first run with audio from runs.yaml and probe its podcast.mp3.
# Verifies (a) the symlink in the image, (b) the fly volume mount, and
# (c) the cache blob arrived via sync_audio_to_fly. Failure here means
# audio is broken in production even though /tracker looks fine.
SMOKE_RUN=$(uv run --no-sync python -c "
import yaml
d = yaml.safe_load(open('runs.yaml'))
ids = d.get('run_ids_audio') or []
if not ids:
    raise SystemExit('no run_ids_audio in runs.yaml')
print(ids[0])
")
SMOKE_URL="${PUBLIC_URL}/audio/${SMOKE_RUN}/podcast.mp3"
SMOKE_TMP=$(mktemp -t bh-smoke-XXXXXX.mp3)
trap 'rm -f "$SMOKE_TMP"' EXIT

http=$(curl --max-time 60 -s -o "$SMOKE_TMP" -w "%{http_code}" "$SMOKE_URL" || echo 000)
size=$(stat -f "%z" "$SMOKE_TMP" 2>/dev/null || stat -c "%s" "$SMOKE_TMP" 2>/dev/null || echo 0)
if [ "$http" != "200" ]; then
    echo "FAIL: $SMOKE_URL returned $http (downloaded $size bytes)" >&2
    echo "--- fly logs (last 40) ---" >&2
    fly logs --app "$APP" --no-tail 2>&1 | tail -40 >&2 || true
    exit 1
fi
if [ "$size" -lt 1000000 ]; then
    echo "FAIL: $SMOKE_URL returned $http but only $size bytes (expected >1 MB)" >&2
    exit 1
fi
echo "    OK: $SMOKE_RUN ($((size/1024/1024)) MB streamed via fly volume)"

echo ""
echo "SUCCESS. Live: $PUBLIC_URL/tracker  (audio verified for $SMOKE_RUN)"
