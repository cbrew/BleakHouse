#!/bin/bash
# Run transport pipeline for both panels on all 10 new novels.
set -e

NOVELS=(
    hard_times
    cranford
    middlemarch
    david_copperfield
    daniel_deronda
    miss_marjoribanks
    hester
    no_name
    new_grub_street
    odd_women
)

for novel in "${NOVELS[@]}"; do
    for panel in v01_baseline v19_all_swapped; do
        echo "========================================"
        echo "$(date): $novel $panel"
        echo "========================================"
        uv run python -m enrichment.run_novel \
            --novel "$novel" --condition transport \
            --panel "$panel" --prompt-version 2
    done
done

echo "========================================"
echo "$(date): All done"
echo "========================================"
