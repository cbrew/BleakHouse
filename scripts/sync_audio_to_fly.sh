#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume
# via fly-proxy + rsync.
#
# Per-machine: open a fly proxy → plain ssh; let rsync do the diff and
# transfer in one shot. rsync is installed in the deployed container
# (Containerfile). --partial allows interrupted transfers to resume.
#
# Idempotent and resumable — re-running just diffs against what's
# already on the remote and ships only the missing bytes.
#
# Usage:
#   bash scripts/sync_audio_to_fly.sh
#   bash scripts/sync_audio_to_fly.sh --machine <id>
#   bash scripts/sync_audio_to_fly.sh --dry-run

set -euo pipefail

APP="${FLY_APP:-bleakhouse-demo}"
ORG="${FLY_ORG:-personal}"
REMOTE_CACHE="/app/audio_volume/dvc-cache/files/md5"
DRY_RUN=0
TARGET_MACHINE=""
PROXY_PORT_BASE="${PROXY_PORT_BASE:-12222}"

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --machine) TARGET_MACHINE="$2"; shift 2 ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

CACHE_DIR=$(uv run --no-sync dvc config cache.dir)
[ -d "$CACHE_DIR/files/md5" ] \
    || { echo "FAIL: $CACHE_DIR/files/md5 not found" >&2; exit 1; }
LOCAL_BLOBS_DIR="$CACHE_DIR/files/md5"

# --- Build files-from list (cache-relative paths) ---
echo "==> Collecting phase4_audio blob paths from dvc.lock"
PATHS_FILE=$(mktemp -t bh-sync-paths.XXXXXX)
uv run --no-sync python -c "
import yaml
lock = yaml.safe_load(open('dvc.lock'))
for stage_name, stage in lock.get('stages', {}).items():
    if not stage_name.startswith('phase4_audio@'):
        continue
    for out in stage.get('outs', []):
        h = out.get('md5')
        if h:
            print(f'{h[:2]}/{h[2:]}')
" > "$PATHS_FILE"
files_to_sync=$(wc -l < "$PATHS_FILE" | tr -d ' ')
[ "$files_to_sync" = "0" ] && { echo "nothing to sync"; rm -f "$PATHS_FILE"; exit 0; }
echo "    $files_to_sync blob path(s)"

# --- Resolve machines ---
echo "==> Resolving target machines (app=$APP)"
MACHINES_JSON=$(fly machines list -a "$APP" --json)
if [ -n "$TARGET_MACHINE" ]; then
    MACHINES="$TARGET_MACHINE"
else
    MACHINES=$(printf '%s' "$MACHINES_JSON" | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    if any(mt.get('name') == 'audio_data' for mt in (m.get('config', {}).get('mounts') or [])):
        print(m['id'])
")
fi
[ -n "$MACHINES" ] || { echo "FAIL: no machines with audio_data volume" >&2; rm -f "$PATHS_FILE"; exit 1; }
echo "    machines: $(echo $MACHINES | tr '\n' ' ')"

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: would rsync $files_to_sync blob(s) × $(echo $MACHINES | wc -w | tr -d ' ') machine(s)"
    rm -f "$PATHS_FILE"
    exit 0
fi

# --- Issue temp SSH cert into ssh-agent ---
echo "==> Issuing temporary SSH credential into ssh-agent (1h, org=$ORG)"
fly ssh issue --hours 1 --agent -o "$ORG"

PROXY_PID=""
PROXY_LOG=$(mktemp -t bh-fly-proxy.XXXXXX.log)
cleanup() {
    [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true
    rm -f "$PATHS_FILE" "$PROXY_LOG"
}
trap cleanup EXIT

machine_meta() {
    printf '%s' "$MACHINES_JSON" | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    if m['id'] == '$1':
        print(m.get('private_ip', '') if '$2' == 'ipv6' else m['state'])
"
}

machine_state_live() {
    fly machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    if m['id'] == '$1': print(m['state'])
"
}

ensure_started() {
    local mach="$1"
    local state
    state=$(machine_state_live "$mach")
    [ "$state" = "started" ] && return 0
    echo "    starting (was: $state)"
    fly machines start "$mach" -a "$APP"
    for _ in $(seq 1 20); do
        state=$(machine_state_live "$mach")
        [ "$state" = "started" ] && return 0
        sleep 2
    done
    echo "FAIL: machine $mach did not start" >&2
    return 1
}

port="$PROXY_PORT_BASE"
for mach in $MACHINES; do
    echo "==> Machine $mach"
    ensure_started "$mach"

    ipv6=$(machine_meta "$mach" ipv6)
    [ -n "$ipv6" ] || { echo "FAIL: no IPv6 for $mach" >&2; exit 1; }

    echo "    fly proxy 127.0.0.1:$port → [$ipv6]:22"
    : > "$PROXY_LOG"
    fly proxy "$port:22" -a "$APP" "$ipv6" >"$PROXY_LOG" 2>&1 &
    PROXY_PID=$!

    for _ in $(seq 1 30); do
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then break; fi
        sleep 1
    done
    if ! nc -z 127.0.0.1 "$port" 2>/dev/null; then
        echo "FAIL: fly proxy did not bind 127.0.0.1:$port" >&2
        cat "$PROXY_LOG" >&2 || true
        exit 1
    fi

    SSH_CMD="ssh -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
    $SSH_CMD root@127.0.0.1 "mkdir -p $REMOTE_CACHE"

    echo "    rsync $files_to_sync blob(s) → $mach"
    rsync -av --partial --info=progress2 -R \
        --files-from="$PATHS_FILE" \
        -e "$SSH_CMD" \
        "$LOCAL_BLOBS_DIR/" \
        "root@127.0.0.1:$REMOTE_CACHE/"

    echo "    machine $mach: rsync ok"
    kill "$PROXY_PID" 2>/dev/null || true
    PROXY_PID=""
    port=$((port + 1))
done

echo "SUCCESS: sync complete"
