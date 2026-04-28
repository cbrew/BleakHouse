"""CLI for inspecting + populating the experiment ledger."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backfill import scan_runs_dir
from .store import Store

DEFAULT_DB = Path("data/experiments.db")
DEFAULT_RUNS = Path("data/runs")


def cmd_scan(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    summary = scan_runs_dir(store, args.runs_dir)
    print(f"scanned: {summary['scanned']}, skipped: {summary['skipped']}")
    print(f"episodes_inserted: {summary['episodes_inserted']}, "
          f"scripts_inserted: {summary['scripts_inserted']}")
    if summary["errors"]:
        print(f"errors: {len(summary['errors'])}")
        for e in summary["errors"][:5]:
            print(f"  {e['run_dir']}: {e['error']}")
    return 0


def cmd_list_episodes(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    for ep in store.list_episodes(novel=args.novel):
        print(f"{ep.id:4d}  {ep.label:50s}  {ep.novel}/{ep.panel}/{ep.pipeline}"
              f"  hostprep={ep.hostprep}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    eps = [e for e in store.list_episodes() if e.label == args.label]
    if not eps:
        print(f"no episode with label {args.label!r}", file=sys.stderr)
        return 1
    ep = eps[0]
    print(f"episode {ep.id}: {ep.label}  ({ep.novel}/{ep.panel}/{ep.pipeline}"
          f", hostprep={ep.hostprep})")
    for sv in store.list_scripts_for_episode(ep.id):
        print(f"  script {sv.id}  {sv.path}  segs={sv.n_segments} "
              f"turns={sv.n_turns} utts={sv.n_utterances}")
        for a in store.list_audio_for_script(sv.id):
            print(f"    audio {a.id}  {a.name}  {a.path}  hash={a.dvc_hash}  "
                  f"dur={a.duration_s}")
        for ev in store.list_evaluations_for_script(sv.id):
            print(f"    eval {ev.id}  {ev.metric_kind}  {ev.metric}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m enrichment.expdb")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_scan = sub.add_parser("scan")
    sp_scan.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    sp_scan.set_defaults(fn=cmd_scan)

    sp_ls = sub.add_parser("list-episodes")
    sp_ls.add_argument("--novel", default=None)
    sp_ls.set_defaults(fn=cmd_list_episodes)

    sp_show = sub.add_parser("show")
    sp_show.add_argument("label")
    sp_show.set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
