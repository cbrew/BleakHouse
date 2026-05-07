"""DVC → CAS one-shot migration (Phases A–D, no destruction).

Phase A — inventory: walk every .dvc file under the repo (33: 32 classic.dvc
+ 1 trevelyan_v2.dvc); expand <hash>.dir shard listings into per-file md5s;
walk dvc.lock phase4_audio* stages for legacy mp3 md5s. Output:
migration_inventory.json.

Phase B — verify R2 coverage: HEAD every unique md5 against R2. Abort on
miss unless --allow-r2-misses.

Phase C — populate local CAS: copy bytes into <BLEAKHOUSE_CAS_ROOT>/files/
md5/<prefix>/<rest>. Verify md5. Skip if already present. Source order:
DVC cache (on disk) → cas.pull from R2 (Phase B already proved coverage).

Phase D — replacement manifests: verify each existing audio/shards.json
against the inventory; write audio/assets.json for runs with legacy
non-shard mp3s; rename dvc_hash → md5 in every run_manifest.json.

Dry-run by default; --commit applies. NON-DESTRUCTIVE — no .dvc files,
DVC cache entries, or dvc.lock are removed (Phase E is a separate task).
Spec: docs/superpowers/specs/2026-05-07-cas-migration-design.md.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import yaml

from cas import store


_REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_dvc_cache_dir(repo_root: Path) -> Path:
    """Return the DVC cache directory.

    Reads .dvc/config and .dvc/config.local; later files override earlier.
    Falls back to <repo>/.dvc/cache if neither sets [cache] dir. Required
    because BleakHouse keeps the cache on an external drive
    (/Volumes/Crucial X9/...) — the default .dvc/cache only holds a small
    subset.
    """
    parser = configparser.ConfigParser()
    for cfg in (repo_root / ".dvc" / "config", repo_root / ".dvc" / "config.local"):
        if cfg.is_file():
            parser.read(cfg)
    if parser.has_section("cache") and parser.has_option("cache", "dir"):
        return Path(parser.get("cache", "dir"))
    return repo_root / ".dvc" / "cache"


# ---------------------------------------------------------------------------
# Phase A — parsers
# ---------------------------------------------------------------------------


def parse_dvc_outs(dvc_path: Path) -> list[dict[str, Any]]:
    """Parse a .dvc YAML file; return its `outs` entries as normalised dicts.

    Each result has md5 (without the .dir suffix), is_dir flag, size, nfiles
    (only meaningful for directories), and path.
    """
    raw = yaml.safe_load(dvc_path.read_text()) or {}
    out: list[dict[str, Any]] = []
    for entry in raw.get("outs", []):
        md5_raw = entry["md5"]
        is_dir = md5_raw.endswith(".dir")
        md5 = md5_raw[: -len(".dir")] if is_dir else md5_raw
        out.append(
            {
                "md5": md5,
                "is_dir": is_dir,
                "size": entry.get("size"),
                "nfiles": entry.get("nfiles"),
                "path": entry["path"],
            }
        )
    return out


def collect_dvc_lock_mp3s(lock_yaml: str) -> list[dict[str, Any]]:
    """Walk dvc.lock; return one entry per unique mp3 out path under
    phase4_audio* stages.

    First-write wins on duplicate paths (same mp3 referenced by multiple
    stages — which happens because some stages declare outs from sibling
    runs).
    """
    parsed = yaml.safe_load(lock_yaml) or {}
    stages = parsed.get("stages", {})
    seen: dict[str, dict[str, Any]] = {}
    for stage_name, stage in stages.items():
        if not stage_name.startswith("phase4_audio"):
            continue
        for out in stage.get("outs", []):
            path = out.get("path", "")
            if not path.endswith(".mp3"):
                continue
            if path in seen:
                continue
            run_id, _, filename = path.rpartition("/")
            run_id = run_id.removeprefix("data/runs/").removesuffix("/audio")
            seen[path] = {
                "run_id": run_id,
                "filename": filename,
                "path": path,
                "md5": out["md5"],
                "size": out.get("size"),
            }
    return list(seen.values())


def expand_dir_listing(listing_bytes: bytes) -> list[dict[str, str]]:
    """Parse a DVC directory-listing blob (JSON list of {md5, relpath, ...})."""
    return [
        {"md5": e["md5"], "relpath": e["relpath"]}
        for e in json.loads(listing_bytes.decode())
    ]


# ---------------------------------------------------------------------------
# Phase B — verify R2 coverage
# ---------------------------------------------------------------------------


def verify_r2_coverage(
    md5s: Iterable[str],
    *,
    has_remote: Callable[[str], bool] = store.has_remote,
    allow_misses: bool = False,
) -> tuple[set[str], set[str]]:
    """HEAD every md5 against R2; return (hits, misses).

    Aborts with RuntimeError on any miss unless `allow_misses=True`.
    """
    hits: set[str] = set()
    misses: set[str] = set()
    for md5 in md5s:
        (hits if has_remote(md5) else misses).add(md5)
    if misses and not allow_misses:
        sample = sorted(misses)[:5]
        raise RuntimeError(
            f"{len(misses)} md5s missing in R2 (sample: {sample}). "
            "Pass --allow-r2-misses to proceed."
        )
    return hits, misses


# ---------------------------------------------------------------------------
# Phase C — populate local CAS
# ---------------------------------------------------------------------------


def _md5_of_file(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def populate_local_cas(
    sources: Iterable[tuple[str, Path]],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Copy each (expected_md5, source_path) into the CAS.

    Idempotent: blobs already in CAS are skipped. Each source is hashed and
    checked against expected md5; mismatch raises. dry_run=True hashes/checks
    but does not write.

    Returns (populated_count, skipped_count).
    """
    populated = 0
    skipped = 0
    for expected_md5, src in sources:
        if store.has_local(expected_md5):
            skipped += 1
            continue
        actual = _md5_of_file(src)
        if actual != expected_md5:
            raise RuntimeError(
                f"md5 mismatch for {src}: expected {expected_md5}, got {actual}"
            )
        if not dry_run:
            placed = store.put(src)
            if placed != expected_md5:
                raise RuntimeError(
                    f"cas.put returned {placed}, expected {expected_md5}"
                )
        populated += 1
    return populated, skipped


# ---------------------------------------------------------------------------
# Phase D — replacement manifests
# ---------------------------------------------------------------------------


def write_audio_assets(
    run_dir: Path,
    legacy_mp3s: list[dict[str, str]],
    *,
    dry_run: bool,
) -> Path:
    """Write run_dir/audio/assets.json from legacy mp3 inventory.

    Schema: {schema_version: 1, assets: {filename: md5}}.
    Returns the target path (whether written or not).
    """
    target = run_dir / "audio" / "assets.json"
    payload = {
        "schema_version": 1,
        "assets": {entry["filename"]: entry["md5"] for entry in legacy_mp3s},
    }
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n")
    return target


def _rename_recursive(node: Any) -> bool:
    """Walk dict/list; rename 'dvc_hash' → 'md5' in place. Return True if any
    change."""
    changed = False
    if isinstance(node, dict):
        if "dvc_hash" in node:
            node["md5"] = node.pop("dvc_hash")
            changed = True
        for v in node.values():
            if _rename_recursive(v):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _rename_recursive(item):
                changed = True
    return changed


def rename_dvc_hash_in_manifest(manifest_path: Path, *, dry_run: bool) -> bool:
    """Rename every `dvc_hash` field to `md5` in the manifest. Idempotent.

    Returns True if any rename happened.
    """
    data = json.loads(manifest_path.read_text())
    changed = _rename_recursive(data)
    if changed and not dry_run:
        manifest_path.write_text(json.dumps(data, indent=2) + "\n")
    return changed


def verify_shards_manifest(run_dir: Path, *, expected_md5s: set[str]) -> None:
    """Confirm an existing audio/shards.json carries every expected md5.

    The migration generator writes shards.json directly; this is a sanity
    check, not an overwrite.
    """
    target = run_dir / "audio" / "shards.json"
    if not target.is_file():
        raise RuntimeError(f"shards.json missing for {run_dir.name}")
    data = json.loads(target.read_text())
    actual = {s["md5"] for s in data.get("shards", [])}
    missing = expected_md5s - actual
    if missing:
        raise RuntimeError(
            f"shards.json drift in {run_dir.name}: "
            f"{len(missing)} expected md5s absent (sample: {sorted(missing)[:3]})"
        )


# ---------------------------------------------------------------------------
# Phase A driver — discover .dvc files, build full inventory
# ---------------------------------------------------------------------------


def discover_dvc_files(repo_root: Path) -> list[Path]:
    """Every .dvc sidecar under data/runs/."""
    return sorted((repo_root / "data" / "runs").rglob("*.dvc"))


def _fetch_dir_listing(md5: str, dvc_cache: Path) -> bytes:
    """Read a directory-listing blob from the DVC cache.

    DVC stores .dir listings at <cache>/files/md5/<prefix>/<rest>.dir (the
    suffix is on the on-disk filename). No R2 fallback: directory listings
    are DVC-internal artifacts; if they're not in the local cache we need
    the operator to plug in the external cache drive.
    """
    cached = dvc_cache / "files" / "md5" / md5[:2] / (md5[2:] + ".dir")
    if not cached.is_file():
        raise FileNotFoundError(
            f"DVC dir-listing for {md5} missing at {cached}; "
            "external cache drive may be unmounted"
        )
    return cached.read_bytes()


def build_inventory(
    repo_root: Path,
    *,
    fetch_dir_listing: Callable[[str], bytes] | None = None,
    dvc_cache: Path | None = None,
) -> dict[str, Any]:
    """Combine .dvc shard outs + dvc.lock legacy mp3s into the inventory."""
    if fetch_dir_listing is None:
        cache = dvc_cache if dvc_cache is not None else resolve_dvc_cache_dir(repo_root)

        def fetch(md5: str) -> bytes:
            return _fetch_dir_listing(md5, cache)
    else:
        fetch = fetch_dir_listing  # type: ignore[assignment]

    dvc_shards: list[dict[str, Any]] = []
    for dvc in discover_dvc_files(repo_root):
        for entry in parse_dvc_outs(dvc):
            run_id = dvc.parent.parent.parent.name  # .../runs/<run>/audio/shards/x.dvc
            profile = dvc.stem
            shard = {
                "dvc_file": str(dvc.relative_to(repo_root)),
                "run_id": run_id,
                "profile": profile,
                "dir_md5": entry["md5"] if entry["is_dir"] else None,
                "size": entry["size"],
                "nfiles": entry["nfiles"],
                "files": [],
            }
            if entry["is_dir"]:
                listing = fetch(entry["md5"])
                shard["files"] = expand_dir_listing(listing)
            dvc_shards.append(shard)

    lock_path = repo_root / "dvc.lock"
    legacy_mp3s = (
        collect_dvc_lock_mp3s(lock_path.read_text())
        if lock_path.is_file()
        else []
    )

    all_md5s: set[str] = set()
    shard_files_total = 0
    for shard in dvc_shards:
        for f in shard["files"]:
            all_md5s.add(f["md5"])
            shard_files_total += 1
    for entry in legacy_mp3s:
        all_md5s.add(entry["md5"])

    return {
        "schema_version": 1,
        "dvc_shards": dvc_shards,
        "legacy_mp3s": legacy_mp3s,
        "summary": {
            "dvc_shard_dirs": len(dvc_shards),
            "shard_files_total": shard_files_total,
            "legacy_mp3s_total": len(legacy_mp3s),
            "unique_md5s": len(all_md5s),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_inventory(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    dvc_cache = Path(args.dvc_cache) if args.dvc_cache else None
    inv = build_inventory(repo, dvc_cache=dvc_cache)
    out = Path(args.out) if args.out else repo / "migration_inventory.json"
    out.write_text(json.dumps(inv, indent=2) + "\n")
    print(json.dumps(inv["summary"], indent=2))
    print(f"wrote {out.relative_to(repo) if out.is_relative_to(repo) else out}")
    return 0


def _all_md5s(inv: dict[str, Any]) -> set[str]:
    md5s: set[str] = set()
    for shard in inv["dvc_shards"]:
        for f in shard["files"]:
            md5s.add(f["md5"])
    for entry in inv["legacy_mp3s"]:
        md5s.add(entry["md5"])
    return md5s


def _cmd_verify(args: argparse.Namespace) -> int:
    inv = json.loads(Path(args.inventory).read_text())
    md5s = _all_md5s(inv)
    print(f"checking {len(md5s)} unique md5s against R2...")
    hits, misses = verify_r2_coverage(md5s, allow_misses=args.allow_r2_misses)
    print(f"hits: {len(hits)}  misses: {len(misses)}")
    if misses:
        print(f"misses (first 5): {sorted(misses)[:5]}")
    return 0


def _resolve_source_paths(
    inv: dict[str, Any], dvc_cache: Path
) -> list[tuple[str, Path]]:
    """For every md5 in the inventory, return (md5, source_path).

    Prefer DVC cache; otherwise pull from R2 into the local CAS first
    (which doubles as the populate step for that md5). Sources used here
    feed `populate_local_cas`, which performs the verified copy.
    """
    pairs: list[tuple[str, Path]] = []
    for shard in inv["dvc_shards"]:
        for f in shard["files"]:
            pairs.append((f["md5"], _source_for(f["md5"], dvc_cache)))
    for entry in inv["legacy_mp3s"]:
        pairs.append((entry["md5"], _source_for(entry["md5"], dvc_cache)))
    return pairs


def _source_for(md5: str, dvc_cache: Path) -> Path:
    cached = dvc_cache / "files" / "md5" / md5[:2] / md5[2:]
    if cached.is_file():
        return cached
    return store.pull(md5)


def _cmd_populate(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    inv = json.loads(Path(args.inventory).read_text())
    dvc_cache = Path(args.dvc_cache) if args.dvc_cache else resolve_dvc_cache_dir(repo)
    pairs = _resolve_source_paths(inv, dvc_cache)
    populated, skipped = populate_local_cas(pairs, dry_run=not args.commit)
    print(f"populated: {populated}  skipped: {skipped}  dry_run: {not args.commit}")
    return 0


def _legacy_by_run(
    inv: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    by_run: dict[str, list[dict[str, str]]] = {}
    for entry in inv["legacy_mp3s"]:
        by_run.setdefault(entry["run_id"], []).append(
            {"filename": entry["filename"], "md5": entry["md5"]}
        )
    return by_run


def _shards_by_run(inv: dict[str, Any]) -> dict[str, set[str]]:
    by_run: dict[str, set[str]] = {}
    for shard in inv["dvc_shards"]:
        md5s = {f["md5"] for f in shard["files"]}
        by_run.setdefault(shard["run_id"], set()).update(md5s)
    return by_run


def _cmd_manifests(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    inv = json.loads(Path(args.inventory).read_text())
    runs_dir = repo / "data" / "runs"

    legacy = _legacy_by_run(inv)
    shards = _shards_by_run(inv)

    assets_written = 0
    shards_verified = 0
    for run_id, entries in legacy.items():
        run_dir = runs_dir / run_id
        if not run_dir.is_dir():
            print(f"skip legacy assets for {run_id}: run dir missing", file=sys.stderr)
            continue
        write_audio_assets(run_dir, entries, dry_run=not args.commit)
        assets_written += 1
    for run_id, md5s in shards.items():
        run_dir = runs_dir / run_id
        if not run_dir.is_dir():
            print(f"skip shards verify for {run_id}: run dir missing", file=sys.stderr)
            continue
        verify_shards_manifest(run_dir, expected_md5s=md5s)
        shards_verified += 1

    renamed = 0
    for manifest in runs_dir.rglob("run_manifest.json"):
        if rename_dvc_hash_in_manifest(manifest, dry_run=not args.commit):
            renamed += 1

    print(
        f"audio/assets.json: {assets_written} runs  "
        f"shards.json verified: {shards_verified} runs  "
        f"run_manifest.json renamed: {renamed}  "
        f"dry_run: {not args.commit}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--repo", default=str(_REPO_ROOT), help="repo root (default: this repo)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inv = sub.add_parser("inventory", help="Phase A — write migration_inventory.json")
    p_inv.add_argument("--out", default=None)
    p_inv.add_argument(
        "--dvc-cache",
        default=None,
        help="DVC cache dir (default: read from .dvc/config[.local])",
    )
    p_inv.set_defaults(func=_cmd_inventory)

    p_ver = sub.add_parser("verify", help="Phase B — HEAD every md5 against R2")
    p_ver.add_argument("--inventory", default="migration_inventory.json")
    p_ver.add_argument("--allow-r2-misses", action="store_true")
    p_ver.set_defaults(func=_cmd_verify)

    p_pop = sub.add_parser("populate", help="Phase C — copy bytes into local CAS")
    p_pop.add_argument("--inventory", default="migration_inventory.json")
    p_pop.add_argument("--commit", action="store_true")
    p_pop.add_argument(
        "--dvc-cache",
        default=None,
        help="DVC cache dir (default: read from .dvc/config[.local])",
    )
    p_pop.set_defaults(func=_cmd_populate)

    p_man = sub.add_parser(
        "manifests", help="Phase D — assets.json + verify shards + rename dvc_hash"
    )
    p_man.add_argument("--inventory", default="migration_inventory.json")
    p_man.add_argument("--commit", action="store_true")
    p_man.set_defaults(func=_cmd_manifests)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
