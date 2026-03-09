#!/usr/bin/env bash
# Run Phase 3 (script generation) for 8 selected variants.
# Phase 0-2 already complete — resumes from existing outputs.
set -euo pipefail

RUN="uv run python -m enrichment.run --phase 3 --resume-from 3"

VARIANTS=(
    v01_baseline
    v02_more_jo
    v05_craft_v2
    v10_conservative
    v12_radical_panel
    v14_trevelyan_for_woodcourt
    v18_trevelyan_rosen
    v19_all_swapped
)

for i in "${!VARIANTS[@]}"; do
    v="${VARIANTS[$i]}"
    echo ""
    echo "=== [$((i+1))/${#VARIANTS[@]}] Phase 3: $v ==="
    $RUN --name "$v"
    echo "  Done: $v"
done

echo ""
echo "=== All 8 Phase 3 runs complete ==="
