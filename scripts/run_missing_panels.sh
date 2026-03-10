#!/bin/bash
# Run 10 missing panel combinations through both transport and embedding pipelines.
# 20 runs total (10 transport + 10 embedding), default parameters otherwise.
#
# Usage: bash scripts/run_missing_panels.sh
#   Or embedding only:  SKIP_TRANSPORT=1 bash scripts/run_missing_panels.sh
#   Or transport only:  SKIP_EMBEDDING=1 bash scripts/run_missing_panels.sh

set -e

run_transport() {
    local name="$1"
    shift
    echo ""
    echo "=== TRANSPORT $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.run --name "$name" "$@"
    echo "=== TRANSPORT $name complete === ($(date +%H:%M:%S))"
}

run_embedding() {
    local name="$1"
    shift
    echo ""
    echo "=== EMBEDDING $name === ($(date +%H:%M:%S))"
    uv run python -m enrichment.embedding_run --name "$name" "$@"
    echo "=== EMBEDDING $name complete === ($(date +%H:%M:%S))"
}

run_pair() {
    local num="$1"
    shift
    if [ -z "$SKIP_TRANSPORT" ]; then
        run_transport "v${num}_$LABEL" "$@"
    fi
    if [ -z "$SKIP_EMBEDDING" ]; then
        run_embedding "emb_v${num}_$LABEL" "$@"
    fi
}

# 1. Hartley, Blackstone, Edmund Leigh
LABEL="hartley_blackstone_edmund"
run_pair 21 \
    --replace-expert "Caroline Woodcourt=sir_edmund"

# 2. Hartley, Blackstone, Rosen
LABEL="hartley_blackstone_rosen"
run_pair 22 \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 3. Hartley, Woodcourt, Rosen
LABEL="hartley_woodcourt_rosen"
run_pair 23 \
    --replace-expert "James Blackstone=dr_rosen"

# 4. Hartley, Edmund, Rosen
LABEL="hartley_edmund_rosen"
run_pair 24 \
    --replace-expert "James Blackstone=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 5. Hartley, Rosen, Trevelyan
LABEL="hartley_rosen_trevelyan"
run_pair 25 \
    --replace-expert "James Blackstone=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 6. Blackstone, Woodcourt, Edmund
LABEL="blackstone_woodcourt_edmund"
run_pair 26 \
    --replace-expert "Eleanor Hartley=sir_edmund"

# 7. Blackstone, Edmund, Rosen
LABEL="blackstone_edmund_rosen"
run_pair 27 \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=dr_rosen"

# 8. Blackstone, Edmund, Trevelyan
LABEL="blackstone_edmund_trevelyan"
run_pair 28 \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 9. Blackstone, Rosen, Trevelyan
LABEL="blackstone_rosen_trevelyan"
run_pair 29 \
    --replace-expert "Eleanor Hartley=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"

# 10. Woodcourt, Edmund, Trevelyan
LABEL="woodcourt_edmund_trevelyan"
run_pair 30 \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "James Blackstone=trevelyan"

echo ""
echo "================================================"
echo "All 10 missing panels complete ($(date +%H:%M:%S))"
echo "Outputs in data/runs/v2[1-9]_* and data/runs/emb_v2[1-9]_*"
