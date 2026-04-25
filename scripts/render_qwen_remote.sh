#!/bin/bash
# Render a Qwen TTS episode for one canonical run.
#
# Pipeline (all per-run, no cross-pollination):
#   1. Stage current run dir + chosen Gemini source MP3 to pop-os.
#   2. Sync experiments/qwen_tts/* to pop-os so the renderer code matches HEAD.
#   3. Extract refs from the Gemini source on pop-os.
#   4. Render via Qwen3-TTS on the pop-os GPU.
#   5. rsync episode.wav back, convert to mp3 locally.
#   6. Write manifest_qwen.json from the render's episode.json metadata.
#
# Usage:
#   scripts/render_qwen_remote.sh <run_id> [--ref-source <path>]
#
# By default the ref source is data/runs/<run_id>/audio/podcast.mp3.
# Override with --ref-source for runs whose own Gemini render isn't
# in the DVC-tracked location (e.g. bh_trn_alternatives_hostprep
# borrows from /Volumes/Crucial X9/.../_audio_archive/...).

set -euo pipefail

RUN=""
REF_SOURCE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --ref-source) REF_SOURCE="$2"; shift 2 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        -*) echo "unknown arg: $1" >&2; exit 2 ;;
        *)  RUN="$1"; shift ;;
    esac
done

[ -n "$RUN" ] || { echo "FAIL: <run_id> required" >&2; exit 2; }

cd "$(dirname "$0")/.."

LOCAL_RUN_DIR="data/runs/$RUN"
[ -d "$LOCAL_RUN_DIR" ] || { echo "FAIL: $LOCAL_RUN_DIR not found" >&2; exit 1; }
[ -f "$LOCAL_RUN_DIR/phase3_episode.json" ] \
    || { echo "FAIL: $LOCAL_RUN_DIR/phase3_episode.json missing" >&2; exit 1; }

if [ -z "$REF_SOURCE" ]; then
    REF_SOURCE="$LOCAL_RUN_DIR/audio/podcast.mp3"
fi
if [ ! -e "$REF_SOURCE" ] && [ ! -L "$REF_SOURCE" ]; then
    echo "FAIL: ref source $REF_SOURCE not found" >&2
    exit 1
fi
# Resolve symlink so rsync can transfer the actual bytes (the symlink
# target lives under /Volumes/... which pop-os can't see).
REF_SOURCE_RESOLVED=$(python3 -c "import pathlib; print(pathlib.Path('$REF_SOURCE').resolve())")
[ -f "$REF_SOURCE_RESOLVED" ] || { echo "FAIL: ref source resolves to missing $REF_SOURCE_RESOLVED" >&2; exit 1; }

POPHOST="${POPHOST:-cbrew@pop-os.local}"
REMOTE_BASE="${REMOTE_BASE:-/home/cbrew/bleakhouse-qwen-tts}"
REMOTE_RUN_DIR="$REMOTE_BASE/run_$RUN"
REMOTE_REFS_DIR="$REMOTE_BASE/refs_$RUN"
REMOTE_OUT_DIR="$REMOTE_BASE/out_$RUN"
REMOTE_REF_SOURCE="$REMOTE_RUN_DIR/audio/podcast.mp3"

echo "==> [1/6] sync run dir + ref source MP3 to $POPHOST"
ssh "$POPHOST" "mkdir -p $REMOTE_RUN_DIR/audio"
rsync -a --delete \
    --include='phase3_episode.json' --include='config.json' --include='manifest.json' \
    --include='phase2_5_*.json' --include='phase2_plan.json' \
    --exclude='*' \
    "$LOCAL_RUN_DIR/" "$POPHOST:$REMOTE_RUN_DIR/"
rsync -a "$REF_SOURCE_RESOLVED" "$POPHOST:$REMOTE_REF_SOURCE"
echo "    run dir + ref MP3 ($(du -h "$REF_SOURCE_RESOLVED" | awk '{print $1}')) on remote"

echo "==> [2/6] sync renderer code (HEAD) to $POPHOST"
rsync -a --delete experiments/qwen_tts/ "$POPHOST:$REMOTE_BASE/experiments/qwen_tts/"

echo "==> [3/6] extract refs (per-speaker first-turn voice clips, F0-validated)"
# && chain short-circuits on first failure; ssh returns that exit
# code. The earlier version's `| tail -30` masked the python error.
ssh "$POPHOST" "cd $REMOTE_BASE && rm -rf $REMOTE_REFS_DIR && mkdir -p $REMOTE_REFS_DIR && \
    .venv/bin/python -m experiments.qwen_tts.extract_refs \
        --run $REMOTE_RUN_DIR \
        --out $REMOTE_REFS_DIR \
        --audio $REMOTE_REF_SOURCE"

echo "==> [4/6] render full episode on GPU (this is the slow step)"
# render_episode.py treats --out as a directory and writes episode.wav
# + episode.json + segment_NN.wav inside it.
ssh "$POPHOST" "cd $REMOTE_BASE && rm -rf $REMOTE_OUT_DIR && mkdir -p $REMOTE_OUT_DIR && \
    .venv/bin/python -m experiments.qwen_tts.render_episode \
        --run $REMOTE_RUN_DIR \
        --refs $REMOTE_REFS_DIR \
        --out $REMOTE_OUT_DIR"

echo "==> [5/6] pull episode.wav + episode.json back"
mkdir -p "$LOCAL_RUN_DIR/audio"
rsync -a --info=progress2 \
    "$POPHOST:$REMOTE_OUT_DIR/episode.wav" "$LOCAL_RUN_DIR/audio/podcast_qwen.wav"
rsync -a "$POPHOST:$REMOTE_OUT_DIR/episode.json" "$LOCAL_RUN_DIR/audio/manifest_qwen.json"

echo "==> [6/6] convert wav → mp3 locally"
# -loglevel error keeps progress lines off but lets real errors through.
ffmpeg -y -loglevel error -i "$LOCAL_RUN_DIR/audio/podcast_qwen.wav" \
    -b:a 192k "$LOCAL_RUN_DIR/audio/podcast_qwen.mp3"
rm "$LOCAL_RUN_DIR/audio/podcast_qwen.wav"

ls -la "$LOCAL_RUN_DIR/audio/podcast_qwen.mp3" "$LOCAL_RUN_DIR/audio/manifest_qwen.json"
echo "SUCCESS: $RUN qwen render landed at $LOCAL_RUN_DIR/audio/"
