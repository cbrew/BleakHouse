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
#   4. sync_audio_to_fly.sh — push DVC audio blobs to the fly volume(s)
#      so the deployed container's audio symlinks resolve. Idempotent.
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

echo "==> [4/7] Sync DVC audio cache to fly volume(s)"
bash scripts/sync_audio_to_fly.sh

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

echo ""
echo "SUCCESS. Live: $PUBLIC_URL/tracker"
