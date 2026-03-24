#!/bin/bash
# Resume Phase 3 (Sonnet script generation) for all transport runs missing it.
# Runs in batches of 3 to stay within Sonnet rate limits.
set -e
cd /Users/brewc/PycharmProjects/BleakHouse

# Map run name -> replace-expert flags
declare -A PANEL_FLAGS
PANEL_FLAGS[arc_v10_conservative]="--replace-expert 'James Blackstone=sir_edmund'"
PANEL_FLAGS[arc_v12_radical_panel]="--replace-expert 'Eleanor Hartley=dr_rosen' --replace-expert 'James Blackstone=sir_edmund'"
PANEL_FLAGS[arc_v14_trevelyan_for_woodcourt]="--replace-expert 'Caroline Woodcourt=trevelyan'"
PANEL_FLAGS[arc_v15_trevelyan_for_hartley]="--replace-expert 'Eleanor Hartley=trevelyan'"
PANEL_FLAGS[arc_v16_trevelyan_for_blackstone]="--replace-expert 'James Blackstone=trevelyan'"
PANEL_FLAGS[arc_v17_trevelyan_edmund]="--replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=trevelyan'"
PANEL_FLAGS[arc_v18_trevelyan_rosen]="--replace-expert 'Eleanor Hartley=trevelyan' --replace-expert 'James Blackstone=dr_rosen'"
PANEL_FLAGS[arc_v19_all_swapped]="--replace-expert 'Eleanor Hartley=trevelyan' --replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
PANEL_FLAGS[arc_v23_hartley_woodcourt_rosen]="--replace-expert 'James Blackstone=dr_rosen'"
PANEL_FLAGS[arc_v24_hartley_edmund_rosen]="--replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
PANEL_FLAGS[arc_v25_hartley_rosen_trevelyan]="--replace-expert 'James Blackstone=dr_rosen' --replace-expert 'Caroline Woodcourt=trevelyan'"
PANEL_FLAGS[arc_v26_blackstone_woodcourt_edmund]="--replace-expert 'Eleanor Hartley=sir_edmund'"
PANEL_FLAGS[arc_v27_blackstone_edmund_rosen]="--replace-expert 'Eleanor Hartley=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
PANEL_FLAGS[arc_v28_blackstone_edmund_trevelyan]="--replace-expert 'Eleanor Hartley=sir_edmund' --replace-expert 'Caroline Woodcourt=trevelyan'"
PANEL_FLAGS[arc_v29_blackstone_rosen_trevelyan]="--replace-expert 'Eleanor Hartley=dr_rosen' --replace-expert 'Caroline Woodcourt=trevelyan'"

# Collect runs missing phase3
MISSING=()
for name in "${!PANEL_FLAGS[@]}"; do
    if [ ! -f "data/runs/${name}/phase3_episode.json" ]; then
        MISSING+=("$name")
    fi
done

echo "Missing Phase 3: ${#MISSING[@]} runs"
echo "${MISSING[@]}" | tr ' ' '\n' | sort

BATCH_SIZE=3
total=${#MISSING[@]}
for ((i=0; i<total; i+=BATCH_SIZE)); do
    batch=("${MISSING[@]:i:BATCH_SIZE}")
    echo ""
    echo "=== Batch starting at index $i (${#batch[@]} runs) ==="

    for name in "${batch[@]}"; do
        flags="${PANEL_FLAGS[$name]}"
        echo "  Starting $name ..."
        eval uv run python -m enrichment.run_pipeline --pipeline transport --novel bleak_house \
            --name "$name" \
            --resume-from 3 \
            $flags \
            2>&1 | tail -3 &
    done

    echo "  Waiting for batch to complete..."
    wait
    echo "  Batch complete."
done

echo ""
echo "=== All done ==="
# Verify
count=$(ls data/runs/arc_*/phase3_episode.json 2>/dev/null | wc -l)
echo "Total transport runs with Phase 3: $count"
