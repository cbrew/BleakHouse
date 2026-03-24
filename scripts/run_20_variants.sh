#!/usr/bin/env bash
# Run all 20 experimental variants through Phase 0→1→2 (no script generation).
# Uses the new architecture: Phase 0 (LLM segment design) → Phase 1 (passage selection)
# → Phase 2 (segment assignment).
#
# Expert names use the new naming convention (first name, last name, no titles).
# Preset keys: sir_edmund, dr_rosen, trevelyan (was stephen_fry).

set -euo pipefail

RUN="uv run python -m enrichment.run --novel bleak_house --phase 2"

echo "=== Round 1: Parameter Tuning (V1–V10) ==="

echo "[V1] baseline"
$RUN --name v01_baseline

echo "[V2] more_jo — Jo arc demand 4→8"
$RUN --name v02_more_jo \
  --arc-demand "Jo's suffering=8"

echo "[V3] strict — cluster_lambda 5→20"
$RUN --name v03_strict \
  --cluster-lambda 20

echo "[V4] craft_focus — per_expert_min 8→12"
$RUN --name v04_craft_focus \
  --per-expert-min 12

echo "[V5] craft_v2 — Hartley demands boosted"
$RUN --name v05_craft_v2 \
  --expert-demand "Eleanor Hartley:prov_narrative_technique=4" \
  --expert-demand "Eleanor Hartley:prov_thematic_depth=3"

echo "[V6] quality — weak_cost 3→15"
$RUN --name v06_quality \
  --weak-cost 15

echo "[V7] skip_dedlock — Dedlock arc zeroed"
$RUN --name v07_skip_dedlock \
  --arc-demand "Lady Dedlock's secret=0"

echo "[V8] tight_budget — total_budget 60→25"
$RUN --name v08_tight_budget \
  --total-budget 25

echo "[V9] diverse — cluster_lambda 5→30"
$RUN --name v09_diverse \
  --cluster-lambda 30

echo "[V10] conservative — Blackstone→Edmund Leigh"
$RUN --name v10_conservative \
  --replace-expert "James Blackstone=sir_edmund"

echo ""
echo "=== Round 2: Expert Swaps (V11–V14) ==="

echo "[V11] marxist — Hartley→Rosen"
$RUN --name v11_marxist \
  --replace-expert "Eleanor Hartley=dr_rosen"

echo "[V12] radical_panel — Blackstone→Edmund, Hartley→Rosen"
$RUN --name v12_radical_panel \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Eleanor Hartley=dr_rosen"

echo "[V13] rosen_jo — Hartley→Rosen + Jo=8"
$RUN --name v13_rosen_jo \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  --arc-demand "Jo's suffering=8"

echo "[V14] trevelyan_for_woodcourt — Woodcourt→Trevelyan"
$RUN --name v14_trevelyan_for_woodcourt \
  --replace-expert "Caroline Woodcourt=trevelyan"

echo ""
echo "=== Round 3: Trevelyan Integration (V15–V20) ==="

echo "[V15] trevelyan_for_hartley — Hartley→Trevelyan"
$RUN --name v15_trevelyan_for_hartley \
  --replace-expert "Eleanor Hartley=trevelyan"

echo "[V16] trevelyan_for_blackstone — Blackstone→Trevelyan"
$RUN --name v16_trevelyan_for_blackstone \
  --replace-expert "James Blackstone=trevelyan"

echo "[V17] trevelyan_edmund — Blackstone→Edmund, Woodcourt→Trevelyan"
$RUN --name v17_trevelyan_edmund \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=trevelyan"

echo "[V18] trevelyan_rosen — Hartley→Trevelyan, Blackstone→Rosen"
$RUN --name v18_trevelyan_rosen \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=dr_rosen"

echo "[V19] all_swapped — Hartley→Trevelyan, Blackstone→Edmund, Woodcourt→Rosen"
$RUN --name v19_all_swapped \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen"

echo "[V20] trevelyan_jo — Woodcourt→Trevelyan + Jo=8"
$RUN --name v20_trevelyan_jo \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  --arc-demand "Jo's suffering=8"

echo ""
echo "=== All 20 variants complete ==="
