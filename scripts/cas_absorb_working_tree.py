"""One-shot: absorb working-tree shard mp3s into the local CAS.

For every data/runs/<run>/audio/shards/<profile>/*.mp3 in the working
tree:
  1. cas.store.put it (hashes + copies into <CAS_ROOT>/files/md5/...)
  2. Verify the returned md5 matches the one already recorded in
     audio/shards.json for the same shard
  3. Unlink the working-tree file
  4. After all shards in a run are absorbed, also remove the now-empty
     audio/shards/ directory tree

Idempotent: re-running on a clean tree is a no-op. Dry-run by default;
--commit applies. cas.store.put is itself idempotent, so partial runs
are safe to retry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cas import store as cas_store

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "runs"


def absorb_run(run_dir: Path, *, dry_run: bool) -> tuple[int, int]:
    """Returns (absorbed, mismatches) for one run."""
    shards_path = run_dir / "audio" / "shards.json"
    if not shards_path.is_file():
        return 0, 0
    manifest = json.loads(shards_path.read_text())
    profile = manifest.get("profile", "classic")
    shard_dir = run_dir / "audio" / "shards" / profile
    if not shard_dir.is_dir():
        return 0, 0

    md5_by_file = {s["file"]: s["md5"] for s in manifest.get("shards", [])}
    absorbed = 0
    mismatches = 0
    for mp3 in sorted(shard_dir.glob("*.mp3")):
        expected = md5_by_file.get(mp3.name)
        if expected is None:
            print(f"  skip {mp3.relative_to(REPO_ROOT)}: not in shards.json",
                  file=sys.stderr)
            continue
        if dry_run:
            absorbed += 1
            continue
        actual = cas_store.put(mp3)
        if actual != expected:
            print(
                f"  MISMATCH {mp3.relative_to(REPO_ROOT)}: "
                f"shards.json={expected[:8]}... actual={actual[:8]}...",
                file=sys.stderr,
            )
            mismatches += 1
            continue
        mp3.unlink()
        absorbed += 1

    if not dry_run and mismatches == 0:
        # Remove the now-empty profile dir + parent shards/ if empty
        try:
            shard_dir.rmdir()
            shard_dir.parent.rmdir()
        except OSError:
            pass  # other profiles or files still present
    return absorbed, mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--commit", action="store_true",
                        help="actually cas.put + delete; default is dry-run")
    args = parser.parse_args()

    total_absorbed = 0
    total_mismatches = 0
    runs_with_files = 0
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        absorbed, mismatches = absorb_run(run_dir, dry_run=not args.commit)
        if absorbed or mismatches:
            print(f"{run_dir.name}: absorbed={absorbed} mismatches={mismatches}")
            runs_with_files += 1
        total_absorbed += absorbed
        total_mismatches += mismatches

    print(f"---\n{runs_with_files} runs touched")
    print(f"total absorbed: {total_absorbed}")
    print(f"total mismatches: {total_mismatches}")
    print(f"dry_run: {not args.commit}")
    return 1 if total_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
