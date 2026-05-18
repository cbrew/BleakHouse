"""Score Tier L pairwise preferences from a Potato annotations TSV.

INPUT (column shape per potato/export/tabular_exporter.py):
  instance_id  user_id  preference.selection  [other schema cols...]

  instance_id          = our pair_id (from blinding_manifest.json)
  user_id              = the Potato login that submitted the annotation
  preference.selection = literal label string the listener clicked:
                         "A", "B", or "tie / no preference"

OUTPUT:
  data/eval/stage2_tier_l_prose/preference_summary.json with
  per_model rolls, pairwise matrix, order_bias, consistency tally,
  rng_seed_used_for_blinding, listener identity.

WHICH TSV PATH TO PASS
----------------------
The Potato listener configured in
`data/eval/stage2_tier_l_prose/potato/config.yaml` writes its
auto-export to:

    data/eval/stage2_tier_l_prose/potato/annotation_output/exports/tsv/annotations.tsv

That file is rewritten after every annotation submit (driven by
`export_annotation_format: tsv` in config.yaml; the `/exports/tsv/`
segment is hard-coded in Potato's user_state_management.py and is
NOT configurable). Pass that path. If config.yaml ever changes
`output_annotation_dir` away from the default `annotation_output/`,
substitute the new value.

Usage:
    uv run python scripts/score_eval_pairings_potato.py \\
        --tsv data/eval/stage2_tier_l_prose/potato/annotation_output/exports/tsv/annotations.tsv
    uv run python scripts/score_eval_pairings_potato.py --tsv … --user alice
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "data" / "eval" / "stage2_tier_l_prose"
MANIFEST_PATH = EVAL_ROOT / "blinding_manifest.json"
SUMMARY_PATH = EVAL_ROOT / "preference_summary.json"

# Must match the `tie_label:` value under annotation_schemes.preference
# in data/eval/stage2_tier_l_prose/potato/config.yaml. If you change one,
# change the other.
TIE_LABEL = "tie / no preference"


def _resolve(choice: str, a_is: str, b_is: str) -> str | None:
    """Map a Potato-emitted label string to the model name that won
    (or 'tie' / None)."""
    c = (choice or "").strip()
    if c == "":
        return None
    if c == TIE_LABEL or c.lower() == "tie":
        return "tie"
    if c == "A":
        return a_is
    if c == "B":
        return b_is
    raise SystemExit(
        f"unrecognised label {choice!r}; expected 'A', 'B', or {TIE_LABEL!r}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--user", default=None,
        help="If set, only score rows where user_id == this value. "
             "Useful when the same TSV has annotations from multiple "
             "logins (single-listener default: auto-pick the only user).",
    )
    ap.add_argument(
        "--tsv", type=Path, required=True,
        help="Path to Potato's auto-export annotations TSV "
             "(<output_annotation_dir>/exports/tsv/annotations.tsv). "
             "See the module docstring.",
    )
    args = ap.parse_args()

    if not MANIFEST_PATH.exists():
        raise SystemExit(
            f"missing {MANIFEST_PATH}. Run scripts/render_eval_pairings.py first."
        )
    args.tsv = args.tsv.resolve()
    if not args.tsv.exists():
        raise SystemExit(
            f"missing {args.tsv}. Run a Potato session first (see "
            f"scripts/start_potato_listener.sh)."
        )

    manifest = json.loads(MANIFEST_PATH.read_text())
    candidates: list[str] = list(manifest["candidates"])
    pairs_by_id: dict[str, dict] = {p["pair_id"]: p for p in manifest["pairs"]}

    # Load TSV. Each row is one user_id × instance_id annotation.
    rows: list[dict[str, str]] = []
    with args.tsv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
    if not rows:
        raise SystemExit(f"{args.tsv} is empty")

    # Filter / pick user.
    user_ids = sorted({r.get("user_id", "") for r in rows if r.get("user_id")})
    if args.user is not None:
        chosen = args.user
        if chosen not in user_ids:
            raise SystemExit(
                f"--user {chosen!r} not in TSV (saw {user_ids})"
            )
    elif len(user_ids) == 1:
        chosen = user_ids[0]
    elif len(user_ids) == 0:
        raise SystemExit("TSV has no user_id values")
    else:
        raise SystemExit(
            f"TSV has multiple users ({user_ids}); pass --user explicitly"
        )
    rows = [r for r in rows if r.get("user_id") == chosen]

    # Build pair_id -> raw choice for the chosen user.
    choice_by_pair: dict[str, str] = {}
    for r in rows:
        pid = r.get("instance_id", "")
        if pid in pairs_by_id:
            choice_by_pair[pid] = r.get("preference.selection", "")

    # --- Score (same logic as scripts/score_eval_pairings.py) ---
    per_model: dict[str, dict] = {
        c: {"wins": 0, "losses": 0, "ties": 0, "missing": 0, "trials": 0}
        for c in candidates
    }
    pairwise_wins: dict[tuple[str, str], int] = defaultdict(int)
    pairwise_ties: dict[frozenset[str], int] = defaultdict(int)
    side_pref = {"A": 0, "B": 0, "tie": 0, "missing": 0}
    consistency_groups: dict[tuple[str, str, int], list[str | None]] = defaultdict(list)

    for pair_id, p in pairs_by_id.items():
        a_is, b_is = p["a_is"], p["b_is"]
        preferred = _resolve(choice_by_pair.get(pair_id, ""), a_is, b_is)
        if preferred is None:
            side_pref["missing"] += 1
        elif preferred == "tie":
            side_pref["tie"] += 1
        else:
            side_pref["A" if preferred == a_is else "B"] += 1

        per_model[a_is]["trials"] += 1
        per_model[b_is]["trials"] += 1
        if preferred is None:
            per_model[a_is]["missing"] += 1
            per_model[b_is]["missing"] += 1
        elif preferred == "tie":
            per_model[a_is]["ties"] += 1
            per_model[b_is]["ties"] += 1
            pairwise_ties[frozenset((a_is, b_is))] += 1
        else:
            loser = b_is if preferred == a_is else a_is
            per_model[preferred]["wins"] += 1
            per_model[loser]["losses"] += 1
            pairwise_wins[(preferred, loser)] += 1

        consistency_groups[
            (p["unordered_pair_key"], p["run_id"], p["seg_idx"])
        ].append(preferred)

    for m in per_model.values():
        decided = m["wins"] + m["losses"] + m["ties"]
        m["decided"] = decided
        m["win_rate"] = (m["wins"] / decided) if decided else None

    consistency = {
        "consistent_same_winner": 0,
        "flipped_disagreement": 0,
        "one_tie_one_decision": 0,
        "both_ties": 0,
        "incomplete": 0,
    }
    consistency_details: list[dict] = []
    for (pair_key, run_id, seg_idx), outcomes in consistency_groups.items():
        if any(o is None for o in outcomes):
            consistency["incomplete"] += 1
            label = "incomplete"
        else:
            non_tie = [o for o in outcomes if o != "tie"]
            n_tie = len(outcomes) - len(non_tie)
            if n_tie == 2:
                consistency["both_ties"] += 1
                label = "both_ties"
            elif n_tie == 1:
                consistency["one_tie_one_decision"] += 1
                label = "one_tie_one_decision"
            elif len(set(non_tie)) == 1:
                consistency["consistent_same_winner"] += 1
                label = "consistent_same_winner"
            else:
                consistency["flipped_disagreement"] += 1
                label = "flipped_disagreement"
        consistency_details.append({
            "unordered_pair": pair_key,
            "run_id": run_id, "seg_idx": seg_idx,
            "outcomes": outcomes, "label": label,
        })

    decided_side = side_pref["A"] + side_pref["B"]
    a_fraction = (side_pref["A"] / decided_side) if decided_side else None

    # --- Print ---
    print(f"\nListener (user_id): {chosen}")
    print(f"Pairs: {len(pairs_by_id)}  |  candidates: {', '.join(candidates)}")
    decided_total = sum(m['decided'] for m in per_model.values()) // 2
    print(f"Decided pairs: {decided_total} / {len(pairs_by_id)}\n")

    print(f"{'model':<20s} {'trials':>6s} {'win':>5s} {'loss':>5s} "
          f"{'tie':>5s} {'miss':>5s} {'win_rate':>9s}")
    print("-" * 70)
    ranked = sorted(
        per_model.items(),
        key=lambda kv: (kv[1]['win_rate'] is None, -(kv[1]['win_rate'] or 0)),
    )
    for c, m in ranked:
        wr_s = f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "—"
        print(f"{c:<20s} {m['trials']:>6d} {m['wins']:>5d} "
              f"{m['losses']:>5d} {m['ties']:>5d} {m['missing']:>5d} "
              f"{wr_s:>9s}")

    print()
    print("Order-bias (over decided A/B trials only — excludes ties/missing):")
    if a_fraction is not None:
        flag = ""
        if a_fraction < 0.4 or a_fraction > 0.6:
            flag = "  ** OUT OF [40%, 60%] BAND — order bias likely **"
        print(f"  A-preferred: {side_pref['A']}/{decided_side} "
              f"({a_fraction:.0%}){flag}")
    print(f"  ties: {side_pref['tie']}  |  missing: {side_pref['missing']}")

    print()
    print("Consistency (per unordered pair × fixture: did both orderings agree?):")
    for k, v in consistency.items():
        print(f"  {k:<28s} {v:>3d}")

    print()
    print("Pairwise wins matrix:")
    print(f"  {'winner':<20s} {'loser':<20s} {'count':>6s}")
    print("  " + "-" * 50)
    for (w, l), n in sorted(pairwise_wins.items(), key=lambda kv: -kv[1]):
        print(f"  {w:<20s} {l:<20s} {n:>6d}")

    SUMMARY_PATH.write_text(json.dumps({
        "doc": (
            "Tier L text-blinded preference roll-up (BleakHouse-dll8, "
            "symmetric N-way variant; scored from Potato TSV)."
        ),
        "source": str(args.tsv.relative_to(REPO_ROOT)),
        "listener": chosen,
        "candidates": candidates,
        "n_pairs": len(pairs_by_id),
        "decided_pairs": decided_total,
        "rng_seed_used_for_blinding": manifest.get("rng_seed"),
        "per_model": per_model,
        "ranked_by_win_rate": [c for c, _ in ranked],
        "order_bias": {
            "A_count": side_pref["A"],
            "B_count": side_pref["B"],
            "tie_count": side_pref["tie"],
            "missing_count": side_pref["missing"],
            "A_fraction_of_decided": a_fraction,
            "flag_if_outside_40_60_band": (
                a_fraction is not None and (a_fraction < 0.4 or a_fraction > 0.6)
            ),
        },
        "consistency": consistency,
        "consistency_details": consistency_details,
        "pairwise_wins": {f"{w}>>{l}": n for (w, l), n in pairwise_wins.items()},
        "pairwise_ties": {
            "__vs__".join(sorted(k)): n for k, n in pairwise_ties.items()
        },
    }, indent=2))
    print(f"\nWrote -> {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
