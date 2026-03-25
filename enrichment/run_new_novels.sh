#!/bin/bash
# Run transport pipeline for both panels on all 10 new novels.
# Run sequentially to avoid API rate limits.
set -e

NOVELS=(
    middlemarch
    david_copperfield
    daniel_deronda
    miss_marjoribanks
    hester
    no_name
    new_grub_street
    odd_women
)
# hard_times and cranford already launched separately

for novel in "${NOVELS[@]}"; do
    echo "========================================"
    echo "$(date): Starting $novel v01_baseline"
    echo "========================================"
    uv run python -m enrichment.run_novel \
        --novel "$novel" --condition transport \
        --panel v01_baseline --prompt-version 2

    echo "========================================"
    echo "$(date): Starting $novel v19_all_swapped"
    echo "========================================"
    uv run python -m enrichment.run_novel \
        --novel "$novel" --condition transport \
        --panel v19_all_swapped --prompt-version 2
done

echo "========================================"
echo "$(date): All done"
echo "========================================"
