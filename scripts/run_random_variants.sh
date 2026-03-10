#!/bin/bash
# Run all 20 panel combinations through the random-passages pipeline.
# Each takes ~7-8 min (Phase 0 + Phase 3).
#
# Usage: bash scripts/run_random_variants.sh
#   Or just through Phase 2 (no script generation, ~1 min each):
#     PHASE=2 bash scripts/run_random_variants.sh

set -e

PHASE=${PHASE:-3}
echo "Running random-passages variants through Phase $PHASE"
echo "======================================================"

run_variant() {
    local name="$1"
    shift
    echo ""
    echo "=== $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.random_rag_run --name "$name" --phase "$PHASE" "$@"
    echo "=== $name complete === ($(date +%H:%M:%S))"
}

# --- Original 10 panels ---

run_variant rand_v01_baseline

run_variant rand_v10_conservative \
    --replace-expert "James Blackstone=sir_edmund"

run_variant rand_v11_marxist \
    --replace-expert "Eleanor Hartley=dr_rosen"

run_variant rand_v12_radical_panel \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "James Blackstone=sir_edmund"

run_variant rand_v14_trevelyan_for_woodcourt \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant rand_v15_trevelyan_for_hartley \
    --replace-expert "Eleanor Hartley=trevelyan"

run_variant rand_v16_trevelyan_for_blackstone \
    --replace-expert "James Blackstone=trevelyan"

run_variant rand_v17_trevelyan_edmund \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant rand_v18_trevelyan_rosen \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=dr_rosen"

run_variant rand_v19_all_swapped \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# --- New 10 panels ---

run_variant rand_v21_hartley_blackstone_edmund \
    --replace-expert "Caroline Woodcourt=sir_edmund"

run_variant rand_v22_hartley_blackstone_rosen \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant rand_v23_hartley_woodcourt_rosen \
    --replace-expert "James Blackstone=dr_rosen"

run_variant rand_v24_hartley_edmund_rosen \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant rand_v25_hartley_rosen_trevelyan \
    --replace-expert "James Blackstone=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant rand_v26_blackstone_woodcourt_edmund \
    --replace-expert "Eleanor Hartley=sir_edmund"

run_variant rand_v27_blackstone_edmund_rosen \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant rand_v28_blackstone_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant rand_v29_blackstone_rosen_trevelyan \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant rand_v30_woodcourt_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "James Blackstone=trevelyan"

echo ""
echo "======================================================"
echo "All 20 random-passages variants complete."
echo "Outputs in data/runs/rand_v*/"
