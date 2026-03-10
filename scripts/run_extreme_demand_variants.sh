#!/usr/bin/env bash
# Run all 20 panels with amplified expert demand profiles.
# Each expert's demands are doubled, making them more extreme
# versions of themselves — Blackstone demands 4 social_critique
# instead of 2, Rosen demands 6, Trevelyan demands 6 humor, etc.
#
# Demonstrates manipulability: adjusting demand vectors (not prompts)
# produces measurably different passage selections and scripts.
#
# Amplified demands (original → extreme):
#   Hartley:    narrative_technique 2→4, character_development 2→4, thematic_depth 1→2
#   Blackstone: social_critique 2→4, atmosphere_setting 2→4, thematic_depth 1→2
#   Woodcourt:  humor_entertainment 2→4, character_development 1→2, atmosphere_setting 1→2
#   Edmund:     character_development 3→6, thematic_depth 2→4, narrative_technique 1→2
#   Rosen:      social_critique 3→6, atmosphere_setting 2→4, character_development 1→2
#   Trevelyan:  humor_entertainment 3→6, atmosphere_setting 2→4, narrative_technique 2→4
#
# Also increases total_budget 60→90 to accommodate higher demand.

set -euo pipefail

RUN="uv run python -m enrichment.run"

# Demand overrides for default experts (applied when present in panel)
HARTLEY_DEMANDS=(
  --expert-demand "Eleanor Hartley:prov_narrative_technique=4"
  --expert-demand "Eleanor Hartley:prov_character_development=4"
  --expert-demand "Eleanor Hartley:prov_thematic_depth=2"
)
BLACKSTONE_DEMANDS=(
  --expert-demand "James Blackstone:prov_social_critique=4"
  --expert-demand "James Blackstone:prov_atmosphere_setting=4"
  --expert-demand "James Blackstone:prov_thematic_depth=2"
)
WOODCOURT_DEMANDS=(
  --expert-demand "Caroline Woodcourt:prov_humor_entertainment=4"
  --expert-demand "Caroline Woodcourt:prov_character_development=2"
  --expert-demand "Caroline Woodcourt:prov_atmosphere_setting=2"
)
# Alternative experts get their demands doubled AFTER replacement
EDMUND_DEMANDS=(
  --expert-demand "Edmund Leigh:prov_character_development=6"
  --expert-demand "Edmund Leigh:prov_thematic_depth=4"
  --expert-demand "Edmund Leigh:prov_narrative_technique=2"
)
ROSEN_DEMANDS=(
  --expert-demand "Daniel Rosen:prov_social_critique=6"
  --expert-demand "Daniel Rosen:prov_atmosphere_setting=4"
  --expert-demand "Daniel Rosen:prov_character_development=2"
)
TREVELYAN_DEMANDS=(
  --expert-demand "Oliver Trevelyan:prov_humor_entertainment=6"
  --expert-demand "Oliver Trevelyan:prov_atmosphere_setting=4"
  --expert-demand "Oliver Trevelyan:prov_narrative_technique=4"
)

BUDGET="--total-budget 90"

echo "=== Extreme Demand Transport Condition (20 panels) ==="
echo "All expert demands doubled, budget 60→90"
echo ""

# Panels: Hartley, Blackstone, Woodcourt
echo "[1/20] ext_v01_baseline"
$RUN --name ext_v01_baseline $BUDGET \
  "${HARTLEY_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Hartley, Edmund, Woodcourt
echo "[2/20] ext_v10_conservative"
$RUN --name ext_v10_conservative $BUDGET \
  --replace-expert "James Blackstone=sir_edmund" \
  "${HARTLEY_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Rosen, Blackstone, Woodcourt
echo "[3/20] ext_v11_marxist"
$RUN --name ext_v11_marxist $BUDGET \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  "${ROSEN_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Rosen, Edmund, Woodcourt
echo "[4/20] ext_v12_radical_panel"
$RUN --name ext_v12_radical_panel $BUDGET \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  "${ROSEN_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Hartley, Blackstone, Trevelyan
echo "[5/20] ext_v14_trevelyan_for_woodcourt"
$RUN --name ext_v14_trevelyan_for_woodcourt $BUDGET \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${HARTLEY_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}"

# Panels: Trevelyan, Blackstone, Woodcourt
echo "[6/20] ext_v15_trevelyan_for_hartley"
$RUN --name ext_v15_trevelyan_for_hartley $BUDGET \
  --replace-expert "Eleanor Hartley=trevelyan" \
  "${TREVELYAN_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Hartley, Trevelyan, Woodcourt
echo "[7/20] ext_v16_trevelyan_for_blackstone"
$RUN --name ext_v16_trevelyan_for_blackstone $BUDGET \
  --replace-expert "James Blackstone=trevelyan" \
  "${HARTLEY_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Hartley, Edmund, Trevelyan
echo "[8/20] ext_v17_trevelyan_edmund"
$RUN --name ext_v17_trevelyan_edmund $BUDGET \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${HARTLEY_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}"

# Panels: Trevelyan, Rosen, Woodcourt
echo "[9/20] ext_v18_trevelyan_rosen"
$RUN --name ext_v18_trevelyan_rosen $BUDGET \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=dr_rosen" \
  "${TREVELYAN_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Trevelyan, Edmund, Rosen
echo "[10/20] ext_v19_all_swapped"
$RUN --name ext_v19_all_swapped $BUDGET \
  --replace-expert "Eleanor Hartley=trevelyan" \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${TREVELYAN_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}"

# Panels: Hartley, Blackstone, Edmund
echo "[11/20] ext_v21_hartley_blackstone_edmund"
$RUN --name ext_v21_hartley_blackstone_edmund $BUDGET \
  --replace-expert "Caroline Woodcourt=sir_edmund" \
  "${HARTLEY_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}"

# Panels: Hartley, Blackstone, Rosen
echo "[12/20] ext_v22_hartley_blackstone_rosen"
$RUN --name ext_v22_hartley_blackstone_rosen $BUDGET \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${HARTLEY_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}"

# Panels: Hartley, Rosen, Woodcourt
echo "[13/20] ext_v23_hartley_woodcourt_rosen"
$RUN --name ext_v23_hartley_woodcourt_rosen $BUDGET \
  --replace-expert "James Blackstone=dr_rosen" \
  "${HARTLEY_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Hartley, Edmund, Rosen
echo "[14/20] ext_v24_hartley_edmund_rosen"
$RUN --name ext_v24_hartley_edmund_rosen $BUDGET \
  --replace-expert "James Blackstone=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${HARTLEY_DEMANDS[@]}" "${EDMUND_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}"

# Panels: Hartley, Rosen, Trevelyan
echo "[15/20] ext_v25_hartley_rosen_trevelyan"
$RUN --name ext_v25_hartley_rosen_trevelyan $BUDGET \
  --replace-expert "James Blackstone=dr_rosen" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${HARTLEY_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}"

# Panels: Edmund, Blackstone, Woodcourt
echo "[16/20] ext_v26_blackstone_woodcourt_edmund"
$RUN --name ext_v26_blackstone_woodcourt_edmund $BUDGET \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  "${EDMUND_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

# Panels: Edmund, Blackstone, Rosen
echo "[17/20] ext_v27_blackstone_edmund_rosen"
$RUN --name ext_v27_blackstone_edmund_rosen $BUDGET \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "Caroline Woodcourt=dr_rosen" \
  "${EDMUND_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${ROSEN_DEMANDS[@]}"

# Panels: Edmund, Blackstone, Trevelyan
echo "[18/20] ext_v28_blackstone_edmund_trevelyan"
$RUN --name ext_v28_blackstone_edmund_trevelyan $BUDGET \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${EDMUND_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}"

# Panels: Rosen, Blackstone, Trevelyan
echo "[19/20] ext_v29_blackstone_rosen_trevelyan"
$RUN --name ext_v29_blackstone_rosen_trevelyan $BUDGET \
  --replace-expert "Eleanor Hartley=dr_rosen" \
  --replace-expert "Caroline Woodcourt=trevelyan" \
  "${ROSEN_DEMANDS[@]}" "${BLACKSTONE_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}"

# Panels: Edmund, Trevelyan, Woodcourt
echo "[20/20] ext_v30_woodcourt_edmund_trevelyan"
$RUN --name ext_v30_woodcourt_edmund_trevelyan $BUDGET \
  --replace-expert "Eleanor Hartley=sir_edmund" \
  --replace-expert "James Blackstone=trevelyan" \
  "${EDMUND_DEMANDS[@]}" "${TREVELYAN_DEMANDS[@]}" "${WOODCOURT_DEMANDS[@]}"

echo ""
echo "=== All 20 extreme-demand panels complete ==="
