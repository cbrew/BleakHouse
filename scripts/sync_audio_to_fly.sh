#!/bin/bash
# Sync DVC cache blobs for phase4_audio outs to the fly audio_data volume
# via fly-proxy + plain ssh + scp.
#
# Why this transport: fly ssh console + tar pipe has a hard ~50 MB /
# 2-min ceiling per session. fly proxy <local>:22 <ipv6> exposes the
# machine's port 22 on localhost, then we use plain ssh+scp over TCP —
# no fly-ssh wrapper, no session ceiling. Verified 95 MB blob in 70s.
#
# rsync would be nicer (diff + --partial) but the deployed image
# doesn't have rsync. scp + a manual probe-and-skip is enough.
#
# Idempotent: probes the remote cache once per machine and only scp's
# blobs that are missing.
#
# Errors are NOT silenced — if anything goes wrong, you see the message.
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
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
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
MACHINES_JSON=$(fly machines list -a "$APP" --json)
if [ -n "$TARGET_MACHINE" ]; then
    MACHINES="$TARGET_MACHINE"
else
    MACHINES=$(printf '%s' "$MACHINES_JSON" | python3 -c "
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
    echo "--dry-run: would sync up to $HASH_COUNT blob(s) × $(echo $MACHINES | wc -w | tr -d ' ') machine(s)"
    exit 0
fi

# --- Issue temp SSH cert into ssh-agent ---
echo "==> Issuing temporary SSH credential into ssh-agent (1h, org=$ORG)"
fly ssh issue --hours 1 --agent -o "$ORG"
ssh-add -L 2>/dev/null | grep -q . \
    || { echo "FAIL: ssh-agent has no identity after fly ssh issue" >&2; exit 1; }

PROXY_PID=""
PROXY_LOG=$(mktemp -t bh-fly-proxy-XXXXXX.log)
trap '[ -n "$PROXY_PID" ] && kill $PROXY_PID 2>/dev/null || true; rm -f "$PROXY_LOG"' EXIT

machine_meta() {
    # $1=machine id, $2=field (state|ipv6)
    printf '%s' "$MACHINES_JSON" | python3 -c "
import json, sys
ms = json.load(sys.stdin)
for m in ms:
    if m['id'] == '$1':
        if '$2' == 'state':
            print(m['state'])
        elif '$2' == 'ipv6':
            print(m.get('private_ip', ''))
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
    if [ "$state" = "started" ]; then return 0; fi
    echo "    starting (was: $state)"
    fly machines start "$mach" -a "$APP"
    for _ in $(seq 1 20); do
        state=$(machine_state_live "$mach")
        [ "$state" = "started" ] && return 0
        sleep 2
    done
    echo "FAIL: machine $mach did not reach started state" >&2
    return 1
}

push_machine() {
    local mach="$1"
    local port="$2"

    ensure_started "$mach"

    local ipv6
    ipv6=$(machine_meta "$mach" ipv6)
    [ -n "$ipv6" ] || { echo "FAIL: no IPv6 for $mach" >&2; return 1; }
    echo "    fly proxy: 127.0.0.1:$port → [$ipv6]:22"

    : > "$PROXY_LOG"
    fly proxy "$port:22" -a "$APP" "$ipv6" >"$PROXY_LOG" 2>&1 &
    PROXY_PID=$!

    # Wait for the proxy to bind. fly proxy logs "Proxying ..." when ready.
    local ready=0
    for _ in $(seq 1 30); do
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then ready=1; break; fi
        sleep 1
    done
    if [ "$ready" = "0" ]; then
        echo "FAIL: fly proxy did not bind 127.0.0.1:$port — proxy log:" >&2
        cat "$PROXY_LOG" >&2 || true
        kill "$PROXY_PID" 2>/dev/null || true; PROXY_PID=""
        return 1
    fi

    SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

    # 1. Probe existing blobs.
    echo "    probing remote cache"
    existing_raw=$(ssh -p "$port" $SSH_OPTS root@127.0.0.1 \
        "mkdir -p $REMOTE_CACHE && find $REMOTE_CACHE -type f -printf '%P\n'") \
        || { echo "FAIL: ssh probe failed" >&2; kill $PROXY_PID 2>/dev/null; PROXY_PID=""; return 1; }
    existing_hashes=$(printf '%s\n' "$existing_raw" | tr -d '\r' \
        | awk -F/ 'NF==2 && length($1)==2 {print $1$2}')
    have_count=$(printf '%s\n' "$existing_hashes" | grep -c . || true)
    echo "    existing on remote: $have_count"

    # 2. Compute missing list.
    missing=$(comm -23 <(printf '%s\n' "$HASHES" | sort -u) \
                       <(printf '%s\n' "$existing_hashes" | sort -u))
    missing_count=$(printf '%s\n' "$missing" | grep -c . || true)
    if [ "$missing_count" = "0" ]; then
        echo "    machine $mach: already up to date"
        kill "$PROXY_PID" 2>/dev/null || true; PROXY_PID=""
        return 0
    fi
    echo "    missing on remote: $missing_count"

    # 3. scp each missing blob (one ssh session per blob; fly proxy
    #    keeps the connection layer stable so this works fine).
    pushed=0
    for h in $missing; do
        prefix="${h:0:2}"; suffix="${h:2}"
        local_path="$LOCAL_BLOBS_DIR/$prefix/$suffix"
        if [ ! -f "$local_path" ]; then
            echo "    WARN: local blob missing: $prefix/$suffix" >&2
            continue
        fi
        echo "    [$((pushed + 1))/$missing_count] $prefix/$suffix"
        ssh -p "$port" $SSH_OPTS root@127.0.0.1 "mkdir -p $REMOTE_CACHE/$prefix" \
            || { echo "FAIL: mkdir for $prefix failed" >&2; kill $PROXY_PID 2>/dev/null; PROXY_PID=""; return 1; }
        scp -P "$port" $SSH_OPTS \
            "$local_path" "root@127.0.0.1:$REMOTE_CACHE/$prefix/$suffix" \
            || { echo "FAIL: scp $prefix/$suffix failed" >&2; kill $PROXY_PID 2>/dev/null; PROXY_PID=""; return 1; }
        pushed=$((pushed + 1))
    done
    echo "    machine $mach: pushed $pushed/$missing_count blob(s)"

    kill "$PROXY_PID" 2>/dev/null || true; PROXY_PID=""
}

port="$PROXY_PORT_BASE"
for mach in $MACHINES; do
    echo "==> Machine $mach"
    push_machine "$mach" "$port"
    port=$((port + 1))
done

echo "SUCCESS: sync complete"
