#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume.
#
# Walks dvc.lock for phase4_audio@<run> stages, extracts each output's
# md5 hash, and tar-pipes the corresponding cache blob to
# /app/audio_volume/dvc-cache/files/md5/<aa>/<bb...> on every machine
# that has the audio_data volume attached.
#
# Idempotent: skips blobs already present at the destination.
#
# Usage:
#   bash scripts/sync_audio_to_fly.sh
#   bash scripts/sync_audio_to_fly.sh --machine <id>      # single machine
#   bash scripts/sync_audio_to_fly.sh --dry-run           # report only
#
# Prerequisites:
#   - fly CLI authenticated for app bleakhouse-demo
#   - DVC cache at /Volumes/Crucial X9/bleakhouse_audio/dvc-cache (or
#     wherever .dvc/config points cache.dir)
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
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

CACHE_DIR=$(uv run --no-sync dvc config cache.dir)
if [ -z "$CACHE_DIR" ] || [ ! -d "$CACHE_DIR" ]; then
    echo "FAIL: cache.dir not configured or missing: '$CACHE_DIR'" >&2
    exit 1
fi
LOCAL_BLOBS_DIR="$CACHE_DIR/files/md5"
[ -d "$LOCAL_BLOBS_DIR" ] || { echo "FAIL: $LOCAL_BLOBS_DIR not found" >&2; exit 1; }

echo "==> Collecting phase4_audio blob hashes from dvc.lock"
HASHES=$(uv run --no-sync python <<'PY'
import yaml
lock = yaml.safe_load(open("dvc.lock"))
for stage_name, stage in lock.get("stages", {}).items():
    if not stage_name.startswith("phase4_audio@"):
        continue
    for out in stage.get("outs", []):
        h = out.get("md5")
        if h:
            print(h)
PY
)
HASH_COUNT=$(echo "$HASHES" | grep -c . || true)
echo "    found $HASH_COUNT phase4_audio blob hashes"

if [ "$HASH_COUNT" = "0" ]; then
    echo "nothing to sync"; exit 0
fi

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
if [ -z "$MACHINES" ]; then
    echo "FAIL: no machines with audio_data volume" >&2
    exit 1
fi
echo "    machines: $MACHINES"

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: would push $HASH_COUNT blob(s) × $(echo "$MACHINES" | wc -w | tr -d ' ') machine(s)"
    exit 0
fi

# For each machine, ensure the machine is started, then push each missing blob.
for mach in $MACHINES; do
    echo "==> Machine $mach"
    state=$(fly machines list -a "$APP" --json | python3 -c "
import json, sys
ms = json.load(sys.stdin)
for m in ms:
    if m['id'] == '$mach': print(m['state'])
")
    if [ "$state" != "started" ]; then
        echo "    starting (was: $state)"
        fly machines start "$mach" -a "$APP" >/dev/null
        # Give the machine a moment to come up.
        for _ in $(seq 1 10); do
            state=$(fly machines list -a "$APP" --json | python3 -c "
import json, sys
ms = json.load(sys.stdin)
for m in ms:
    if m['id'] == '$mach': print(m['state'])
")
            [ "$state" = "started" ] && break
            sleep 2
        done
        if [ "$state" != "started" ]; then
            echo "FAIL: machine $mach did not start" >&2; exit 1
        fi
    fi

    pushed=0
    skipped=0
    for hash in $HASHES; do
        prefix="${hash:0:2}"
        suffix="${hash:2}"
        blob="$LOCAL_BLOBS_DIR/$prefix/$suffix"
        if [ ! -f "$blob" ]; then
            echo "    WARN: local blob missing: $blob — skipping" >&2
            continue
        fi
        # Probe destination for idempotency.
        if fly ssh console -a "$APP" --machine "$mach" -C \
                "test -f $REMOTE_CACHE/$prefix/$suffix" >/dev/null 2>&1; then
            skipped=$((skipped + 1))
            continue
        fi
        # mkdir -p the prefix dir, then tar-pipe.
        fly ssh console -a "$APP" --machine "$mach" -C \
            "mkdir -p $REMOTE_CACHE/$prefix" >/dev/null
        tar cf - -C "$LOCAL_BLOBS_DIR/$prefix" "$suffix" \
          | fly ssh console -a "$APP" --machine "$mach" -C \
                "tar xf - -C $REMOTE_CACHE/$prefix" >/dev/null
        pushed=$((pushed + 1))
        echo "    pushed: $prefix/$suffix"
    done
    echo "    machine $mach: $pushed pushed, $skipped already present"
done

echo "SUCCESS: synced $HASH_COUNT blob(s) to $(echo "$MACHINES" | wc -w | tr -d ' ') machine(s)"
