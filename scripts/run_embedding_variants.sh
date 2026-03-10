#!/bin/bash
# Run 8 embedding pipeline variants matched to the transport variants.
# Each takes ~7-8 minutes (Phase 0 + retrieval + curation + Phase 3).
#
# Usage: bash scripts/run_embedding_variants.sh
#   Or to run just through Phase 2 (no script generation, ~2 min each):
#     PHASE=2 bash scripts/run_embedding_variants.sh

set -e

PHASE=${PHASE:-3}
echo "Running embedding variants through Phase $PHASE"
echo "================================================"

run_variant() {
    local name="$1"
    shift
    echo ""
    echo "=== $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.embedding_run --name "$name" --phase "$PHASE" "$@"
    echo "=== $name complete === ($(date +%H:%M:%S))"
}

# 1. Baseline — default experts, default arcs
run_variant emb_v01_baseline

# 2. More Jo — arc demand override
run_variant emb_v02_more_jo \
    --arc-demand "Jo's suffering=8"

# 3. Craft v2 — boosted Hartley demands
run_variant emb_v05_craft_v2 \
    --expert-demand "Eleanor Hartley:prov_narrative_technique=4" \
    --expert-demand "Eleanor Hartley:prov_thematic_depth=3"

# 4. Conservative — Edmund Leigh replaces Blackstone
run_variant emb_v10_conservative \
    --replace-expert "James Blackstone=sir_edmund"

# 5. Radical panel — Edmund + Rosen replace Hartley + Blackstone
run_variant emb_v12_radical_panel \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "James Blackstone=sir_edmund"

# 6. Trevelyan for Woodcourt
run_variant emb_v14_trevelyan_for_woodcourt \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 7. Trevelyan + Rosen
run_variant emb_v18_trevelyan_rosen \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=dr_rosen"

# 8. All swapped
run_variant emb_v19_all_swapped \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

echo ""
echo "================================================"
echo "All 8 embedding variants complete."
echo "Outputs in data/runs/emb_v*/"
