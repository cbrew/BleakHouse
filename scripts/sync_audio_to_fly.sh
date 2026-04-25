#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume.
#
# Walks dvc.lock for phase4_audio@<run> stages, extracts each output's
# md5 hash, computes which blobs are missing on each fly machine, and
# tar-streams just those in a single pipe per machine. Idempotent.
#
# Usage:
#   bash scripts/sync_audio_to_fly.sh
#   bash scripts/sync_audio_to_fly.sh --machine <id>      # single machine
#   bash scripts/sync_audio_to_fly.sh --dry-run           # report only
#
# Prerequisites:
#   - fly CLI authenticated for app bleakhouse-demo
#   - DVC cache at the local cache.dir (.dvc/config)
#   - Target machines reachable via `fly ssh console`

set -euo pipefail

APP="${FLY_APP:-bleakhouse-demo}"
REMOTE_CACHE="/app/audio_volume/dvc-cache/files/md5"
DRY_RUN=0
TARGET_MACHINE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --machine) TARGET_MACHINE="$2"; shift 2 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
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
echo "    machines: $MACHINES"

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: would push up to $HASH_COUNT blob(s) × $(echo "$MACHINES" | wc -w | tr -d ' ') machine(s)"
    exit 0
fi

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
    echo "FAIL: machine $mach did not start" >&2
    return 1
}

for mach in $MACHINES; do
    echo "==> Machine $mach"
    ensure_started "$mach" || exit 1

    # 1) Probe — single SSH session listing what's already there.
    echo "    probing remote cache contents"
    existing_raw=$(fly ssh console -a "$APP" --machine "$mach" -C \
        "sh -c 'mkdir -p $REMOTE_CACHE && find $REMOTE_CACHE -type f -printf \"%P\n\" 2>/dev/null || true'" \
        2>/dev/null || true)
    # Normalise: lines like "3b/bf60a970087e2bd72f96abf054651d" → flat hash strings
    existing_hashes=$(printf '%s\n' "$existing_raw" | tr -d '\r' \
        | awk -F/ 'NF==2 && length($1)==2 {print $1$2}')

    # 2) Diff against expected.
    missing=$(comm -23 <(printf '%s\n' "$HASHES" | sort -u) \
                       <(printf '%s\n' "$existing_hashes" | sort -u))
    missing_count=$(printf '%s\n' "$missing" | grep -c . || true)
    have_count=$(printf '%s\n' "$existing_hashes" | grep -c . || true)
    echo "    existing on remote: $have_count, missing: $missing_count"
    if [ "$missing_count" = "0" ]; then
        echo "    machine $mach: up to date"
        continue
    fi

    # 3) Build a single tar stream of just the missing blobs and pipe it.
    paths_file=$(mktemp -t bh-sync-paths-XXXXXX)
    trap 'rm -f "$paths_file"' EXIT
    : > "$paths_file"
    skipped_local=0
    for h in $missing; do
        prefix="${h:0:2}"; suffix="${h:2}"
        if [ -f "$LOCAL_BLOBS_DIR/$prefix/$suffix" ]; then
            echo "$prefix/$suffix" >> "$paths_file"
        else
            skipped_local=$((skipped_local + 1))
            echo "    WARN: local blob missing: $prefix/$suffix" >&2
        fi
    done
    actual_count=$(wc -l < "$paths_file" | tr -d ' ')
    if [ "$actual_count" = "0" ]; then
        echo "    machine $mach: nothing to push (all missing blobs absent locally)"
        continue
    fi

    # fly ssh console kills sessions somewhere around 300-500 MB of
    # cumulative payload, so we chunk into N-blob batches (~200 MB
    # each) and retry on disconnect.
    BATCH_SIZE="${BATCH_SIZE:-2}"
    MAX_RETRIES="${MAX_RETRIES:-3}"
    pushed_total=0
    pushed_this_run=0
    failed=0

    push_chunk() {
        local chunk_file="$1"
        local n; n=$(wc -l < "$chunk_file" | tr -d ' ')
        local attempt=0
        while [ "$attempt" -lt "$MAX_RETRIES" ]; do
            attempt=$((attempt + 1))
            if tar -cf - -C "$LOCAL_BLOBS_DIR" -T "$chunk_file" \
                 | fly ssh console -a "$APP" --machine "$mach" -C \
                    "sh -c 'cd $REMOTE_CACHE && tar -xf -'" 2>/dev/null; then
                return 0
            fi
            echo "    chunk push attempt $attempt/$MAX_RETRIES failed; sleeping 5s"
            sleep 5
        done
        return 1
    }

    chunk_file=$(mktemp -t bh-sync-chunk-XXXXXX)
    trap 'rm -f "$paths_file" "$chunk_file"' EXIT
    while IFS= read -r line; do
        echo "$line" >> "$chunk_file"
        if [ "$(wc -l < "$chunk_file" | tr -d ' ')" -ge "$BATCH_SIZE" ]; then
            n=$(wc -l < "$chunk_file" | tr -d ' ')
            printf "    streaming %d-blob batch (%d/%d done so far)\n" \
                "$n" "$pushed_total" "$actual_count"
            if push_chunk "$chunk_file"; then
                pushed_total=$((pushed_total + n))
                pushed_this_run=$((pushed_this_run + n))
            else
                echo "FAIL: chunk to machine $mach errored after $MAX_RETRIES retries" >&2
                failed=1; break
            fi
            : > "$chunk_file"
        fi
    done < "$paths_file"

    # Final partial batch.
    if [ "$failed" = "0" ] && [ -s "$chunk_file" ]; then
        n=$(wc -l < "$chunk_file" | tr -d ' ')
        printf "    streaming final %d-blob batch (%d/%d done so far)\n" \
            "$n" "$pushed_total" "$actual_count"
        if push_chunk "$chunk_file"; then
            pushed_total=$((pushed_total + n))
        else
            echo "FAIL: final chunk to machine $mach errored after $MAX_RETRIES retries" >&2
            failed=1
        fi
    fi
    rm -f "$paths_file" "$chunk_file"

    if [ "$failed" = "1" ]; then
        echo "    machine $mach: pushed $pushed_total/$actual_count before failure" >&2
        exit 1
    fi
    echo "    machine $mach: pushed $pushed_total/$actual_count blob(s)"
done

echo "SUCCESS: sync complete"
