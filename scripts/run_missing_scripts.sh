#!/bin/bash
# Generate Phase 3 scripts for 12 older transport runs stuck at phase2.
# Uses --resume-from 3 to skip Phases 0-2.

set -e

VARIANTS=(
    v03_strict
    v04_craft_focus
    v06_quality
    v07_skip_dedlock
    v08_tight_budget
    v09_diverse
    v11_marxist
    v13_rosen_jo
    v15_trevelyan_for_hartley
    v16_trevelyan_for_blackstone
    v17_trevelyan_edmund
    v20_trevelyan_jo
)

echo "Generating Phase 3 scripts for ${#VARIANTS[@]} variants"
echo "================================================"

for name in "${VARIANTS[@]}"; do
    echo ""
    echo "=== $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.run --novel bleak_house --name "$name" --resume-from 3
    echo "=== $name complete === ($(date +%H:%M:%S))"
done

echo ""
echo "================================================"
echo "All ${#VARIANTS[@]} scripts complete."
