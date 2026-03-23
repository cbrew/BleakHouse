#!/usr/bin/env bash
# Quick progress report for cross-novel runs.
# Usage: bash scripts/progress.sh

set -euo pipefail
cd /Users/brewc/PycharmProjects/BleakHouse

echo "=== Cross-Novel Run Progress ($(date +%H:%M:%S)) ==="
echo ""

total=0
done=0
printf "%-6s %4s %4s %4s\n" "" "trn" "ext" "hia"
for novel in omf motf nas pti; do
    row="$novel"
    for cond in trn ext hia; do
        n=$(find data/runs -maxdepth 2 -name "phase3_episode.json" -path "*/${novel}_${cond}_*/*" 2>/dev/null | wc -l | tr -d ' ')
        total=$((total + 20))
        done=$((done + n))
        if [ "$n" -eq 20 ]; then
            row=$(printf "%s %4s" "$row" "done")
        else
            row=$(printf "%s %4s" "$row" "${n}/20")
        fi
    done
    echo "$row"
done

remaining=$((total - done))
echo ""
echo "Total: $done/$total complete, $remaining remaining"

# Active runs
active=$(ps aux | grep "enrichment.run --name" | grep -v grep | grep python3 | awk '{for(i=1;i<=NF;i++) if($i=="--name") print $(i+1)}')
if [ -n "$active" ]; then
    echo ""
    echo "Active:"
    echo "$active" | sed 's/^/  /'
    count=$(echo "$active" | wc -l | tr -d ' ')
    if [ "$remaining" -gt 0 ] && [ "$count" -gt 0 ]; then
        mins=$(( remaining * 10 / count ))
        hours=$(( mins / 60 ))
        mins_rem=$(( mins % 60 ))
        echo ""
        echo "ETA: ~${hours}h${mins_rem}m (assuming ~10min/run, $count concurrent)"
    fi
else
    echo ""
    if [ "$remaining" -gt 0 ]; then
        echo "WARNING: No active runs but $remaining remaining — script may have crashed"
    else
        echo "All runs complete!"
    fi
fi
