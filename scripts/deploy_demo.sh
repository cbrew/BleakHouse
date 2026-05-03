#!/bin/bash
# Build, locally verify, and deploy the Fly demo container.
#
# Architecture (deploy-via-dvc-pull, 2026-05-03):
#   - Container holds code + dvc.lock + git-tracked config files. No data.
#   - Entrypoint generates .dvc/config.local from R2 credentials (Fly
#     secrets in production; passed as env vars locally for the smoke
#     test) and runs `dvc pull <non-audio stages>` into /cache (a Fly
#     volume in production; a bind-mounted tmp dir locally).
#   - Audio mp3s stay in R2; webapp 302-redirects to public r2.dev URLs.
#
# Steps:
#   1. dvc push -r r2 (idempotent; sync any pending blobs)
#   2. podman build
#   3. podman run with R2 secrets + tmp cache mount; probe /tracker
#      and /tracker/data; fail-loud on logs containing tracebacks
#   4. fly deploy --local-only
#   5. Post-deploy curl /tracker
#   6. Post-deploy audio smoke test (302 → R2 public URL)
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
LOCAL_CACHE_DIR="${LOCAL_CACHE_DIR:-/tmp/bh-deploy-cache}"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,28p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

# Read R2 credentials from .dvc/config.local for the local podman run.
# In production these come from Fly secrets (set separately).
R2_ACCESS=$(grep access_key_id .dvc/config.local | awk '{print $3}')
R2_SECRET=$(grep secret_access_key .dvc/config.local | awk '{print $3}')
if [ -z "$R2_ACCESS" ] || [ -z "$R2_SECRET" ]; then
    echo "FAIL: couldn't read R2 credentials from .dvc/config.local" >&2
    exit 1
fi

echo "==> [1/6] dvc push -r r2 (idempotent)"
uv run --no-sync dvc push -r r2

echo "==> [2/6] podman build"
podman build -t "$IMAGE_TAG" -f Containerfile .

echo "==> [3/6] podman run + probe"
podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
mkdir -p "$LOCAL_CACHE_DIR"
podman run -d --name "$CONTAINER_NAME" \
    -e DVC_REMOTE_R2_ACCESS_KEY="$R2_ACCESS" \
    -e DVC_REMOTE_R2_SECRET_ACCESS_KEY="$R2_SECRET" \
    -v "$LOCAL_CACHE_DIR:/cache" \
    -p "${LOCAL_PORT}:8080" \
    "$IMAGE_TAG" >/dev/null

cleanup() {
    podman stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    podman rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

probe() {
    curl --max-time 5 -s -o /dev/null -w "%{http_code}" "$1" 2>/dev/null || echo "000"
}

# Wait up to ~60s for /tracker to respond 200 (first boot includes
# the dvc pull, which takes ~3s on a warm cache; longer on first pull).
code=""
for _ in $(seq 1 30); do
    code=$(probe "http://127.0.0.1:${LOCAL_PORT}/tracker")
    [ "$code" = "200" ] && break
    sleep 2
done
if [ "$code" != "200" ]; then
    echo "FAIL: /tracker returned $code after 60s" >&2
    echo "--- container logs ---" >&2
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
fi

if podman logs "$CONTAINER_NAME" 2>&1 | grep -qE "Traceback|ModuleNotFoundError|ImportError"; then
    echo "FAIL: container logs contain a traceback" >&2
    podman logs "$CONTAINER_NAME" >&2
    exit 1
fi

# /tracker/data validates the matrix payload.
json=""
for _ in $(seq 1 8); do
    json=$(curl --max-time 10 -s "http://127.0.0.1:${LOCAL_PORT}/tracker/data" 2>/dev/null || true)
    [ -n "$json" ] && break
    sleep 2
done
if [ -z "$json" ] || ! echo "$json" | python3 -c "
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
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
fi

echo "==> Local container healthy."
if [ "$DRY_RUN" = 1 ]; then
    echo "--dry-run set; stopping before fly deploy."
    exit 0
fi

cleanup
trap - EXIT

echo "==> [4/6] fly deploy --local-only (app: $APP)"
fly deploy --local-only --yes --app "$APP"

echo "==> [5/6] Post-deploy: $PUBLIC_URL/tracker"
for i in $(seq 1 30); do
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

echo "==> [6/6] Audio smoke test (302 → R2)"
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

# Real-browser UA — Cloudflare R2's public r2.dev URL blocks bare
# 'curl/x.y' as a bot via Browser Integrity Check.
http=$(curl --max-time 60 -sL -A "Mozilla/5.0" -o "$SMOKE_TMP" -w "%{http_code}" -r 0-1048576 "$SMOKE_URL" || echo 000)
size=$(stat -f "%z" "$SMOKE_TMP" 2>/dev/null || stat -c "%s" "$SMOKE_TMP" 2>/dev/null || echo 0)
if [ "$http" != "206" ] && [ "$http" != "200" ]; then
    echo "FAIL: $SMOKE_URL returned $http (downloaded $size bytes)" >&2
    echo "--- fly logs (last 40) ---" >&2
    fly logs --app "$APP" --no-tail 2>&1 | tail -40 >&2 || true
    exit 1
fi
if [ "$size" -lt 100000 ]; then
    echo "FAIL: $SMOKE_URL returned $http but only $size bytes (expected ≥100 KB)" >&2
    exit 1
fi
echo "    OK: $SMOKE_RUN ($((size/1024)) KB range-streamed via R2)"

echo ""
echo "SUCCESS. Live: $PUBLIC_URL/tracker  (audio verified for $SMOKE_RUN)"
