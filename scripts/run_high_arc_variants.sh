#!/usr/bin/env bash
# Run all 20 panels with doubled character arc demands.
# Demonstrates manipulability: changing arc constraints produces
# measurably different passage selections and scripts.
#
# Arc demands: Richard 6→12, Lady Dedlock 5→10, Jo 4→8
# Everything else identical to the transport baseline for each panel.

set -euo pipefail

RUN="uv run python -m enrichment.run"
ARC_OVERRIDES=(
  --arc-demand "Richard's deterioration=12"
  --arc-demand "Lady Dedlock's secret=10"
  --arc-demand "Jo's suffering=8"
)

echo "=== High-Arc Transport Condition (20 panels) ==="
echo "Arc demands doubled: Richard 12, Dedlock 10, Jo 8"
echo ""

echo "[1/20] arc_v01_baseline"
$RUN --name arc_v01_baseline "${ARC_OVERRIDES[@]}"

echo "[2/20] arc_v10_conservative"
$RUN --name arc_v10_conservative \
  --replace-expert "James Blackstone=sir_edmund" \
  "${ARC_OVERRIDES[@]}"

echo "[3/20] arc_v11_marxist"
$RUN --name arc_v11_marxist \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[4/20] arc_v12_radical_panel"
$RUN --name arc_v12_radical_panel \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[5/20] arc_v14_trevelyan_for_woodcourt"
$RUN --name arc_v14_trevelyan_for_woodcourt \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[6/20] arc_v15_trevelyan_for_hartley"
$RUN --name arc_v15_trevelyan_for_hartley \
  --replace-expert "Eleanor Hartley=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[7/20] arc_v16_trevelyan_for_blackstone"
$RUN --name arc_v16_trevelyan_for_blackstone \
  --replace-expert "James Blackstone=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[8/20] arc_v17_trevelyan_edmund"
$RUN --name arc_v17_trevelyan_edmund \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[9/20] arc_v18_trevelyan_rosen"
$RUN --name arc_v18_trevelyan_rosen \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[10/20] arc_v19_all_swapped"
$RUN --name arc_v19_all_swapped \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[11/20] arc_v21_hartley_blackstone_edmund"
$RUN --name arc_v21_hartley_blackstone_edmund \
  --replace-expert "Caroline Woodcourt=sir_edmund" \
  "${ARC_OVERRIDES[@]}"

echo "[12/20] arc_v22_hartley_blackstone_rosen"
$RUN --name arc_v22_hartley_blackstone_rosen \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[13/20] arc_v23_hartley_woodcourt_rosen"
$RUN --name arc_v23_hartley_woodcourt_rosen \
  --replace-expert "James Blackstone=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[14/20] arc_v24_hartley_edmund_rosen"
$RUN --name arc_v24_hartley_edmund_rosen \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[15/20] arc_v25_hartley_rosen_trevelyan"
$RUN --name arc_v25_hartley_rosen_trevelyan \
  --replace-expert "James Blackstone=dr_rosen" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[16/20] arc_v26_blackstone_woodcourt_edmund"
$RUN --name arc_v26_blackstone_woodcourt_edmund \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  "${ARC_OVERRIDES[@]}"

echo "[17/20] arc_v27_blackstone_edmund_rosen"
$RUN --name arc_v27_blackstone_edmund_rosen \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${ARC_OVERRIDES[@]}"

echo "[18/20] arc_v28_blackstone_edmund_trevelyan"
$RUN --name arc_v28_blackstone_edmund_trevelyan \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[19/20] arc_v29_blackstone_rosen_trevelyan"
$RUN --name arc_v29_blackstone_rosen_trevelyan \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo "[20/20] arc_v30_woodcourt_edmund_trevelyan"
$RUN --name arc_v30_woodcourt_edmund_trevelyan \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "James Blackstone=trevelyan" \
  "${ARC_OVERRIDES[@]}"

echo ""
echo "=== All 20 high-arc panels complete ==="
