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
import re, sqlite3
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
# Every run registered in experiments.db. The webapp resolves matrix
# coordinates via the DB, so any episode label it surfaces must have
# its run_dir in demo_data — otherwise the cell goes 'missing' even
# though the DB shows it as done. This sweeps in retrofits and any
# future labels the DB knows about.
db_labels = set()
db_path = Path('data/experiments.db')
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    db_labels = {r[0] for r in conn.execute('SELECT label FROM episode')}
    # Also stage every directory referenced by the DB's path columns
    # (hostprep_version.interviews_path / briefs_path,
    # script_version.path, audio_artifact.path / audio_manifest_path).
    # Retrofit episodes keep their canonical label but write hostprep
    # files into a separate timestamped dir; without staging that dir,
    # /api/runs/<id>/prep returns 404 because the DB-resolved path is
    # missing on the container filesystem.
    for path_sql in (
        'SELECT interviews_path FROM hostprep_version WHERE interviews_path IS NOT NULL',
        'SELECT briefs_path FROM hostprep_version WHERE briefs_path IS NOT NULL',
        'SELECT path FROM script_version WHERE path IS NOT NULL',
        'SELECT path FROM audio_artifact WHERE path IS NOT NULL',
        'SELECT audio_manifest_path FROM audio_artifact WHERE audio_manifest_path IS NOT NULL',
    ):
        for (p,) in conn.execute(path_sql):
            parts = Path(p).parts
            if len(parts) >= 3 and parts[0] == 'data' and parts[1] == 'runs':
                db_labels.add(parts[2])
# Legacy panel-script artefacts still referenced by paper/poster. Absent post-migration
# (archived); the existence check in the loop skips them gracefully.
panel_scripts = {
    'arc_v01_baseline', 'arc_v19_all_swapped',
    'hest_trn_v01_baseline_hostprep_refs',
    'hest_trn_v19_all_swapped_hostprep_refs',
}
for name in sorted(grid | inter | alt_gen | versioned | db_labels | panel_scripts):
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
             phase3_episode.json phase3_teaser.json \
             phase2_5_host_briefs.json phase2_5_interviews.json \
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

# Bundle experiments.db so the in-container webapp can serve the matrix
# without scanning the filesystem. The deploy script refreshes it before
# calling stage_demo.sh; here we just copy the current state.
if [ -f data/experiments.db ]; then
    cp data/experiments.db "$DEST/experiments.db"
    echo "Bundled experiments.db ($(du -h data/experiments.db | cut -f1))"
else
    echo "WARN: data/experiments.db not present; webapp will fail to start" >&2
fi

# Regenerate provenance badges
echo "Generating provenance data..."
uv run python scripts/generate_provenance.py > webapp/static/provenance.json

du -sh "$DEST"
