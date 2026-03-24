
#!/usr/bin/env bash
# Run all cross-novel conditions: baseline transport, peaked demand, high-arc.
# 4 novels × 3 conditions × 20 panels.
#
# Concurrency: MAX_CONCURRENT runs at a time per batch.
# Each run is serial internally (Phase 0→1→2→3).
#
# All arguments are passed as proper arrays — no eval, no quoting tricks.
set -euo pipefail

cd /Users/brewc/PycharmProjects/BleakHouse

MAX_CONCURRENT=2

ALL_PANELS=(
  v01_baseline
  v10_conservative
  v11_rosen_blackstone_woodcourt
  v12_radical_panel
  v14_trevelyan_for_woodcourt
  v15_trevelyan_for_hartley
  v16_trevelyan_for_blackstone
  v17_trevelyan_edmund
  v18_trevelyan_rosen
  v19_all_swapped
  v21_hartley_blackstone_edmund
  v22_hartley_blackstone_rosen
  v23_hartley_woodcourt_rosen
  v24_hartley_edmund_rosen
  v25_hartley_rosen_trevelyan
  v26_blackstone_woodcourt_edmund
  v27_blackstone_edmund_rosen
  v28_blackstone_edmund_trevelyan
  v29_blackstone_rosen_trevelyan
  v30_woodcourt_edmund_trevelyan
)

# ---- Panel replacement flags as functions ----
# Returns the --replace-expert args for a panel via a nameref array.
get_panel_args() {
    local panel="$1"
    local -n _out="$2"
    _out=()
    case "$panel" in
        v01_baseline) ;;
        v10_conservative)
            _out+=(--replace-expert "James Blackstone=sir_edmund") ;;
        v11_rosen_blackstone_woodcourt)
            _out+=(--replace-expert "Eleanor Hartley=dr_rosen") ;;
        v12_radical_panel)
            _out+=(--replace-expert "Eleanor Hartley=dr_rosen" --replace-expert "James Blackstone=sir_edmund") ;;
        v14_trevelyan_for_woodcourt)
            _out+=(--replace-expert "Caroline Woodcourt=trevelyan") ;;
        v15_trevelyan_for_hartley)
            _out+=(--replace-expert "Eleanor Hartley=trevelyan") ;;
        v16_trevelyan_for_blackstone)
            _out+=(--replace-expert "James Blackstone=trevelyan") ;;
        v17_trevelyan_edmund)
            _out+=(--replace-expert "James Blackstone=sir_edmund" --replace-expert "Caroline Woodcourt=trevelyan") ;;
        v18_trevelyan_rosen)
            _out+=(--replace-expert "Eleanor Hartley=trevelyan" --replace-expert "James Blackstone=dr_rosen") ;;
        v19_all_swapped)
            _out+=(--replace-expert "Eleanor Hartley=trevelyan" --replace-expert "James Blackstone=sir_edmund" --replace-expert "Caroline Woodcourt=dr_rosen") ;;
        v21_hartley_blackstone_edmund)
            _out+=(--replace-expert "Caroline Woodcourt=sir_edmund") ;;
        v22_hartley_blackstone_rosen)
            _out+=(--replace-expert "Caroline Woodcourt=dr_rosen") ;;
        v23_hartley_woodcourt_rosen)
            _out+=(--replace-expert "James Blackstone=dr_rosen") ;;
        v24_hartley_edmund_rosen)
            _out+=(--replace-expert "James Blackstone=sir_edmund" --replace-expert "Caroline Woodcourt=dr_rosen") ;;
        v25_hartley_rosen_trevelyan)
            _out+=(--replace-expert "James Blackstone=dr_rosen" --replace-expert "Caroline Woodcourt=trevelyan") ;;
        v26_blackstone_woodcourt_edmund)
            _out+=(--replace-expert "Eleanor Hartley=sir_edmund") ;;
        v27_blackstone_edmund_rosen)
            _out+=(--replace-expert "Eleanor Hartley=sir_edmund" --replace-expert "Caroline Woodcourt=dr_rosen") ;;
        v28_blackstone_edmund_trevelyan)
            _out+=(--replace-expert "Eleanor Hartley=sir_edmund" --replace-expert "Caroline Woodcourt=trevelyan") ;;
        v29_blackstone_rosen_trevelyan)
            _out+=(--replace-expert "Eleanor Hartley=dr_rosen" --replace-expert "Caroline Woodcourt=trevelyan") ;;
        v30_woodcourt_edmund_trevelyan)
            _out+=(--replace-expert "Eleanor Hartley=sir_edmund" --replace-expert "James Blackstone=trevelyan") ;;
        *) echo "Unknown panel: $panel" >&2; exit 1 ;;
    esac
}

# Peaked expert demand args — proper array, no eval needed
PEAKED_ARGS=(
    --expert-demand "Eleanor Hartley:prov_narrative_technique=6"
    --expert-demand "Eleanor Hartley:prov_character_development=1"
    --expert-demand "Eleanor Hartley:prov_thematic_depth=0"
    --expert-demand "James Blackstone:prov_social_critique=6"
    --expert-demand "James Blackstone:prov_atmosphere_setting=1"
    --expert-demand "James Blackstone:prov_thematic_depth=0"
    --expert-demand "Caroline Woodcourt:prov_humor_entertainment=6"
    --expert-demand "Caroline Woodcourt:prov_character_development=0"
    --expert-demand "Caroline Woodcourt:prov_atmosphere_setting=1"
    --expert-demand "Edmund Leigh:prov_character_development=7"
    --expert-demand "Edmund Leigh:prov_thematic_depth=1"
    --expert-demand "Edmund Leigh:prov_narrative_technique=0"
    --expert-demand "Daniel Rosen:prov_social_critique=8"
    --expert-demand "Daniel Rosen:prov_atmosphere_setting=0"
    --expert-demand "Daniel Rosen:prov_character_development=0"
    --expert-demand "Oliver Trevelyan:prov_humor_entertainment=8"
    --expert-demand "Oliver Trevelyan:prov_atmosphere_setting=0"
    --expert-demand "Oliver Trevelyan:prov_narrative_technique=0"
)

# High-arc overrides per novel — returned via function
get_hia_args() {
    local novel="$1"
    local -n _out="$2"
    _out=()
    case "$novel" in
        our_mutual_friend)
            _out+=(--arc-demand "Bella's transformation=12"
                   --arc-demand "Harmon's disguise=10"
                   --arc-demand "The Dust Heaps=8") ;;
        mill_on_the_floss)
            _out+=(--arc-demand "Maggie's intellectual hunger=12"
                   --arc-demand "Tom and Maggie's rift=10"
                   --arc-demand "The Tulliver ruin=8") ;;
        north_and_south)
            _out+=(--arc-demand "Margaret's transformation=12"
                   --arc-demand "Thornton and the strike=10"
                   --arc-demand "Higgins and class solidarity=8") ;;
        passage_to_india)
            _out+=(--arc-demand "Aziz's humiliation and trial=12"
                   --arc-demand "The Marabar Caves=10"
                   --arc-demand "Fielding's disillusion=8") ;;
        *) echo "Unknown novel: $novel" >&2; exit 1 ;;
    esac
}

# ---- Concurrency limiter ----
running_pids=()

wait_for_slot() {
    while true; do
        local new_pids=()
        for pid in "${running_pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                new_pids+=("$pid")
            fi
        done
        running_pids=("${new_pids[@]}")
        if [ ${#running_pids[@]} -lt $MAX_CONCURRENT ]; then
            return
        fi
        sleep 5
    done
}

wait_all() {
    for pid in "${running_pids[@]}"; do
        wait "$pid" || echo "WARNING: PID $pid exited with error"
    done
    running_pids=()
}

# Launch a run in the background.
# Usage: launch_run <novel_key> <run_name> <extra_args...>
launch_run() {
    local novel_key="$1"
    local run_name="$2"
    shift 2

    wait_for_slot
    echo "  [$(date +%H:%M:%S)] Starting $run_name"
    BLEAKHOUSE_NOVEL="$novel_key" \
        uv run python -m enrichment.run_pipeline --pipeline transport --novel "$novel_key" --name "$run_name" "$@" \
        > /dev/null 2>&1 &
    running_pids+=($!)
}

# ---- Main ----
total=0
skipped=0

for novel_key in our_mutual_friend mill_on_the_floss north_and_south passage_to_india; do
    case "$novel_key" in
        our_mutual_friend) novel_prefix="omf" ;;
        mill_on_the_floss) novel_prefix="motf" ;;
        north_and_south)   novel_prefix="nas" ;;
        passage_to_india)  novel_prefix="pti" ;;
    esac

    echo ""
    echo "========================================"
    echo "Novel: $novel_key ($novel_prefix)"
    echo "========================================"

    # --- CONDITION 1: Baseline transport (fill gaps) ---
    echo ""
    echo "--- Baseline transport (trn) ---"
    for panel in "${ALL_PANELS[@]}"; do
        run_name="${novel_prefix}_trn_${panel}"
        if [ -f "data/runs/${run_name}/phase3_episode.json" ]; then
            skipped=$((skipped + 1))
            continue
        fi
        total=$((total + 1))
        local_panel_args=()
        get_panel_args "$panel" local_panel_args
        launch_run "$novel_key" "$run_name" "${local_panel_args[@]}"
    done
    wait_all
    echo "  Baseline transport done for $novel_key"

    # --- CONDITION 2: Peaked expert demand (ext) ---
    echo ""
    echo "--- Peaked demand (ext) ---"
    for panel in "${ALL_PANELS[@]}"; do
        run_name="${novel_prefix}_ext_${panel}"
        if [ -f "data/runs/${run_name}/phase3_episode.json" ]; then
            skipped=$((skipped + 1))
            continue
        fi
        total=$((total + 1))
        local_panel_args=()
        get_panel_args "$panel" local_panel_args
        launch_run "$novel_key" "$run_name" "${local_panel_args[@]}" "${PEAKED_ARGS[@]}"
    done
    wait_all
    echo "  Peaked demand done for $novel_key"

    # --- CONDITION 3: High-arc demand (hia) ---
    echo ""
    echo "--- High-arc demand (hia) ---"
    local_hia_args=()
    get_hia_args "$novel_key" local_hia_args
    for panel in "${ALL_PANELS[@]}"; do
        run_name="${novel_prefix}_hia_${panel}"
        if [ -f "data/runs/${run_name}/phase3_episode.json" ]; then
            skipped=$((skipped + 1))
            continue
        fi
        total=$((total + 1))
        local_panel_args=()
        get_panel_args "$panel" local_panel_args
        launch_run "$novel_key" "$run_name" "${local_panel_args[@]}" "${local_hia_args[@]}"
    done
    wait_all
    echo "  High-arc demand done for $novel_key"
done

echo ""
echo "========================================"
echo "COMPLETE: $total runs launched, $skipped skipped (already existed)"
echo "========================================"
