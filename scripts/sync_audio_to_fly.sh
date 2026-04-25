#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume.
#
# Transport: fly ssh console + tar pipe, one blob per session. No proxy,
# no rsync, no wireguard. Each session sends one ~95 MB file in ~90s,
# inside fly's per-session lifetime. If a blob fails, retry that one
# blob with a backoff; never lose progress on already-uploaded blobs.
#
# Idempotent: probes the remote cache once per machine and only uploads
# blobs that are missing.
#
# Usage:
#   bash scripts/sync_audio_to_fly.sh
#   bash scripts/sync_audio_to_fly.sh --machine <id>
#   bash scripts/sync_audio_to_fly.sh --dry-run

set -euo pipefail

APP="${FLY_APP:-bleakhouse-demo}"
REMOTE_CACHE="/app/audio_volume/dvc-cache/files/md5"
INTER_BLOB_PAUSE="${INTER_BLOB_PAUSE:-3}"     # seconds between successful blobs
RETRIES_PER_BLOB="${RETRIES_PER_BLOB:-5}"
RETRY_BACKOFF_BASE="${RETRY_BACKOFF_BASE:-5}"
DRY_RUN=0
TARGET_MACHINE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --machine) TARGET_MACHINE="$2"; shift 2 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

CACHE_DIR=$(uv run --no-sync dvc config cache.dir)
[ -d "$CACHE_DIR/files/md5" ] \
    || { echo "FAIL: $CACHE_DIR/files/md5 not found" >&2; exit 1; }
LOCAL_BLOBS_DIR="$CACHE_DIR/files/md5"

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
    MACHINES=$(fly machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    if any(mt.get('name') == 'audio_data' for mt in (m.get('config', {}).get('mounts') or [])):
        print(m['id'])
")
fi
[ -n "$MACHINES" ] || { echo "FAIL: no machines with audio_data volume" >&2; exit 1; }
echo "    machines: $(echo $MACHINES | tr '\n' ' ')"

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: would upload up to $HASH_COUNT blob(s) × $(echo $MACHINES | wc -w | tr -d ' ') machine(s)"
    exit 0
fi

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
    echo "    starting $mach (was: $state)"
    fly machines start "$mach" -a "$APP" >/dev/null
    for _ in $(seq 1 20); do
        state=$(machine_state_live "$mach")
        [ "$state" = "started" ] && return 0
        sleep 2
    done
    echo "FAIL: machine $mach did not reach started state" >&2
    return 1
}

for mach in $MACHINES; do
    echo "==> Machine $mach"
    ensure_started "$mach"

    # Probe what's already there. Ensure the cache dir exists first
    # so `find` doesn't error on a missing directory.
    echo "    probing remote cache"
    existing=$(fly ssh console -a "$APP" --machine "$mach" -C \
        "mkdir -p $REMOTE_CACHE && find $REMOTE_CACHE -type f -printf '%P\n'" \
        | tr -d '\r' \
        | awk -F/ 'NF==2 && length($1)==2 {print $1$2}')
    have=$(printf '%s\n' "$existing" | grep -c . || true)
    echo "    already on remote: $have"

    missing=$(comm -23 <(printf '%s\n' "$HASHES" | sort -u) \
                       <(printf '%s\n' "$existing" | sort -u))
    missing_count=$(printf '%s\n' "$missing" | grep -c . || true)
    if [ "$missing_count" = "0" ]; then
        echo "    machine $mach: up to date"
        continue
    fi
    echo "    missing on remote: $missing_count"

    pushed=0
    failed=()
    for h in $missing; do
        prefix="${h:0:2}"
        suffix="${h:2}"
        local_path="$LOCAL_BLOBS_DIR/$prefix/$suffix"
        if [ ! -f "$local_path" ]; then
            echo "    WARN: local blob missing: $prefix/$suffix" >&2
            continue
        fi
        attempt=0
        while : ; do
            attempt=$((attempt + 1))
            echo "    [$((pushed + 1))/$missing_count] $prefix/$suffix (attempt $attempt)"
            # mkdir prefix dir on remote (cheap), then tar-pipe one blob.
            if fly ssh console -a "$APP" --machine "$mach" -C \
                    "mkdir -p $REMOTE_CACHE/$prefix" >/dev/null 2>&1 \
               && tar -cf - -C "$LOCAL_BLOBS_DIR/$prefix" "$suffix" \
                    | fly ssh console -a "$APP" --machine "$mach" -C \
                        "tar -xf - -C $REMOTE_CACHE/$prefix"; then
                pushed=$((pushed + 1))
                sleep "$INTER_BLOB_PAUSE"
                break
            fi
            if [ "$attempt" -ge "$RETRIES_PER_BLOB" ]; then
                echo "    GIVE UP on $prefix/$suffix after $attempt attempts" >&2
                failed+=("$prefix/$suffix")
                break
            fi
            backoff=$((RETRY_BACKOFF_BASE * attempt))
            echo "    attempt $attempt failed; retrying in ${backoff}s"
            sleep "$backoff"
        done
    done

    echo "    machine $mach: pushed $pushed/$missing_count blob(s)"
    if [ "${#failed[@]}" -gt 0 ]; then
        echo "    failed: ${failed[*]}" >&2
    fi
done

echo "SUCCESS: sync complete"
