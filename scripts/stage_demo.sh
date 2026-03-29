#!/bin/bash
# Stage demo data for fly deployment.
# Creates a lean data/ directory with only the 183 demo runs.
set -euo pipefail

DEST="${1:-demo_data}"
RUNS_SRC="data/runs"

echo "Staging demo data to $DEST/"
rm -rf "$DEST"
mkdir -p "$DEST/runs"

# Generate the list of demo runs (180 tracker grid + 3 interdisciplinary)
DEMO_RUNS=$(python3 -c "
from enrichment.run_full_matrix import build_matrix
grid = {r['name'] for r in build_matrix()}
inter = {'interdisciplinary_trn_hostprep', 'interdisciplinary_emb_hostprep', 'interdisciplinary_nop_hostprep'}
for name in sorted(grid | inter):
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
             phase3_episode.json phase2_5_host_briefs.json phase2_5_interviews.json; do
        [ -f "$src/$f" ] && cp "$src/$f" "$dst/"
    done

    # Copy audio manifest (not the mp3)
    if [ -f "$src/audio/manifest.json" ]; then
        mkdir -p "$dst/audio"
        cp "$src/audio/manifest.json" "$dst/audio/"
    fi

    count=$((count + 1))
done

echo "Staged $count runs"

# Regenerate provenance badges
echo "Generating provenance data..."
uv run python scripts/generate_provenance.py > webapp/static/provenance.json

du -sh "$DEST"
