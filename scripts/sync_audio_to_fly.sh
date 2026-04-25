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

probe_existing_hashes() {
    local mach="$1"
    fly ssh console -a "$APP" --machine "$mach" -C "mkdir -p $REMOTE_CACHE"
    fly ssh console -a "$APP" --machine "$mach" -C \
        "find $REMOTE_CACHE -type f -printf %P\\n" \
        | tr -d '\r' \
        | awk -F/ 'NF==2 && length($1)==2 {print $1$2}' \
        | sort -u
}

push_missing_in_one_stream() {
    # One tar pipe of all currently-missing blobs. Returns the
    # PIPESTATUS of (tar, fly_ssh) joined with a colon — caller
    # decides what to do.
    local mach="$1"
    local paths_file
    paths_file=$(mktemp -t bh-tar-paths.XXXXXX)
    local existing missing
    existing=$(probe_existing_hashes "$mach")
    missing=$(comm -23 <(printf '%s\n' "$HASHES" | sort -u) \
                       <(printf '%s\n' "$existing" | sort -u))
    : > "$paths_file"
    for h in $missing; do
        prefix="${h:0:2}"; suffix="${h:2}"
        [ -f "$LOCAL_BLOBS_DIR/$prefix/$suffix" ] \
            && echo "$prefix/$suffix" >> "$paths_file"
    done
    local n
    n=$(wc -l < "$paths_file" | tr -d ' ')
    if [ "$n" = "0" ]; then
        rm -f "$paths_file"
        echo "0:0"
        return
    fi
    echo "    streaming $n blob(s) → $mach" >&2
    set +e
    tar -cf - --totals -C "$LOCAL_BLOBS_DIR" -T "$paths_file" \
      | fly ssh console -a "$APP" --machine "$mach" -C "tar -xvf - -C $REMOTE_CACHE"
    # Capture all of PIPESTATUS in one go — assigning out of it twice
    # resets the array between reads.
    local pstat=("${PIPESTATUS[@]}")
    set -e
    rm -f "$paths_file"
    echo "${pstat[0]:-?}:${pstat[1]:-?}"
}

for mach in $MACHINES; do
    echo "==> Machine $mach"
    ensure_started "$mach"

    pass=0
    MAX_STREAM_PASSES="${MAX_STREAM_PASSES:-25}"
    while : ; do
        pass=$((pass + 1))
        echo "    pass $pass"
        rc=$(push_missing_in_one_stream "$mach")
        rc_tar="${rc%:*}"; rc_ssh="${rc#*:}"

        existing=$(probe_existing_hashes "$mach")
        landed=$(printf '%s\n' "$existing" | grep -c . || true)
        echo "    pass $pass: tar=$rc_tar fly_ssh=$rc_ssh — $landed/$HASH_COUNT blob(s) on remote"

        if [ "$landed" -ge "$HASH_COUNT" ]; then
            echo "    machine $mach: complete after $pass pass(es)"
            break
        fi
        if [ "$pass" -ge "$MAX_STREAM_PASSES" ]; then
            echo "FAIL: machine $mach stuck at $landed/$HASH_COUNT after $pass passes" >&2
            exit 1
        fi
        # If the previous pass made no progress, sleep longer to let
        # any flakiness clear.
        if [ "${prev_landed:-0}" = "$landed" ]; then
            echo "    no progress; sleeping 30s before next pass"
            sleep 30
        else
            sleep 5
        fi
        prev_landed="$landed"
        ensure_started "$mach"  # in case auto-stop triggered
    done
    unset prev_landed
done

echo "SUCCESS: all machines fully synced"

echo "SUCCESS: sync complete"
