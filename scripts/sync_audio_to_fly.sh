#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume
# via fly-proxy + rsync.
#
# Why not `fly ssh console + tar pipe`: fly's ssh-console wrapper kills
# sessions around ~50 MB / 2 minutes per stream. rsync over a fly-proxy
# tunnel uses TCP directly, handles retries natively, and resumes
# partial transfers via --partial.
#
# Idempotent — rsync will only re-send files whose size/checksum differ.
#
# Usage:
#   bash scripts/sync_audio_to_fly.sh
#   bash scripts/sync_audio_to_fly.sh --machine <id>      # single machine
#   bash scripts/sync_audio_to_fly.sh --dry-run           # report only
#
# Prerequisites:
#   - fly CLI authenticated for app bleakhouse-demo
#   - rsync installed locally
#   - DVC cache at the local cache.dir (.dvc/config)

set -euo pipefail

APP="${FLY_APP:-bleakhouse-demo}"
REMOTE_CACHE="/app/audio_volume/dvc-cache/files/md5"
DRY_RUN=0
TARGET_MACHINE=""
PROXY_PORT_BASE="${PROXY_PORT_BASE:-12222}"  # local port for fly proxy

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --machine) TARGET_MACHINE="$2"; shift 2 ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

CACHE_DIR=$(uv run --no-sync dvc config cache.dir)
[ -n "$CACHE_DIR" ] && [ -d "$CACHE_DIR" ] \
    || { echo "FAIL: cache.dir not configured or missing: '$CACHE_DIR'" >&2; exit 1; }
LOCAL_BLOBS_DIR="$CACHE_DIR/files/md5"
[ -d "$LOCAL_BLOBS_DIR" ] || { echo "FAIL: $LOCAL_BLOBS_DIR not found" >&2; exit 1; }

echo "==> Collecting phase4_audio blob hashes from dvc.lock"
HASHES=$(uv run --no-sync python -c "
import yaml
lock = yaml.safe_load(open('dvc.lock'))
for stage_name, stage in lock.get('stages', {}).items():
    if not stage_name.startswith('phase4_audio@'):
        continue
    for out in stage.get('outs', []):
        h = out.get('md5')
        if h:
            print(h)
")
HASH_COUNT=$(printf '%s\n' "$HASHES" | grep -c . || true)
echo "    found $HASH_COUNT phase4_audio blob hashes"
[ "$HASH_COUNT" = "0" ] && { echo "nothing to sync"; exit 0; }

echo "==> Resolving target machines (app=$APP)"
if [ -n "$TARGET_MACHINE" ]; then
    MACHINES="$TARGET_MACHINE"
else
    MACHINES=$(fly machines list -a "$APP" --json 2>/dev/null \
        | python3 -c "
import json, sys
ms = json.load(sys.stdin)
for m in ms:
    if any(mt.get('name') == 'audio_data' for mt in (m.get('config', {}).get('mounts') or [])):
        print(m['id'])
")
fi
[ -n "$MACHINES" ] || { echo "FAIL: no machines with audio_data volume" >&2; exit 1; }
echo "    machines: $(echo $MACHINES | tr '\n' ' ')"

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: would sync $HASH_COUNT blob(s) × $(echo $MACHINES | wc -w | tr -d ' ') machine(s) via fly proxy + rsync"
    exit 0
fi

# --- Build the files-from list (cache-relative paths like aa/bb...) ---
PATHS_FILE=$(mktemp -t bh-sync-paths-XXXXXX)
trap 'rm -f "$PATHS_FILE" "$SSH_KEY" 2>/dev/null || true; [ -n "${PROXY_PID:-}" ] && kill $PROXY_PID 2>/dev/null || true' EXIT
for h in $HASHES; do
    prefix="${h:0:2}"; suffix="${h:2}"
    if [ -f "$LOCAL_BLOBS_DIR/$prefix/$suffix" ]; then
        echo "$prefix/$suffix" >> "$PATHS_FILE"
    else
        echo "    WARN: local blob missing: $prefix/$suffix" >&2
    fi
done
files_to_sync=$(wc -l < "$PATHS_FILE" | tr -d ' ')
echo "    paths-from list: $files_to_sync blob(s)"

# --- Issue a temporary SSH cert ---
SSH_KEY=$(mktemp -t fly_ssh_key_XXXXXX)
SSH_KEY_PUB="${SSH_KEY}-cert.pub"
echo "==> Issuing temporary SSH credential (1h)"
# fly ssh issue is org-scoped, not app-scoped — no -a flag. Writes to
# <path> (private key) and <path>-cert.pub (signed certificate).
fly ssh issue --hours 1 --overwrite "$SSH_KEY"
[ -f "$SSH_KEY" ] || { echo "FAIL: SSH cert not issued at $SSH_KEY" >&2; exit 1; }
chmod 600 "$SSH_KEY"

machine_state() {
    fly machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json, sys
ms = json.load(sys.stdin)
for m in ms:
    if m['id'] == '$1': print(m['state'])
"
}

ensure_started() {
    local mach="$1"
    local state
    state=$(machine_state "$mach")
    if [ "$state" = "started" ]; then return 0; fi
    echo "    starting (was: $state)"
    fly machines start "$mach" -a "$APP" >/dev/null
    for _ in $(seq 1 15); do
        state=$(machine_state "$mach")
        [ "$state" = "started" ] && return 0
        sleep 2
    done
    echo "FAIL: machine $mach did not start" >&2; return 1
}

PROXY_PID=""

push_machine() {
    local mach="$1"
    local port="$2"

    ensure_started "$mach"

    echo "    starting fly proxy on localhost:$port → $mach:22"
    fly proxy "$port:22" -a "$APP" --machine "$mach" >/dev/null 2>&1 &
    PROXY_PID=$!

    # Wait for the proxy to accept TCP.
    for _ in $(seq 1 30); do
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then break; fi
        sleep 1
    done
    if ! nc -z 127.0.0.1 "$port" 2>/dev/null; then
        echo "FAIL: fly proxy didn't open port $port" >&2
        kill "$PROXY_PID" 2>/dev/null || true
        PROXY_PID=""
        return 1
    fi

    SSH_OPTS="-p $port -i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
    # mkdir -p the cache root.
    ssh $SSH_OPTS root@127.0.0.1 "mkdir -p $REMOTE_CACHE" \
        || { echo "FAIL: ssh mkdir on $mach" >&2; kill $PROXY_PID 2>/dev/null; PROXY_PID=""; return 1; }

    echo "    rsync $files_to_sync blob(s) → $mach"
    if rsync -av --partial --info=progress2 -R \
            --files-from="$PATHS_FILE" \
            -e "ssh $SSH_OPTS" \
            "$LOCAL_BLOBS_DIR/" "root@127.0.0.1:$REMOTE_CACHE/"; then
        echo "    machine $mach: rsync ok"
    else
        echo "FAIL: rsync to $mach errored" >&2
        kill $PROXY_PID 2>/dev/null; PROXY_PID=""
        return 1
    fi

    kill "$PROXY_PID" 2>/dev/null || true
    PROXY_PID=""
}

port="$PROXY_PORT_BASE"
for mach in $MACHINES; do
    echo "==> Machine $mach"
    push_machine "$mach" "$port" || exit 1
    port=$((port + 1))
done

echo "SUCCESS: sync complete"
