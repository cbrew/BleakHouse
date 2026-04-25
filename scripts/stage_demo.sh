#!/bin/bash
# Stage demo data for fly deployment.
# Creates a lean data/ directory with only the 183 demo runs.
set -euo pipefail

DEST="${1:-demo_data}"
RUNS_SRC="data/runs"

echo "Staging demo data to $DEST/"
rm -rf "$DEST"
mkdir -p "$DEST/runs"

# Generate the list of demo runs (180 tracker grid + 3 interdisciplinary + versioned)
DEMO_RUNS=$(python3 -c "
import re
from pathlib import Path
from enrichment.run_full_matrix import build_matrix
grid = {r['name'] for r in build_matrix()}
inter = {d.name for d in Path('data/runs').iterdir() if 'interdisciplinary' in d.name and (d / 'phase3_episode.json').exists()}
# Alt-generator runs (cerebras_qwen, cerebras_zai_glm, ...) so the demo matrix
# can compare generators side-by-side against the Anthropic default.
alt_gen = {d.name for d in Path('data/runs').iterdir() if '_cerebras_' in d.name and (d / 'phase3_episode.json').exists()}
# Include versioned runs (v1_1, v1_2, etc.) that have a phase3_episode.json or reading list
versioned = set()
for d in Path('data/runs').iterdir():
    if re.search(r'_v1_\d+$', d.name) and (
        (d / 'phase3_episode.json').exists() or (d / 'phase2_5_reading_list.json').exists()
    ):
        versioned.add(d.name)
# Legacy panel-script artefacts still referenced by paper/poster. Absent post-migration
# (archived); the existence check in the loop skips them gracefully.
panel_scripts = {
    'arc_v01_baseline', 'arc_v19_all_swapped',
    'hest_trn_v01_baseline_hostprep_refs',
    'hest_trn_v19_all_swapped_hostprep_refs',
}
for name in sorted(grid | inter | alt_gen | versioned | panel_scripts):
    print(name)
")

count=0
for run in $DEMO_RUNS; do
    src="$RUNS_SRC/$run"
    dst="$DEST/runs/$run"
    [ -d "$src" ] || continue
    mkdir -p "$dst"

    # Copy only files the webapp needs
    for f in manifest.json report.html config.json quote_verification.json \
             phase3_episode.json phase2_5_host_briefs.json phase2_5_interviews.json \
             phase2_5_reading_list.json; do
        [ -f "$src/$f" ] && cp "$src/$f" "$dst/"
    done

    # Copy the per-run audio manifest from the canonical local path.
    # (Pre-2026-04-25 the script also looked at PODCAST_AUDIO_DIR; that
    # layout no longer exists post audio-reorg — the canonical location
    # is data/runs/<run>/audio/manifest.json.)
    if [ -f "$src/audio/manifest.json" ]; then
        mkdir -p "$dst/audio"
        cp "$src/audio/manifest.json" "$dst/audio/"
    fi
    for extra in "$src/audio"/manifest_*.json; do
        [ -f "$extra" ] && mkdir -p "$dst/audio" && cp "$extra" "$dst/audio/"
    done

    # Audio-symlink rewrite for the container build context.
    # Locally, $src/audio/podcast*.mp3 is a symlink pointing into the
    # DVC cache on the external volume. We can't ship that symlink
    # verbatim (target doesn't exist in the container) and we don't
    # want to dereference into the image. Instead, rewrite each
    # symlink so it points at the in-container cache path:
    #   /Volumes/Crucial X9/bleakhouse_audio  →  /app/audio_volume
    # The fly mount makes that path valid at runtime.
    for src_mp3 in "$src/audio"/podcast*.mp3; do
        [ -e "$src_mp3" ] || [ -L "$src_mp3" ] || continue
        fname=$(basename "$src_mp3")
        mkdir -p "$dst/audio"
        if [ -L "$src_mp3" ]; then
            local_target=$(readlink "$src_mp3")
            container_target=${local_target/\/Volumes\/Crucial X9\/bleakhouse_audio/\/app\/audio_volume}
            ln -sfn "$container_target" "$dst/audio/$fname"
        elif [ -f "$src_mp3" ]; then
            cp "$src_mp3" "$dst/audio/$fname"
        fi
    done

    count=$((count + 1))
done

echo "Staged $count runs"

# Regenerate provenance badges
echo "Generating provenance data..."
uv run python scripts/generate_provenance.py > webapp/static/provenance.json

du -sh "$DEST"
