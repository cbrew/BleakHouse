#!/bin/bash
# Run all 20 panel combinations through the no-passages pipeline.
# Each takes ~5 min (Phase 0 + Phase 3, no retrieval).
#
# Usage: bash scripts/run_no_passages_variants.sh

set -e

echo "Running no-passages variants (prior knowledge baseline)"
echo "========================================================"

run_variant() {
    local name="$1"
    shift
    echo ""
    echo "=== $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.no_passages_run --novel bleak_house --name "$name" "$@"
    echo "=== $name complete === ($(date +%H:%M:%S))"
}

# --- Original 10 panels ---

run_variant nop_v01_baseline

run_variant nop_v10_conservative \
    --replace-expert "James Blackstone=sir_edmund"

run_variant nop_v11_marxist \
    --replace-expert "Eleanor Hartley=dr_rosen"

run_variant nop_v12_radical_panel \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "James Blackstone=sir_edmund"

run_variant nop_v14_trevelyan_for_woodcourt \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant nop_v15_trevelyan_for_hartley \
    --replace-expert "Eleanor Hartley=trevelyan"

run_variant nop_v16_trevelyan_for_blackstone \
    --replace-expert "James Blackstone=trevelyan"

run_variant nop_v17_trevelyan_edmund \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant nop_v18_trevelyan_rosen \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=dr_rosen"

run_variant nop_v19_all_swapped \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# --- New 10 panels ---

run_variant nop_v21_hartley_blackstone_edmund \
    --replace-expert "Caroline Woodcourt=sir_edmund"

run_variant nop_v22_hartley_blackstone_rosen \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant nop_v23_hartley_woodcourt_rosen \
    --replace-expert "James Blackstone=dr_rosen"

run_variant nop_v24_hartley_edmund_rosen \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant nop_v25_hartley_rosen_trevelyan \
    --replace-expert "James Blackstone=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant nop_v26_blackstone_woodcourt_edmund \
    --replace-expert "Eleanor Hartley=sir_edmund"

run_variant nop_v27_blackstone_edmund_rosen \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

run_variant nop_v28_blackstone_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant nop_v29_blackstone_rosen_trevelyan \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

run_variant nop_v30_woodcourt_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "James Blackstone=trevelyan"

echo ""
echo "========================================================"
echo "All 20 no-passages variants complete."
echo "Outputs in data/runs/nop_v*/"
