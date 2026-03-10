#!/bin/bash
# Run all 20 panel combinations through the plain RAG pipeline.
# Each takes ~8-10 min (Phase 0 + vector retrieval + Phase 3).
#
# Usage: bash scripts/run_plain_rag_variants.sh
#   Or just through Phase 2 (no script generation, ~1 min each):
#     PHASE=2 bash scripts/run_plain_rag_variants.sh

set -e

PHASE=${PHASE:-3}
echo "Running plain RAG variants through Phase $PHASE"
echo "================================================"

run_variant() {
    local name="$1"
    shift
    echo ""
    echo "=== $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.plain_rag_run --name "$name" --phase "$PHASE" "$@"
    echo "=== $name complete === ($(date +%H:%M:%S))"
}

# --- Original 10 panels (matched to transport v01-v19) ---

# 1. Hartley, Blackstone, Woodcourt (default)
run_variant rag_v01_baseline

# 2. Hartley, Edmund, Woodcourt
run_variant rag_v10_conservative \
    --replace-expert "James Blackstone=sir_edmund"

# 3. Rosen, Blackstone, Woodcourt
run_variant rag_v11_marxist \
    --replace-expert "Eleanor Hartley=dr_rosen"

# 4. Rosen, Edmund, Woodcourt
run_variant rag_v12_radical_panel \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "James Blackstone=sir_edmund"

# 5. Hartley, Blackstone, Trevelyan
run_variant rag_v14_trevelyan_for_woodcourt \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 6. Trevelyan, Blackstone, Woodcourt
run_variant rag_v15_trevelyan_for_hartley \
    --replace-expert "Eleanor Hartley=trevelyan"

# 7. Hartley, Trevelyan, Woodcourt
run_variant rag_v16_trevelyan_for_blackstone \
    --replace-expert "James Blackstone=trevelyan"

# 8. Hartley, Edmund, Trevelyan
run_variant rag_v17_trevelyan_edmund \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 9. Trevelyan, Rosen, Woodcourt
run_variant rag_v18_trevelyan_rosen \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=dr_rosen"

# 10. Trevelyan, Edmund, Rosen
run_variant rag_v19_all_swapped \
    --replace-expert "Eleanor Hartley=trevelyan" \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# --- New 10 panels (matched to transport v21-v30) ---

# 11. Hartley, Blackstone, Edmund
run_variant rag_v21_hartley_blackstone_edmund \
    --replace-expert "Caroline Woodcourt=sir_edmund"

# 12. Hartley, Blackstone, Rosen
run_variant rag_v22_hartley_blackstone_rosen \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 13. Hartley, Woodcourt, Rosen
run_variant rag_v23_hartley_woodcourt_rosen \
    --replace-expert "James Blackstone=dr_rosen"

# 14. Hartley, Edmund, Rosen
run_variant rag_v24_hartley_edmund_rosen \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 15. Hartley, Rosen, Trevelyan
run_variant rag_v25_hartley_rosen_trevelyan \
    --replace-expert "James Blackstone=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 16. Blackstone, Woodcourt, Edmund
run_variant rag_v26_blackstone_woodcourt_edmund \
    --replace-expert "Eleanor Hartley=sir_edmund"

# 17. Blackstone, Edmund, Rosen
run_variant rag_v27_blackstone_edmund_rosen \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 18. Blackstone, Edmund, Trevelyan
run_variant rag_v28_blackstone_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 19. Blackstone, Rosen, Trevelyan
run_variant rag_v29_blackstone_rosen_trevelyan \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 20. Woodcourt, Edmund, Trevelyan
run_variant rag_v30_woodcourt_edmund_trevelyan \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "James Blackstone=trevelyan"

echo ""
echo "================================================"
echo "All 20 plain RAG variants complete."
echo "Outputs in data/runs/rag_v*/"
