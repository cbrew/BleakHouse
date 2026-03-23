#!/bin/bash
# Run v2 and v3 prompts across all 19 non-baseline panels × 3 conditions.
# Baseline (v01) already done for both v2 and v3.
# Runs 3 conditions in parallel per panel, then moves to next panel.
set -e

cd /Users/brewc/PycharmProjects/BleakHouse

# Panel definitions: suffix | replace flags
PANELS=(
  "v10_conservative|--replace-expert 'James Blackstone=sir_edmund'"
  "v11_marxist|--replace-expert 'Eleanor Hartley=dr_rosen'"
  "v12_radical_panel|--replace-expert 'Eleanor Hartley=dr_rosen' --replace-expert 'James Blackstone=sir_edmund'"
  "v14_trevelyan_for_woodcourt|--replace-expert 'Caroline Woodcourt=trevelyan'"
  "v15_trevelyan_for_hartley|--replace-expert 'Eleanor Hartley=trevelyan'"
  "v16_trevelyan_for_blackstone|--replace-expert 'James Blackstone=trevelyan'"
  "v17_trevelyan_edmund|--replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=trevelyan'"
  "v18_trevelyan_rosen|--replace-expert 'Eleanor Hartley=trevelyan' --replace-expert 'James Blackstone=dr_rosen'"
  "v19_all_swapped|--replace-expert 'Eleanor Hartley=trevelyan' --replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
  "v21_hartley_blackstone_edmund|--replace-expert 'Caroline Woodcourt=sir_edmund'"
  "v22_hartley_blackstone_rosen|--replace-expert 'Caroline Woodcourt=dr_rosen'"
  "v23_hartley_woodcourt_rosen|--replace-expert 'James Blackstone=dr_rosen'"
  "v24_hartley_edmund_rosen|--replace-expert 'James Blackstone=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
  "v25_hartley_rosen_trevelyan|--replace-expert 'James Blackstone=dr_rosen' --replace-expert 'Caroline Woodcourt=trevelyan'"
  "v26_blackstone_woodcourt_edmund|--replace-expert 'Eleanor Hartley=sir_edmund'"
  "v27_blackstone_edmund_rosen|--replace-expert 'Eleanor Hartley=sir_edmund' --replace-expert 'Caroline Woodcourt=dr_rosen'"
  "v28_blackstone_edmund_trevelyan|--replace-expert 'Eleanor Hartley=sir_edmund' --replace-expert 'Caroline Woodcourt=trevelyan'"
  "v29_blackstone_rosen_trevelyan|--replace-expert 'Eleanor Hartley=dr_rosen' --replace-expert 'Caroline Woodcourt=trevelyan'"
  "v30_woodcourt_edmund_trevelyan|--replace-expert 'Eleanor Hartley=sir_edmund' --replace-expert 'James Blackstone=trevelyan'"
)

run_panel() {
  local version=$1  # 2 or 3
  local suffix=$2
  local flags=$3
  local prefix="p${version}"

  echo "=== ${prefix}_${suffix} (v${version}) ==="

  # Transport
  eval uv run python -m enrichment.run \
    --name "${prefix}_${suffix}" \
    --prompt-version "${version}" \
    ${flags} \
    2>&1 | tail -5 &
  PID_T=$!

  # Embedding
  eval uv run python -m enrichment.embedding_run \
    --name "${prefix}_emb_${suffix}" \
    --prompt-version "${version}" \
    ${flags} \
    2>&1 | tail -5 &
  PID_E=$!

  # No-passages
  eval uv run python -m enrichment.no_passages_run \
    --name "${prefix}_nop_${suffix}" \
    --prompt-version "${version}" \
    ${flags} \
    2>&1 | tail -5 &
  PID_N=$!

  wait $PID_T $PID_E $PID_N
  echo "  Done: ${prefix}_${suffix} (all 3 conditions)"
}

for panel in "${PANELS[@]}"; do
  IFS='|' read -r suffix flags <<< "$panel"

  # v2
  run_panel 2 "$suffix" "$flags"

  # v3
  run_panel 3 "$suffix" "$flags"
done

echo ""
echo "All runs complete."
